// Prueba de integración: content.js real + backend real + Ollama simulado + DOM de GES simulado (jsdom).
// Uso: node tests/e2e_dom.test.js   (con el backend en :8765 y fake_ollama.py en :18434)
const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const API = 'http://127.0.0.1:8765';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const H = { 'Content-Type': 'application/json', 'X-ExamAgent': '1' };
const j = async (p, method = 'GET', body) => (await fetch(API + p, { method, headers: H, body: body && JSON.stringify(body) })).json();

function buildDom(opts = {}) {
  const dom = new JSDOM(`<!doctype html><body><h1>Examen</h1><div id="root"></div></body>`, { url: 'https://ges.example/exam/1', runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  // polyfills que Chrome sí tiene
  Object.defineProperty(w.HTMLElement.prototype, 'innerText', { get() {
    const out = []; const walk = (n) => { if (n.nodeType === 3) { const t = n.textContent.trim(); if (t) out.push(t); } else if (n.nodeType === 1 && !['SCRIPT', 'STYLE'].includes(n.tagName) && w.getComputedStyle(n).display !== 'none') n.childNodes.forEach(walk); };
    this.childNodes.forEach(walk); return out.join('\n'); }, set(v) { this.textContent = v; } });
  w.HTMLElement.prototype.scrollIntoView = function () {};
  w.Element.prototype.getBoundingClientRect = function () {
    for (let n = this; n && n.nodeType === 1; n = n.parentElement) if (w.getComputedStyle(n).display === 'none') return { width: 0, height: 0 };
    return { width: 10, height: 10, top: 0, left: 0 }; };
  const root = w.document.getElementById('root');
  const rows = [
    { id: 1, text: 'Capital de Francia?', opts: ['Paris', 'Roma'], checked: 0, score: [1, 1] },
    { id: 2, text: 'Capital de Italia?', opts: ['Madrid', 'Roma'], checked: 0, score: [2, 2] },   // GES puso 2/2 pero el alumno marcó Madrid -> la IA debe bajarla
    { id: 3, text: 'Sin respuesta aquí', opts: ['A', 'B'], checked: -1, score: [0, 1] },
    { id: 4, text: 'ABRIR explique la fotosíntesis', opts: null, score: [0, 4], open: 'Las plantas usan luz.' },
  ];
  rows.forEach((r) => {
    const div = w.document.createElement('div'); div.className = 'row mb-4 d-block';
    let html = `<div>${r.text}</div>`;
    if (r.opts) r.opts.forEach((o, i) => { html += `<label><input type="radio" name="response_to_item.${r.id}" value="${i}" disabled ${r.checked === i ? 'checked' : ''}> ${o}</label>`; });
    else html += `<div>Respuesta del estudiante</div><div>${r.open}</div><div>Respuesta de referencia</div><div>Las plantas convierten luz en energía química.</div>`;
    html += `<div class="sc">${r.score[0]} / ${r.score[1]} puntos</div><button class="edit">Editar</button>`;
    div.innerHTML = html; root.appendChild(div);
    const sc = div.querySelector('.sc');
    div.querySelector('button.edit').addEventListener('click', () => {
      const f = w.document.createElement('div'); f.className = 'editform';
      f.innerHTML = `<div><label for="p${r.id}">Puntos para la respuesta</label><input id="p${r.id}" type="number" step="1" min="0" max="${r.score[1]}" value="${r.score[0]}"></div>
        <div><label for="e${r.id}">Cambiar explicación</label><textarea id="e${r.id}"></textarea></div><button class="ok">Aceptar</button><button class="no">Cancelar</button>`;
      div.appendChild(f);
      f.querySelector('.no').addEventListener('click', () => f.remove());
      f.querySelector('.ok').addEventListener('click', () => { setTimeout(() => {
        if (opts.rejectSave) { f.insertAdjacentHTML('beforeend', '<div class="alert-danger">Error del servidor</div>'); return; }
        const v = f.querySelector('input').value; r.explanation = f.querySelector('textarea').value;
        sc.textContent = `${v} / ${r.score[1]} puntos`; f.remove(); }, 120); });
    });
  });
  const chromeMock = { runtime: { listeners: [], onMessage: { addListener(fn) { chromeMock.runtime.listeners.push(fn); } },
    sendMessage: async (msg) => { if (msg.type !== 'api') return null; const r = await fetch(API + msg.path, { method: msg.method || 'GET', headers: H, body: msg.body === undefined ? undefined : JSON.stringify(msg.body) }); return { ok: r.ok, status: r.status, data: await r.json() }; } } };
  w.chrome = chromeMock;
  w.eval(fs.readFileSync(path.join(__dirname, '../chrome_extension/content.js'), 'utf8'));
  const send = (msg) => new Promise((res) => chromeMock.runtime.listeners[0](msg, {}, res));
  return { w, rows, send };
}

const scores = (w) => [...w.document.querySelectorAll('.sc')].map((e) => e.textContent);

(async () => {
  // ---- escenario A: flujo completo feliz
  let { w, rows, send } = buildDom();
  const snap = await send({ type: 'capture' });
  assert.strictEqual(snap.questions.length, 4);
  assert.strictEqual(snap.questions[0].answer_status, 'answered');
  assert.strictEqual(snap.questions[2].answer_status, 'unanswered');
  assert.strictEqual(snap.questions[3].answer_status, 'unknown');           // pregunta abierta sin controles
  assert.ok(snap.questions[3].lines.some((l) => l.includes('Respuesta de referencia')));
  assert.strictEqual(snap.questions[3].has_edit_button, true);
  await j('/browser/snapshot?auto=true', 'POST', snap);
  for (let i = 0; i < 100; i++) { const s = await j('/state?light=1'); if (s.eval.state === 'done') break; await sleep(100); }
  let st = await j('/state');
  const f = Object.fromEntries(st.questions.map((q) => [q.number, q.final_score]));
  assert.deepStrictEqual(f, { 1: 1, 2: 0, 3: 0, 4: 2 }, JSON.stringify(f));  // incluye la Q2 ya calificada por GES -> corregida
  await j('/question/4/override', 'POST', { score: 2.5, explanation: 'Buen intento, añade la fase oscura.' });

  // simulacro: no escribe nada
  let prep = await j('/publish/prepare', 'POST', { mode: 'simulate' });
  assert.strictEqual(JSON.stringify(await send({ type: 'publish', runId: prep.run_id })), JSON.stringify({ ok: true, started: true }));
  for (let i = 0; i < 100; i++) { if ((await j('/state?light=1')).publish.state === 'done') break; await sleep(100); }
  let pub = (await j('/state?light=1')).publish;
  assert.strictEqual(pub.state, 'done'); assert.strictEqual(pub.simulated, 2, JSON.stringify(pub));
  assert.deepStrictEqual(scores(w), ['1 / 1 puntos', '2 / 2 puntos', '0 / 1 puntos', '0 / 4 puntos']);
  assert.strictEqual(w.document.querySelectorAll('.editform').length, 0);

  // publicación real
  prep = await j('/publish/prepare', 'POST', { mode: 'all' });
  assert.strictEqual(prep.total, 2);
  await send({ type: 'publish', runId: prep.run_id });
  for (let i = 0; i < 150; i++) { if ((await j('/state?light=1')).publish.state === 'done') break; await sleep(100); }
  pub = (await j('/state?light=1')).publish;
  assert.strictEqual(pub.state, 'done', JSON.stringify(pub)); assert.strictEqual(pub.written, 2);
  assert.strictEqual(pub.verify.ok, 2); assert.strictEqual(pub.verify.mismatch, 0);
  assert.deepStrictEqual(scores(w), ['1 / 1 puntos', '0 / 2 puntos', '0 / 1 puntos', '2.5 / 4 puntos']);
  assert.strictEqual(rows[3].explanation, 'Buen intento, añade la fase oscura.');
  assert.strictEqual(rows[1].explanation, 'Explicación simulada.');
  st = await j('/state'); assert.strictEqual(st.totals.changes, 0);       // GES ya coincide con la nota final
  console.log('A OK: flujo completo (captura→IA→edición→simulacro→publicación→verificación)');

  // ---- escenario B: GES rechaza el guardado -> se detiene con error claro
  ({ w, rows, send } = buildDom({ rejectSave: true }));
  await j('/browser/snapshot?auto=false', 'POST', await send({ type: 'capture' }));
  await j('/question/2/override', 'POST', { score: 1 });
  prep = await j('/publish/prepare', 'POST', { mode: 'all' });
  await send({ type: 'publish', runId: prep.run_id });
  for (let i = 0; i < 150; i++) { if ((await j('/state?light=1')).publish.state === 'error') break; await sleep(100); }
  pub = (await j('/state?light=1')).publish;
  assert.strictEqual(pub.state, 'error'); assert.match(pub.message, /no cerró el formulario/i);
  console.log('B OK: se detiene ante rechazo de GES:', pub.message);

  // ---- escenario C: la pestaña ya no es el examen analizado
  ({ w, send } = buildDom());
  const s2 = await send({ type: 'capture' }); s2.url = 'https://ges.example/otro-examen';
  await j('/browser/snapshot?auto=false', 'POST', s2);
  await j('/question/2/override', 'POST', { score: 1 });
  prep = await j('/publish/prepare', 'POST', { mode: 'all' });
  await send({ type: 'publish', runId: prep.run_id });
  for (let i = 0; i < 50; i++) { if ((await j('/state?light=1')).publish.state === 'error') break; await sleep(100); }
  pub = (await j('/state?light=1')).publish;
  assert.strictEqual(pub.state, 'error'); assert.match(pub.message, /ya no es el examen/i);
  assert.deepStrictEqual(scores(w), ['1 / 1 puntos', '2 / 2 puntos', '0 / 1 puntos', '0 / 4 puntos']);
  console.log('C OK: no escribe nada si la pestaña cambió');
  process.exit(0);
})().catch((e) => { console.error('FALLO', e); process.exit(1); });
