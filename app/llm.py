"""Cliente mínimo de Ollama con medición real de tokens/tiempo y degradación de capacidades."""
from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests

from app.config import settings

THINK_RE = re.compile(r'<think>.*?</think>', re.S)


class OllamaError(RuntimeError):
    pass


@dataclass
class Reply:
    text: str
    tokens_out: int = 0
    tokens_in: int = 0
    wall_ms: float = 0.0
    decode_ms: float = 0.0
    # Por cada token generado: lista de (token_normalizado, probabilidad) de las alternativas más probables.
    top: list[list[tuple[str, float]]] | None = None


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, 'lock', threading.Lock()):
            self.by_label: dict[str, dict[str, float]] = {}

    def record(self, label: str, model: str, r: Reply) -> None:
        with self.lock:
            s = self.by_label.setdefault(label, {'calls': 0, 'tokens_in': 0, 'tokens_out': 0, 'wall_ms': 0.0,
                                                 'decode_ms': 0.0, 'model': model})
            s['calls'] += 1
            s['tokens_in'] += r.tokens_in
            s['tokens_out'] += r.tokens_out
            s['wall_ms'] += r.wall_ms
            s['decode_ms'] += r.decode_ms
            s['model'] = model

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            out = {}
            for k, s in self.by_label.items():
                out[k] = {**s, 'tokens_per_s': round(1000 * s['tokens_out'] / s['decode_ms'], 1) if s['decode_ms'] else None,
                          'avg_ms_per_call': round(s['wall_ms'] / s['calls']) if s['calls'] else None}
            return out


stats = Stats()
_caps = {'logprobs': True, 'think': True}
_caps_lock = threading.Lock()


def reset_caps() -> None:
    with _caps_lock:
        _caps.update(logprobs=True, think=True)


def _base() -> str:
    return settings.ollama_base_url.rstrip('/')


def _norm_token(tok: str) -> str:
    return re.sub(r'[^A-Za-z0-9]', '', tok or '').upper()


def _parse_logprobs(data: dict[str, Any]) -> list[list[tuple[str, float]]] | None:
    raw = data.get('logprobs') or (data.get('message') or {}).get('logprobs')
    if not raw or not isinstance(raw, list):
        return None
    out: list[list[tuple[str, float]]] = []
    for item in raw:
        alts: dict[str, float] = {}
        entries = list(item.get('top_logprobs') or [])
        if item.get('token') is not None and item.get('logprob') is not None:
            entries.append({'token': item['token'], 'logprob': item['logprob']})
        for e in entries:
            t = _norm_token(e.get('token', ''))
            if t:
                alts[t] = max(alts.get(t, 0.0), math.exp(float(e.get('logprob', -50))))
        out.append(sorted(alts.items(), key=lambda kv: -kv[1]))
    return out


def chat(model: str, messages: list[dict[str, str]], *, label: str, think: bool = False, num_ctx: int = 2048,
         num_predict: int = 8, temperature: float = 0.0, want_logprobs: bool = False) -> Reply:
    """Una llamada a /api/chat. Si la versión de Ollama no soporta think/logprobs, se desactivan y se recuerda."""
    for _ in range(4):
        body: dict[str, Any] = {
            'model': model, 'messages': messages, 'stream': False, 'keep_alive': settings.keep_alive,
            'options': {'temperature': temperature, 'num_ctx': num_ctx, 'num_predict': num_predict, 'seed': 7},
        }
        with _caps_lock:
            use_think, use_lp = _caps['think'], _caps['logprobs'] and want_logprobs
        if use_think:
            body['think'] = think
        if use_lp:
            body['logprobs'] = True
            body['top_logprobs'] = 8
        t0 = time.perf_counter()
        try:
            resp = requests.post(f'{_base()}/api/chat', json=body, timeout=settings.ollama_timeout)
        except requests.RequestException as exc:
            raise OllamaError(f'No se pudo contactar con Ollama: {exc}') from exc
        if resp.status_code == 400:
            with _caps_lock:
                if use_lp:
                    _caps['logprobs'] = False
                    continue
                if use_think:
                    _caps['think'] = False
                    continue
            raise OllamaError(f'Ollama rechazó la petición: {resp.text[:200]}')
        if resp.status_code == 404:
            raise OllamaError(f'El modelo «{model}» no está instalado. Ejecuta: ollama pull {model}')
        if not resp.ok:
            raise OllamaError(f'Ollama respondió {resp.status_code}: {resp.text[:200]}')
        data = resp.json()
        wall = (time.perf_counter() - t0) * 1000
        text = THINK_RE.sub('', (data.get('message') or {}).get('content', '') or '').strip()
        reply = Reply(text=text, tokens_out=int(data.get('eval_count') or 0), tokens_in=int(data.get('prompt_eval_count') or 0),
                      wall_ms=wall, decode_ms=float(data.get('eval_duration') or 0) / 1e6,
                      top=_parse_logprobs(data) if use_lp else None)
        stats.record(label, model, reply)
        return reply
    raise OllamaError('Ollama no aceptó la petición tras degradar capacidades.')


def list_models() -> list[str]:
    r = requests.get(f'{_base()}/api/tags', timeout=4)
    r.raise_for_status()
    return [m.get('name') for m in r.json().get('models', []) if m.get('name')]


def running_models() -> list[dict[str, Any]]:
    try:
        r = requests.get(f'{_base()}/api/ps', timeout=3)
        r.raise_for_status()
        return r.json().get('models', [])
    except Exception:
        return []


def warm(model: str) -> None:
    """Carga el modelo en memoria sin generar nada (oculta el tiempo de arranque)."""
    try:
        requests.post(f'{_base()}/api/generate', json={'model': model, 'keep_alive': settings.keep_alive}, timeout=300)
    except Exception:
        pass


def benchmark(model: str, tokens: int = 24) -> dict[str, Any]:
    t0 = time.perf_counter()
    r = requests.post(f'{_base()}/api/generate', json={
        'model': model, 'prompt': 'Cuenta en voz alta del 1 al 40, separando con comas.', 'stream': False,
        'keep_alive': settings.keep_alive, 'options': {'num_predict': tokens, 'temperature': 0}}, timeout=300)
    r.raise_for_status()
    d = r.json()
    dec = float(d.get('eval_duration') or 0) / 1e9
    return {'model': model, 'tokens': d.get('eval_count'), 'tokens_per_s': round((d.get('eval_count') or 0) / dec, 1) if dec else None,
            'wall_s': round(time.perf_counter() - t0, 2)}


def pull(model: str, on_progress: Callable[[str, float | None], None]) -> None:
    with requests.post(f'{_base()}/api/pull', json={'model': model, 'stream': True}, stream=True, timeout=3600) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            if d.get('error'):
                raise OllamaError(d['error'])
            pct = 100 * d['completed'] / d['total'] if d.get('total') and d.get('completed') is not None else None
            on_progress(d.get('status', ''), pct)
