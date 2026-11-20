from __future__ import annotations

import csv
import io
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from app import evaluator, hardware, llm
from app.cache import Cache
from app.config import settings
from app.store import Store, fingerprint

VERSION = '2.1.0'
EPS = 0.005

@asynccontextmanager
async def lifespan(_app: FastAPI):
    threading.Thread(target=_warm_models, daemon=True).start()  # oculta el tiempo de carga de los modelos
    yield


app = FastAPI(title='ExamAgent NDE', version=VERSION, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])
store = Store(settings.data_dir)

# ---------------------------------------------------------------- seguridad local
@app.middleware('http')
async def require_header_for_writes(request: Request, call_next):
    # Las páginas web externas no pueden enviar cabeceras personalizadas sin preflight CORS
    # (que este servicio nunca autoriza), así que solo el panel y la extensión pueden escribir.
    if request.method in ('POST', 'PUT', 'DELETE') and request.headers.get('x-examagent') != '1':
        return JSONResponse({'detail': 'Cabecera X-ExamAgent requerida.'}, status_code=403)
    return await call_next(request)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- estado transitorio
eval_job: dict[str, Any] = {'state': 'idle', 'done': 0, 'total': 0, 'current': None, 'error': None, 'phase': 'idle',
                            'cancel': False, 'started_at': None, 'finished_at': None, 'run': None}
pull_job: dict[str, Any] = {'state': 'idle', 'model': None, 'percent': None, 'status': '', 'error': None}
publish: dict[str, Any] = {'run_id': None, 'state': 'idle', 'mode': None, 'plan': None, 'events': [],
                           'done': 0, 'total': 0, 'written': 0, 'verified': 0, 'skipped': 0, 'failed': 0,
                           'simulated': 0, 'unverified': 0, 'stop': False, 'message': '',
                           'started_at': None, 'finished_at': None, 'last_event': None, 'verify': None}
job_lock = threading.Lock()


# ---------------------------------------------------------------- modelos
class BrowserSnapshot(BaseModel):
    url: str
    title: str = ''
    captured_at: str = ''
    capture_version: str = ''
    text: str = ''
    headings: list[str] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    capture_summary: dict[str, Any] = Field(default_factory=dict)
    viewport: dict[str, Any] = Field(default_factory=dict)


class EvaluateRequest(BaseModel):
    instructions: str | None = None
    mode: str = 'missing'  # missing | all | errors
    numbers: list[int] | None = None
    fresh: bool = False  # ignora la caché de decisiones


class OverrideRequest(BaseModel):
    score: float | None = None
    explanation: str | None = None
    clear: bool = False


class SettingsRequest(BaseModel):
    write_explanations: bool | None = None
    overwrite_explanations: bool | None = None
    force_all: bool | None = None
    time_budget_s: int | None = None


class PullRequest(BaseModel):
    models: list[str] | None = None


class PrepareRequest(BaseModel):
    mode: str = 'all'  # all | one | simulate


class PublishEvent(BaseModel):
    run_id: str
    type: str
    question_number: int | None = None
    result: str | None = None
    detail: str = ''
    message: str = ''
    stopped: bool = False
    snapshot: dict[str, Any] | None = None


# ---------------------------------------------------------------- cálculo de notas
def final_for(q: dict[str, Any]) -> dict[str, Any]:
    key = str(q.get('question_number'))
    res = store.data['results'].get(key)
    ov = store.data['overrides'].get(key) or {}
    ai_score = res.get('score') if res else None
    score = ov['score'] if ov.get('score') is not None else ai_score
    explanation = ov['explanation'] if ov.get('explanation') is not None else (res or {}).get('explanation', '')
    observed = (q.get('score') or {}).get('earned')
    maximum = (q.get('score') or {}).get('maximum')
    if score is not None and maximum is not None:
        score = max(0.0, min(float(maximum), float(score)))
    score_changed = score is not None and (observed is None or abs(float(score) - float(observed)) > EPS)
    done = store.data['published'].get(key) or {}
    expl_pending = ov.get('explanation') is not None and done.get('explanation') != (explanation or '')
    return {'score': score, 'explanation': explanation or '', 'observed': observed, 'maximum': maximum,
            'score_edited': ov.get('score') is not None, 'explanation_edited': ov.get('explanation') is not None,
            'explanation_pending': expl_pending, 'changed': score_changed or expl_pending, 'score_changed': score_changed,
            'result': res}


def totals() -> dict[str, Any]:
    snap = store.data['snapshot'] or {}
    ges = ai = final = maxi = 0.0
    low = changes = unscored = unevaluated = 0
    for q in snap.get('questions', []):
        f = final_for(q)
        res = f['result']
        maximum = f['maximum'] or 0.0
        maxi += maximum
        ges += f['observed'] or 0.0
        ai_s = res.get('score') if res else None
        ai += ai_s if ai_s is not None else (f['observed'] or 0.0)
        final += f['score'] if f['score'] is not None else (f['observed'] or 0.0)
        if f['score'] is None and f['observed'] is None:
            unscored += 1
        if res is None:
            unevaluated += 1
        elif res.get('low_confidence') or res.get('status') != 'evaluated':
            low += 1
        if f['changed']:
            changes += 1
    return {'ges_total': round(ges, 2), 'ai_total': round(ai, 2), 'final_total': round(final, 2),
            'max_total': round(maxi, 2), 'percent': round(100 * final / maxi, 1) if maxi else None,
            'doubtful': low, 'changes': changes, 'unscored': unscored, 'unevaluated': unevaluated}


def question_view(q: dict[str, Any]) -> dict[str, Any]:
    f = final_for(q)
    return {
        'number': q.get('question_number'), 'text': q.get('question_text') or q.get('raw_text') or '',
        'lines': (q.get('lines') or [])[:40], 'type': q.get('question_type'),
        'answer_status': q.get('answer_status'),
        'selected': [a.get('text') or a.get('value') or '' for a in q.get('selected_answers', [])],
        'options': [{'text': o.get('text') or o.get('value') or '', 'checked': bool(o.get('checked'))}
                    for o in q.get('options', [])],
        'observed': f['observed'], 'maximum': f['maximum'], 'result': f['result'],
        'final_score': f['score'], 'final_explanation': f['explanation'],
        'score_edited': f['score_edited'], 'explanation_edited': f['explanation_edited'],
        'changed': f['changed'], 'has_edit_button': q.get('has_edit_button'),
    }


def publish_public() -> dict[str, Any]:
    p = {k: v for k, v in publish.items() if k not in ('plan', 'events')}
    p['events'] = publish['events'][-60:]
    if p['state'] == 'running' and publish['last_event'] and time.time() - publish['last_event'] > 120:
        p['state'] = 'stalled'
    return p


def build_state(light: bool = False) -> dict[str, Any]:
    snap = store.data['snapshot']
    out: dict[str, Any] = {
        'version': VERSION, 'models': {k: v for k, v in current_models().items() if k in ('fast', 'strong', 'class', 'workers', 'missing', 'reachable', 'gpu')},
        'has_snapshot': snap is not None, 'perf': perf_snapshot(), 'pull': dict(pull_job),
        'totals': totals() if snap else None, 'eval': {k: v for k, v in eval_job.items() if k not in ('cancel', 'run')},
        'publish': publish_public(), 'settings': store.data['settings'],
        'instructions': store.data['instructions'],
    }
    if snap:
        out['exam'] = {'url': snap.get('url'), 'title': snap.get('title'), 'captured_at': snap.get('captured_at'),
                       'received_at': snap.get('received_at'), 'questions': len(snap.get('questions', []))}
        if not light:
            out['questions'] = [question_view(q) for q in snap.get('questions', [])]
    return out


# ---------------------------------------------------------------- modelos, hardware y caché
cache = Cache(Path(settings.data_dir) / 'cache.db')
_hw: dict[str, Any] = {}
_plan_cache: dict[str, Any] = {'at': 0.0, 'value': None}


def hardware_info() -> dict[str, Any]:
    if not _hw:
        _hw.update(hardware.detect())
    return _hw


def current_models(force: bool = False) -> dict[str, Any]:
    if not force and _plan_cache['value'] and time.time() - _plan_cache['at'] < 20:
        return _plan_cache['value']
    try:
        installed: list[str] | None = llm.list_models()
    except Exception:  # noqa: BLE001
        installed = None
    plan = hardware.resolve(hardware_info(), installed, settings.fast_model, settings.strong_model, settings.eval_workers)
    plan.update(installed=installed, reachable=installed is not None)
    _plan_cache.update(at=time.time(), value=plan)
    return plan


def _warm_models() -> None:
    plan = current_models(True)
    if plan['reachable']:
        for m in dict.fromkeys([plan['fast'], plan['strong']]):
            llm.warm(m)


def perf_snapshot() -> dict[str, Any]:
    by = llm.stats.snapshot()
    run = eval_job.get('run')
    return {'llm': by, 'run': run.snapshot() if run else None, 'cache_entries': cache.count(),
            'tokens_out': int(sum(v['tokens_out'] for v in by.values())), 'calls': int(sum(v['calls'] for v in by.values()))}


# ---------------------------------------------------------------- evaluación en segundo plano
def start_eval(numbers: list[int], fresh: bool = False) -> bool:
    with job_lock:
        if eval_job['state'] == 'running' or not numbers:
            return False
        eval_job.update(state='running', done=0, total=len(numbers), current=None, error=None, cancel=False,
                        phase='preparando', started_at=now_iso(), finished_at=None, run=None)
    threading.Thread(target=_run_eval, args=(numbers, fresh), daemon=True).start()
    return True


def _run_eval(numbers: list[int], fresh: bool) -> None:
    snap = store.data['snapshot']
    fp = store.data['fingerprint']
    wanted = set(numbers)
    questions = [q for q in snap['questions'] if q['question_number'] in wanted]
    instructions = store.data['instructions']
    rs = evaluator.RunStats()
    eval_job['run'] = rs
    llm.stats.reset()

    def still_valid() -> bool:
        return store.data['fingerprint'] == fp

    def save(n: int, res: dict[str, Any]) -> None:
        if still_valid():
            with store.lock:
                store.data['results'][str(n)] = res
                store.save()

    def save_expl(n: int, text: str) -> None:
        if still_valid():
            with store.lock:
                r = store.data['results'].get(str(n))
                if r is not None:
                    r['explanation'] = text
                    store.save()

    def progress(done: int, total: int, phase: str) -> None:
        eval_job.update(done=done, total=total, phase=phase)

    try:
        models = current_models(True)
        if not models['reachable']:
            raise llm.OllamaError('Ollama no responde. Inícialo (ollama serve) y vuelve a intentarlo.')
        evaluator.run_cascade(questions, instructions, models=models, cache=cache, save=save, save_explanation=save_expl,
                              progress=progress, cancelled=lambda: eval_job['cancel'] or not still_valid(), fresh=fresh,
                              budget_s=int(store.data['settings'].get('time_budget_s') or 0), run_stats=rs)
        eval_job['state'] = 'cancelled' if eval_job['cancel'] else 'done'
    except Exception as exc:  # noqa: BLE001
        eval_job.update(state='error', error=str(exc))
    finally:
        eval_job['finished_at'] = now_iso()
        eval_job['current'] = None


def numbers_to_evaluate(mode: str, explicit: list[int] | None) -> list[int]:
    snap = store.data['snapshot'] or {}
    all_numbers = [q['question_number'] for q in snap.get('questions', [])]
    if explicit:
        return [n for n in all_numbers if n in set(explicit)]
    results = store.data['results']
    if mode == 'all':
        return all_numbers
    if mode == 'errors':
        return [n for n in all_numbers if (results.get(str(n)) or {}).get('status') in ('error', 'skipped')]
    return [n for n in all_numbers if str(n) not in results or results[str(n)].get('status') == 'error'
            or results[str(n)].get('tentative')]


# ---------------------------------------------------------------- páginas y estado
@app.get('/', response_class=HTMLResponse)
def dashboard():
    return (Path(__file__).parent / 'dashboard.html').read_text(encoding='utf-8')


@app.get('/health')
def health():
    m = current_models()
    return {'status': 'ok', 'app_version': VERSION, 'model': m['strong'], 'fast_model': m['fast']}


@app.get('/model/status')
def model_status():
    m = current_models(True)
    if not m['reachable']:
        return {'reachable': False, 'fast': m['fast'], 'strong': m['strong'], 'error': 'Ollama no responde'}
    return {'reachable': True, 'fast': m['fast'], 'strong': m['strong'], 'missing': m['missing'], 'models': m['installed'],
            'model_available': not m['missing'], 'class': m['class']}


@app.get('/hardware')
def hardware_endpoint(bench: bool = False):
    plan = current_models(True)
    out: dict[str, Any] = {'hardware': hardware_info(), 'plan': {k: v for k, v in plan.items() if k != 'installed'},
                           'installed': plan['installed'],
                           'ollama_running': [{'model': r.get('name'), 'size_gb': round((r.get('size') or 0) / 2**30, 1),
                                               'in_vram_gb': round((r.get('size_vram') or 0) / 2**30, 1)} for r in llm.running_models()]}
    if bench and plan['reachable']:
        try:
            out['benchmark'] = llm.benchmark(plan['fast'])
        except Exception as exc:  # noqa: BLE001
            out['benchmark'] = {'error': str(exc)}
    return out


@app.post('/models/pull')
def models_pull(req: PullRequest):
    if pull_job['state'] == 'running':
        raise HTTPException(409, 'Ya hay una descarga en curso.')
    plan = current_models(True)
    allowed = {m for pair in hardware.CLASSES.values() for prefs in pair for m in prefs} | {settings.fast_model, settings.strong_model}
    wanted = req.models or plan['missing']
    wanted = [m for m in wanted if m in allowed and re.fullmatch(r'[A-Za-z0-9._:/-]+', m)]
    if not wanted:
        raise HTTPException(400, 'No hay modelos que descargar.')

    def work() -> None:
        pull_job.update(state='running', error=None)
        try:
            for m in wanted:
                pull_job.update(model=m, percent=0, status='iniciando')
                llm.pull(m, lambda st, pct: pull_job.update(status=st, percent=pct))
            pull_job.update(state='done', percent=100, status='listo')
            _plan_cache['value'] = None
            _warm_models()
        except Exception as exc:  # noqa: BLE001
            pull_job.update(state='error', error=str(exc))

    threading.Thread(target=work, daemon=True).start()
    return {'started': True, 'models': wanted}


@app.get('/state')
def get_state(light: bool = False):
    return build_state(light)


# ---------------------------------------------------------------- captura
@app.post('/browser/snapshot')
def receive_snapshot(snapshot: BrowserSnapshot, auto: bool = True):
    payload = snapshot.model_dump()
    payload['received_at'] = now_iso()
    new_fp = fingerprint(payload)
    with store.lock:
        if new_fp != store.data['fingerprint']:
            eval_job['cancel'] = True  # corta una evaluación del examen anterior
            store.data.update(results={}, overrides={}, published={}, fingerprint=new_fp)
        store.data['snapshot'] = payload
        store.save()
    started = False
    if auto:
        for _ in range(60):  # espera a que termine de cancelarse una evaluación del examen anterior
            if eval_job['state'] != 'running':
                break
            time.sleep(0.1)
        started = start_eval(numbers_to_evaluate('missing', None))
    s = totals()
    return {'accepted': True, 'questions': len(payload['questions']), 'evaluation_started': started, **s}


# ---------------------------------------------------------------- evaluación / edición
@app.post('/evaluate')
def evaluate(req: EvaluateRequest):
    if store.data['snapshot'] is None:
        raise HTTPException(404, 'Primero analiza el examen con la extensión.')
    if req.instructions is not None:
        store.data['instructions'] = req.instructions.strip()
        store.save()
    numbers = numbers_to_evaluate(req.mode, req.numbers)
    if req.mode == 'all' and not req.numbers:
        with store.lock:  # al re-evaluar todo se conservan las ediciones del docente
            store.data['results'] = {}
            store.save()
    if not start_eval(numbers, fresh=req.fresh or req.mode == 'all'):
        raise HTTPException(409, 'Ya hay una evaluación en curso o no hay nada que evaluar.')
    return {'started': True, 'total': len(numbers)}


@app.post('/evaluate/cancel')
def evaluate_cancel():
    eval_job['cancel'] = True
    return {'cancelling': True}


@app.post('/question/{number}/override')
def set_override(number: int, req: OverrideRequest):
    snap = store.data['snapshot']
    q = next((x for x in (snap or {}).get('questions', []) if x.get('question_number') == number), None)
    if q is None:
        raise HTTPException(404, 'Pregunta no encontrada.')
    key = str(number)
    with store.lock:
        if req.clear:
            store.data['overrides'].pop(key, None)
        else:
            ov = store.data['overrides'].setdefault(key, {})
            if req.score is not None:
                maximum = (q.get('score') or {}).get('maximum')
                if req.score < 0 or (maximum is not None and req.score > maximum + EPS):
                    raise HTTPException(400, f'La nota debe estar entre 0 y {maximum}.')
                ov['score'] = round(float(req.score), 2)
            if req.explanation is not None:
                ov['explanation'] = req.explanation.strip()[:2000]
            ov['edited_at'] = now_iso()
        store.save()
    return {'saved': True, 'question': question_view(q), 'totals': totals()}


@app.post('/settings')
def update_settings(req: SettingsRequest):
    with store.lock:
        upd = {k: v for k, v in req.model_dump().items() if v is not None}
        if 'time_budget_s' in upd:
            upd['time_budget_s'] = max(0, min(36000, int(upd['time_budget_s'])))
        store.data['settings'].update(upd)
        store.save()
    return store.data['settings']


# ---------------------------------------------------------------- publicación en GES
def build_plan(mode: str) -> dict[str, Any]:
    snap = store.data['snapshot']
    cfg = store.data['settings']
    items = []
    for q in snap['questions']:
        f = final_for(q)
        if f['score'] is None:
            continue
        needs = f['changed'] or cfg['force_all']
        if not needs:
            continue
        items.append({
            'question_number': q['question_number'], 'question_id': q.get('question_id'),
            'text_probe': (q.get('question_text') or q.get('raw_text') or '')[:60],
            'current_score': f['observed'], 'maximum': f['maximum'], 'target_score': f['score'],
            'explanation': f['explanation'], 'explanation_edited': f['explanation_pending'],
            'force': bool(cfg['force_all']),
        })
    if mode == 'one':
        items = items[:1]
    elif mode == 'simulate':
        items = items[:3]
    return {'url': snap.get('url'), 'title': snap.get('title'), 'mode': mode, 'items': items,
            'write_explanations': cfg['write_explanations'], 'overwrite_explanations': cfg['overwrite_explanations']}


def log_event(kind: str, **data: Any) -> None:
    entry = {'at': now_iso(), 'type': kind, 'run_id': publish['run_id'], **data}
    publish['events'].append(entry)
    publish['events'] = publish['events'][-500:]
    publish['last_event'] = time.time()
    store.append_log(entry)


@app.post('/publish/prepare')
def publish_prepare(req: PrepareRequest):
    if store.data['snapshot'] is None:
        raise HTTPException(404, 'No hay examen capturado.')
    if req.mode not in ('all', 'one', 'simulate'):
        raise HTTPException(400, 'Modo inválido.')
    if publish['state'] == 'running':
        raise HTTPException(409, 'Ya hay una publicación en curso.')
    if eval_job['state'] == 'running':
        raise HTTPException(409, 'El modelo aún está evaluando. Espera a que termine.')
    plan = build_plan(req.mode)
    run_id = uuid.uuid4().hex[:12]
    publish.update(run_id=run_id, state='ready', mode=req.mode, plan=plan, events=[], done=0,
                   total=len(plan['items']), written=0, verified=0, skipped=0, failed=0, simulated=0,
                   unverified=0, stop=False, message='', started_at=now_iso(), finished_at=None,
                   last_event=time.time(), verify=None)
    log_event('prepared', mode=req.mode, total=len(plan['items']))
    if not plan['items']:
        publish.update(state='done', finished_at=now_iso(), message='No hay notas que subir: GES ya coincide.')
    return {'run_id': run_id, 'total': len(plan['items']), 'mode': req.mode, 'state': publish['state']}


@app.get('/publish/plan')
def publish_plan(run_id: str):
    if publish['run_id'] != run_id or publish['plan'] is None:
        raise HTTPException(404, 'Plan no encontrado.')
    return publish['plan']


@app.post('/publish/event')
def publish_event(ev: PublishEvent):
    if ev.run_id != publish['run_id']:
        raise HTTPException(404, 'Ejecución desconocida.')
    if ev.type == 'start':
        publish.update(state='running', message='Publicando…')
        log_event('start')
    elif ev.type == 'item':
        publish['done'] += 1
        if ev.result in ('written', 'skipped', 'failed', 'simulated', 'unverified'):
            key = {'written': 'written', 'skipped': 'skipped', 'failed': 'failed', 'simulated': 'simulated',
                   'unverified': 'unverified'}[ev.result]
            publish[key] += 1
            if ev.result == 'unverified':
                publish['written'] += 1
        log_event('item', question_number=ev.question_number, result=ev.result, detail=ev.detail)
    elif ev.type == 'warn':
        log_event('warn', question_number=ev.question_number, detail=ev.detail)
    elif ev.type == 'error':
        publish.update(state='error', message=ev.message, finished_at=now_iso())
        log_event('error', question_number=ev.question_number, detail=ev.message)
    elif ev.type == 'finish':
        if publish['state'] != 'error':
            publish['state'] = 'aborted' if ev.stopped else 'done'
        publish['finished_at'] = now_iso()
        if ev.snapshot and publish['mode'] != 'simulate':
            verify_after(ev.snapshot)
        publish['message'] = 'Detenido por el usuario.' if ev.stopped else ('Publicación terminada.' if publish['state'] == 'done' else publish['message'])
        log_event('finish', stopped=ev.stopped, verify=publish['verify'])
    return {'ok': True, 'stop': bool(publish['stop'])}


def verify_after(new_snapshot: dict[str, Any]) -> None:
    """Compara las notas visibles en GES tras publicar con las notas planificadas."""
    plan = (publish['plan'] or {}).get('items', [])
    by_number = {q.get('question_number'): q for q in new_snapshot.get('questions', [])}
    ok = bad = 0
    mismatches = []
    for it in plan:
        seen = ((by_number.get(it['question_number']) or {}).get('score') or {}).get('earned')
        if seen is not None and abs(seen - it['target_score']) <= EPS:
            ok += 1
        else:
            bad += 1
            mismatches.append({'question_number': it['question_number'], 'expected': it['target_score'], 'seen': seen})
    publish['verified'] = ok
    publish['verify'] = {'ok': ok, 'mismatch': bad, 'mismatches': mismatches[:20]}
    bad_numbers = {m['question_number'] for m in mismatches}
    with store.lock:
        for it in plan:
            if it['question_number'] not in bad_numbers:
                store.data['published'][str(it['question_number'])] = {'score': it['target_score'], 'explanation': it['explanation'] or ''}
        store.save()
    new_snapshot = {k: new_snapshot.get(k) for k in BrowserSnapshot.model_fields if k in new_snapshot}
    try:
        payload = BrowserSnapshot(**new_snapshot).model_dump()
        payload['received_at'] = now_iso()
        with store.lock:
            if fingerprint(payload) == store.data['fingerprint']:
                store.data['snapshot'] = payload
                store.save()
    except Exception:
        pass


@app.post('/publish/stop')
def publish_stop():
    publish['stop'] = True
    log_event('stop_requested')
    return {'stopping': True}


@app.post('/publish/abort')
def publish_abort(payload: dict[str, Any]):
    """El panel no pudo lanzar la extensión: se libera el estado."""
    publish.update(state='error', message=str(payload.get('message', 'No se pudo iniciar.')), finished_at=now_iso())
    log_event('error', detail=publish['message'])
    return {'ok': True}


# ---------------------------------------------------------------- exportación
@app.get('/export.csv')
def export_csv():
    snap = store.data['snapshot']
    if snap is None:
        raise HTTPException(404, 'No hay captura.')
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(['pregunta', 'texto', 'estado_respuesta', 'respuesta_estudiante', 'nota_ges', 'nota_ia', 'veredicto',
                'confianza', 'nota_final', 'maximo', 'editada_por_docente', 'explicacion_final', 'razon_ia'])
    for q in snap['questions']:
        f = final_for(q)
        res = f['result'] or {}
        w.writerow([q.get('question_number'), (q.get('question_text') or '')[:300], q.get('answer_status'),
                    ' | '.join(str(a.get('text') or a.get('value') or '') for a in q.get('selected_answers', [])),
                    f['observed'], res.get('score'), res.get('verdict'), res.get('confidence'), f['score'],
                    f['maximum'], f['score_edited'] or f['explanation_edited'], f['explanation'],
                    res.get('reasoning_summary')])
    return StreamingResponse(iter(['\ufeff' + out.getvalue()]), media_type='text/csv; charset=utf-8',
                             headers={'Content-Disposition': 'attachment; filename=examagent-informe.csv'})
