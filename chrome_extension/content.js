// ExamAgent NDE — conector de la pestaña GES: captura el examen y publica las notas.
(() => {
  const VERSION = '2.0.0';
  if (window.__examAgentNDE && window.__examAgentNDE.version === VERSION) return;
  window.__examAgentNDE = { version: VERSION, running: false };

  // ------------------------------------------------------------------ utilidades
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const normalize = (v) => String(v || '').replace(/\s+/g, ' ').trim();
  const fold = (v) => normalize(v).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
  const SCORE_LINE = /^(\d+(?:[.,]\d+)?)\s*\/\s*(\d+(?:[.,]\d+)?)\s*puntos$/i;
  const SCORE_ANY = /(\d+(?:[.,]\d+)?)\s*\/\s*(\d+(?:[.,]\d+)?)\s*puntos/i;
  const ROW_SELECTOR = 'div.row.mb-4.d-block';

  const visible = (el) => {
    if (!el || !el.isConnected) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };

  async function waitFor(fn, timeout = 6000, interval = 120) {
    const end = Date.now() + timeout;
    for (;;) {
      const v = fn();
      if (v) return v;
      if (Date.now() > end) return null;
      await sleep(interval);
    }
  }

  const rowLines = (row) =>
    (row.innerText || row.textContent || '').split('\n').map(normalize).filter(Boolean);

  function readRowScore(row) {
    const lines = rowLines(row);
    const line = lines.find((l) => SCORE_LINE.test(l));
    const m = line ? line.match(SCORE_LINE) : normalize(row.innerText || '').match(SCORE_ANY);
    if (!m) return null;
    return { earned: Number(m[1].replace(',', '.')), maximum: Number(m[2].replace(',', '.')) };
  }

  // ------------------------------------------------------------------ captura (solo lectura)
  function capture() {
    const rows = [...document.querySelectorAll(ROW_SELECTOR)];
    const questions = rows.map((row, index) => {
      const rowControls = [...row.querySelectorAll('input,select,textarea')];
      const answerControls = rowControls.filter((el) => {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || '').toLowerCase();
        if (type === 'hidden') return false;
        return tag === 'select' || tag === 'textarea' ||
          (tag === 'input' && ['radio', 'checkbox', 'text', 'number', 'email', 'search', 'url', 'tel'].includes(type));
      });
      const labelText = (el) => {
        const labels = el.labels ? [...el.labels].map((l) => normalize(l.innerText || l.textContent)) : [];
        const wrapping = el.closest('label');
        if (wrapping) labels.push(normalize(wrapping.innerText || wrapping.textContent));
        return [...new Set(labels.filter(Boolean))].join(' | ');
      };
      const options = [];
      answerControls.forEach((el) => {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || tag).toLowerCase();
        if (type === 'radio' || type === 'checkbox') {
          options.push({ control_type: type, value: el.value || '', text: labelText(el), checked: !!el.checked, disabled: !!el.disabled, id: el.id || '' });
        } else if (tag === 'select') {
          [...el.options].forEach((o) => options.push({ control_type: 'select-option', value: o.value, text: normalize(o.textContent), checked: !!o.selected, disabled: !!o.disabled, id: o.id || '' }));
        }
      });
      const lines = rowLines(row);
      const optionTexts = new Set(options.map((o) => o.text).filter(Boolean));
      const scoreLine = lines.find((l) => SCORE_LINE.test(l)) || null;
      const scoreMatch = scoreLine ? scoreLine.match(SCORE_LINE) : null;
      const questionText = lines
        .filter((l) => l.toLocaleLowerCase() !== 'editar')
        .filter((l) => !optionTexts.has(l))
        .filter((l) => !SCORE_LINE.test(l))
        .join(' ').trim();
      const selectedAnswers = [];
      answerControls.forEach((el) => {
        const tag = el.tagName.toLowerCase();
        const type = (el.type || tag).toLowerCase();
        if ((type === 'radio' || type === 'checkbox') && el.checked) selectedAnswers.push({ type, value: el.value || '', text: labelText(el) });
        else if (tag === 'select') [...el.selectedOptions].filter((o) => o.value !== '').forEach((o) => selectedAnswers.push({ type: 'select', value: o.value, text: normalize(o.textContent) }));
        else if ((tag === 'textarea' || tag === 'input') && !['radio', 'checkbox'].includes(type) && String(el.value || '').trim()) selectedAnswers.push({ type, value: el.value, text: labelText(el) });
      });
      const questionType = answerControls.some((el) => (el.type || '').toLowerCase() === 'radio') ? 'radio' :
        answerControls.some((el) => (el.type || '').toLowerCase() === 'checkbox') ? 'checkbox' :
        answerControls.some((el) => el.tagName === 'SELECT') ? 'select' :
        answerControls.some((el) => el.tagName === 'TEXTAREA') ? 'textarea' :
        answerControls.length ? 'text' : 'unknown';
      const answerStatus = !answerControls.length ? 'unknown' : selectedAnswers.length ? 'answered' : 'unanswered';
      const named = rowControls.find((el) => (el.name || '').startsWith('response_to_item.'));
      return {
        question_number: index + 1,
        question_id: named ? named.name : null,
        question_text: questionText,
        question_type: questionType,
        options,
        selected_answers: selectedAnswers,
        answer_status: answerStatus,
        score: scoreMatch ? { earned: Number(scoreMatch[1].replace(',', '.')), maximum: Number(scoreMatch[2].replace(',', '.')), raw: scoreLine } : null,
        lines: lines.slice(0, 80).map((l) => l.slice(0, 800)),
        has_edit_button: !!findEditButton(row),
        raw_text: normalize(row.innerText || row.textContent || '').slice(0, 4000)
      };
    });
    return {
      url: location.href,
      title: document.title,
      captured_at: new Date().toISOString(),
      capture_version: VERSION,
      text: (document.body?.innerText || '').slice(0, 20000),
      headings: [...document.querySelectorAll('h1,h2,h3,h4')].filter(visible).map((el) => normalize(el.innerText).slice(0, 300)).filter(Boolean).slice(0, 100),
      questions,
      capture_summary: {
        total_questions: questions.length,
        answered: questions.filter((q) => q.answer_status === 'answered').length,
        unanswered: questions.filter((q) => q.answer_status === 'unanswered').length,
        unknown_answer_status: questions.filter((q) => q.answer_status === 'unknown').length,
        scores_available: questions.filter((q) => q.score).length
      },
      viewport: { width: innerWidth, height: innerHeight }
    };
  }

  // ------------------------------------------------------------------ localizar elementos de GES
  const btnText = (el) => normalize(el.innerText || el.textContent || el.value || el.title || el.getAttribute('aria-label') || '');
  const BUTTONS = 'button,a,[role=button],input[type=button],input[type=submit]';

  function findEditButton(row) {
    return [...row.querySelectorAll(BUTTONS)].filter(visible).find((el) => fold(btnText(el)) === 'editar') || null;
  }

  function findRow(item) {
    const rows = [...document.querySelectorAll(ROW_SELECTOR)];
    const probe = fold(item.text_probe || '');
    const matchesText = (r) => !probe || fold(r.innerText || r.textContent).includes(probe);
    if (item.question_id) {
      const r = rows.find((row) => [...row.querySelectorAll('[name]')].some((e) => e.name === item.question_id));
      if (r) return r;
    }
    const byIndex = rows[item.question_number - 1];
    if (byIndex && matchesText(byIndex)) return byIndex;
    return rows.find(matchesText) || null;
  }

  const FIELD_SELECTOR = 'input,textarea,select,[contenteditable="true"],[contenteditable=""],iframe';
  const isTextual = (el) => {
    if (el.tagName === 'IFRAME') return true;
    if (el.isContentEditable && el.tagName !== 'INPUT' && el.tagName !== 'TEXTAREA') return true;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName !== 'INPUT') return false;
    return !['hidden', 'radio', 'checkbox', 'button', 'submit', 'file', 'reset', 'image'].includes((el.type || '').toLowerCase());
  };
  const visibleFields = () => new Set([...document.querySelectorAll(FIELD_SELECTOR)].filter(isTextual).filter(visible));

  function fieldHints(el) {
    const parts = [];
    if (el.labels) parts.push(...[...el.labels].map((l) => l.textContent));
    parts.push(el.getAttribute('aria-label') || '', el.getAttribute('placeholder') || '', el.name || '', el.id || '', el.title || '');
    (el.getAttribute('aria-labelledby') || '').split(/\s+/).forEach((id) => parts.push(document.getElementById(id)?.textContent || ''));
    let node = el;
    for (let i = 0; i < 3 && node; i++) {
      const prev = node.previousElementSibling;
      if (prev && !prev.querySelector('input,textarea,select')) { parts.push(prev.textContent); break; }
      node = node.parentElement;
    }
    const wrap = el.closest('label, .form-group, .mb-3');
    if (wrap) parts.push((wrap.textContent || '').slice(0, 200));
    return fold(parts.join(' | '));
  }

  const POINTS_LABEL = /puntos?\s*(para|de)?\s*(la)?\s*respuesta|puntos|puntuacion|score/;
  const EXPLANATION_LABEL = /explicaci/;

  function locateEditor(row, before) {
    const after = [...visibleFields()];
    let fresh = after.filter((el) => !before.has(el));
    if (!fresh.length) fresh = after.filter((el) => row.contains(el) && (POINTS_LABEL.test(fieldHints(el)) || EXPLANATION_LABEL.test(fieldHints(el))));
    if (!fresh.length) return null;
    const points = fresh.find((el) => el.tagName === 'INPUT' && POINTS_LABEL.test(fieldHints(el))) ||
      fresh.find((el) => el.tagName === 'INPUT' && (el.type || '').toLowerCase() === 'number') ||
      (fresh.filter((el) => el.tagName === 'INPUT').length === 1 ? fresh.find((el) => el.tagName === 'INPUT') : null);
    if (!points) return null;
    const rest = fresh.filter((el) => el !== points);
    const explanation = rest.find((el) => EXPLANATION_LABEL.test(fieldHints(el))) ||
      rest.find((el) => el.tagName === 'TEXTAREA' || el.tagName === 'IFRAME' || (el.isContentEditable && el.tagName !== 'INPUT')) || null;
    const isAccept = (el) => ['aceptar', 'guardar'].includes(fold(btnText(el)));
    let container = points.parentElement;
    let accept = null;
    for (let i = 0; i < 12 && container && container !== document.documentElement; i++) {
      const found = [...container.querySelectorAll(BUTTONS)].filter(visible).filter(isAccept);
      if (found.length) {
        accept = found.find((b) => points.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) || found[0];
        break;
      }
      container = container.parentElement;
    }
    return accept ? { points, explanation, accept, container } : { points, explanation, accept: null, container: null };
  }

  function setNativeValue(el, value) {
    el.focus();
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    el.dispatchEvent(new Event('blur', { bubbles: true }));
  }

  function readExplanation(el) {
    if (!el) return '';
    if (el.tagName === 'IFRAME') return normalize(el.contentDocument?.body?.innerText || '');
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return el.value || '';
    return el.innerText || '';
  }

  function writeExplanation(el, text) {
    if (el.tagName === 'IFRAME') {
      const body = el.contentDocument?.body;
      if (!body) throw new Fatal('No puedo escribir en el editor de explicación (iframe inaccesible).');
      body.innerText = text;
      body.dispatchEvent(new Event('input', { bubbles: true }));
    } else if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      setNativeValue(el, text);
    } else {
      el.focus();
      el.innerText = text;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  const fmtNumber = (value, input) => {
    const s = String(Math.round(value * 100) / 100);
    return (input.type || '').toLowerCase() === 'text' && String(input.value || '').includes(',') ? s.replace('.', ',') : s;
  };

  async function closeEditor(editor) {
    const cancel = editor.container && [...editor.container.querySelectorAll(BUTTONS)].filter(visible)
      .find((b) => ['cancelar', 'cerrar', 'close', 'x', '×'].includes(fold(btnText(b))));
    if (cancel) cancel.click();
    else document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true }));
    const closed = await waitFor(() => !visible(editor.points), 2500);
    if (!closed) throw new Fatal('No pude cerrar el formulario de edición tras el simulacro.');
  }

  function visibleErrors(scope) {
    const root = scope || document;
    return [...root.querySelectorAll('.alert-danger,.invalid-feedback,.text-danger,[role=alert],.toast-error')]
      .filter(visible).map((e) => normalize(e.textContent)).filter(Boolean).slice(0, 3).join(' | ');
  }

  class Fatal extends Error {}
  class Recoverable extends Error {}

  // ------------------------------------------------------------------ interfaz mínima en la página
  function createOverlay(onStop) {
    const box = document.createElement('div');
    box.id = 'examagent-overlay';
    box.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:2147483647;background:#0b1020;color:#fff;font:13px system-ui,sans-serif;padding:12px 14px;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.4);width:290px';
    box.innerHTML = '<div style="font-weight:700;margin-bottom:6px">ExamAgent NDE</div><div id="ea-msg" style="min-height:34px;line-height:1.35"></div><div style="background:#263750;border-radius:6px;height:8px;margin:8px 0"><div id="ea-bar" style="background:#34d399;height:8px;border-radius:6px;width:0"></div></div><button id="ea-stop" style="background:#dc2626;color:#fff;border:0;border-radius:7px;padding:7px 12px;font-weight:700;cursor:pointer;width:100%">Detener</button>';
    document.body.appendChild(box);
    box.querySelector('#ea-stop').addEventListener('click', () => { onStop(); box.querySelector('#ea-stop').textContent = 'Deteniendo…'; });
    return {
      set(msg, pct) { box.querySelector('#ea-msg').textContent = msg; if (pct != null) box.querySelector('#ea-bar').style.width = pct + '%'; },
      end(msg) { box.querySelector('#ea-msg').textContent = msg; box.querySelector('#ea-stop').style.display = 'none'; setTimeout(() => box.remove(), 12000); }
    };
  }

  const api = (path, method, body) => chrome.runtime.sendMessage({ type: 'api', path, method, body });

  // ------------------------------------------------------------------ publicación
  async function processItem(item, plan, mode) {
    const row = findRow(item);
    if (!row) throw new Fatal(`No encuentro la pregunta ${item.question_number} en la página (¿cambió el examen?).`);
    row.scrollIntoView({ block: 'center' });
    await sleep(250);
    const current = readRowScore(row);
    const maximum = item.maximum ?? current?.maximum ?? null;
    const target = item.target_score;
    if (maximum == null) throw new Recoverable('No conozco la puntuación máxima de esta pregunta; no la modifico.');
    if (target < 0 || target > maximum + 1e-9) throw new Fatal(`Nota ${target} fuera de rango (0–${maximum}).`);
    if (!item.force && !item.explanation_edited && current && Math.abs(current.earned - target) < 0.005) {
      return { result: 'skipped', detail: 'GES ya tiene esa nota.' };
    }
    const editBtn = findEditButton(row);
    if (!editBtn) throw new Recoverable('No encontré el botón «Editar» en esta pregunta.');

    const before = visibleFields();
    editBtn.click();
    let editor = null;
    await waitFor(() => { editor = locateEditor(row, before); return editor && editor.accept; }, 7000);
    if (!editor || !editor.points) throw new Fatal('No apareció el formulario de edición (campo «Puntos para la respuesta»).');
    if (!editor.accept) throw new Fatal('No encontré el botón «Aceptar» del formulario.');

    const { points, explanation, accept } = editor;
    const notes = [];
    if (mode === 'simulate') {
      const found = `puntos=${points.name || points.id || points.type}, explicación=${explanation ? (explanation.tagName.toLowerCase()) : 'no encontrada'}, aceptar=OK`;
      await closeEditor(editor);
      return { result: 'simulated', detail: `Formulario localizado y cerrado sin cambios (${found}).` };
    }

    if (points.max !== '' && points.max != null && Number.isFinite(Number(points.max)) && target > Number(points.max) + 1e-9) {
      throw new Fatal(`El campo de puntos de GES admite como máximo ${points.max}, pero la nota es ${target}.`);
    }
    if (points.step && points.step !== 'any' && points.type === 'number') {
      const step = Number(points.step);
      if (step > 0 && Math.abs(target / step - Math.round(target / step)) > 1e-6) { points.step = 'any'; notes.push('el campo solo admitía pasos enteros'); }
    }
    setNativeValue(points, fmtNumber(target, points));

    if (plan.write_explanations && item.explanation) {
      if (explanation) {
        const existing = readExplanation(explanation).trim();
        if (!existing || plan.overwrite_explanations || item.explanation_edited) writeExplanation(explanation, item.explanation);
        else notes.push('explicación existente conservada');
      } else {
        notes.push('no encontré el campo de explicación');
      }
    }
    await sleep(200);
    if (typeof points.checkValidity === 'function' && !points.checkValidity()) {
      throw new Fatal(`GES rechaza el valor ${target}: ${points.validationMessage || 'valor no válido'}.`);
    }
    accept.click();

    const closed = await waitFor(() => !visible(points), 9000);
    if (!closed) throw new Fatal(`GES no cerró el formulario tras Aceptar. ${visibleErrors(editor.container) || visibleErrors()}`.trim());
    await sleep(500);

    let shown = null;
    const ok = await waitFor(() => {
      const r = findRow(item);
      shown = r ? readRowScore(r) : null;
      return shown && Math.abs(shown.earned - target) < 0.005;
    }, 7000, 250);
    if (ok) return { result: 'written', detail: `${current ? current.earned : '—'} → ${shown.earned}${notes.length ? ' (' + notes.join('; ') + ')' : ''}` };
    if (!shown) return { result: 'unverified', detail: 'Guardado, pero no pude leer la nota en pantalla para confirmarla.' };
    throw new Fatal(`Verificación fallida en la pregunta ${item.question_number}: esperaba ${target} y GES muestra ${shown.earned}.`);
  }

  async function runPublish(runId) {
    const state = window.__examAgentNDE;
    state.running = true;
    let stopRequested = false;
    const overlay = createOverlay(() => { stopRequested = true; api('/publish/stop', 'POST', {}); });
    const send = async (type, extra = {}) => {
      const res = await api('/publish/event', 'POST', { run_id: runId, type, ...extra });
      if (res?.data?.stop) stopRequested = true;
      return res;
    };
    try {
      const planRes = await api(`/publish/plan?run_id=${encodeURIComponent(runId)}`, 'GET');
      if (!planRes?.ok) throw new Fatal(planRes?.data?.detail || 'No pude obtener el plan de publicación.');
      const plan = planRes.data;
      const here = location.href.split('#')[0];
      if (here !== String(plan.url).split('#')[0]) {
        throw new Fatal('Esta pestaña ya no es el examen que se analizó (la dirección cambió). Vuelve a analizar el examen.');
      }
      await send('start');
      const total = plan.items.length;
      let consecutiveRecoverable = 0;
      let index = 0;
      for (const item of plan.items) {
        if (stopRequested) break;
        overlay.set(`Pregunta ${item.question_number} (${index + 1}/${total})…`, (index / Math.max(1, total)) * 100);
        try {
          const out = await processItem(item, plan, plan.mode);
          consecutiveRecoverable = 0;
          await send('item', { question_number: item.question_number, result: out.result, detail: out.detail });
        } catch (e) {
          if (e instanceof Recoverable) {
            consecutiveRecoverable++;
            await send('item', { question_number: item.question_number, result: 'failed', detail: e.message });
            if (consecutiveRecoverable >= 3) throw new Fatal('Tres preguntas seguidas no se pudieron editar. Me detengo para que lo revises.');
          } else throw e;
        }
        index++;
        await sleep(350);
      }
      overlay.set('Verificando resultado en GES…', 100);
      const snapshot = plan.mode === 'simulate' ? null : capture();
      await send('finish', { stopped: stopRequested, snapshot });
      overlay.end(stopRequested ? 'Detenido.' : plan.mode === 'simulate' ? 'Simulacro terminado: no se modificó ninguna nota.' : 'Listo. Notas subidas y verificadas.');
    } catch (e) {
      const message = e && e.message ? e.message : String(e);
      await send('error', { message });
      overlay.end('Detenido: ' + message);
    } finally {
      state.running = false;
    }
  }

  // ------------------------------------------------------------------ mensajes de la extensión
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg.type === 'ping') { sendResponse({ ok: true, version: VERSION, running: window.__examAgentNDE.running }); return false; }
    if (msg.type === 'capture') { sendResponse(capture()); return false; }
    if (msg.type === 'publish') {
      if (window.__examAgentNDE.running) { sendResponse({ ok: false, error: 'Ya hay una publicación en curso en esta pestaña.' }); return false; }
      runPublish(msg.runId);
      sendResponse({ ok: true, started: true });
      return false;
    }
    return false;
  });

  // Expuesto solo para pruebas automáticas.
  window.__examAgentNDE.internals = { capture, findRow, readRowScore, locateEditor, processItem };
})();
