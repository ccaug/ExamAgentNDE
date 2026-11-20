// Puente entre el panel (http://127.0.0.1:8765) y la extensión. Solo permite estas órdenes.
const ALLOWED = new Set(['ges_status', 'launch_publish']);
window.addEventListener('message', async (ev) => {
  if (ev.source !== window || !ev.data || ev.data.__examagent !== true) return;
  const { id, cmd, payload } = ev.data;
  let reply;
  if (!ALLOWED.has(cmd)) reply = { ok: false, error: 'Orden no permitida' };
  else {
    try { reply = await chrome.runtime.sendMessage({ type: cmd, ...(payload || {}) }); }
    catch (e) { reply = { ok: false, error: e.message }; }
  }
  window.postMessage({ __examagent_reply: true, id, reply }, '*');
});
