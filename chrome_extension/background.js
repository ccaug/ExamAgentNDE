const API = 'http://127.0.0.1:8765';

async function api(path, method = 'GET', body) {
  try {
    const r = await fetch(API + path, {
      method,
      headers: { 'Content-Type': 'application/json', 'X-ExamAgent': '1' },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    const text = await r.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { detail: text }; }
    return { ok: r.ok, status: r.status, data };
  } catch (e) {
    return { ok: false, status: 0, data: { detail: `No se pudo conectar con el servicio local (${e.message}). ¿Está abierto run.bat?` } };
  }
}

async function gesTab() {
  const { gesTab } = await chrome.storage.local.get('gesTab');
  if (!gesTab) return { error: 'Aún no has analizado ningún examen. Abre GES y pulsa «Analizar examen» en la extensión.' };
  let tab;
  try { tab = await chrome.tabs.get(gesTab.tabId); }
  catch { return { error: 'La pestaña de GES ya no existe. Vuelve a abrir el examen y pulsa «Analizar examen».' }; }
  try {
    const pong = await chrome.tabs.sendMessage(tab.id, { type: 'ping' });
    return { tab, pong };
  } catch {
    return { error: 'La pestaña de GES perdió el conector (¿la recargaste?). Pulsa «Analizar examen» de nuevo en esa pestaña.' };
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      switch (msg.type) {
        case 'api':
          return sendResponse(await api(msg.path, msg.method, msg.body));
        case 'remember_tab':
          await chrome.storage.local.set({ gesTab: { tabId: msg.tabId, url: msg.url, title: msg.title, at: Date.now() } });
          return sendResponse({ ok: true });
        case 'ges_status': {
          const r = await gesTab();
          if (r.error) return sendResponse({ ok: false, error: r.error });
          return sendResponse({ ok: true, title: r.tab.title, url: r.tab.url });
        }
        case 'launch_publish': {
          const r = await gesTab();
          if (r.error) return sendResponse({ ok: false, error: r.error });
          await chrome.tabs.update(r.tab.id, { active: true });
          await chrome.windows.update(r.tab.windowId, { focused: true });
          const res = await chrome.tabs.sendMessage(r.tab.id, { type: 'publish', runId: msg.runId });
          return sendResponse(res);
        }
        default:
          return sendResponse({ ok: false, error: 'Mensaje desconocido: ' + msg.type });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  })();
  return true;
});
