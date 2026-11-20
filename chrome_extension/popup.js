const API = 'http://127.0.0.1:8765';
const statusEl = document.getElementById('status');
const analyzeBtn = document.getElementById('analyze');

async function openPanel() {
  const tabs = await chrome.tabs.query({ url: API + '/*' });
  if (tabs.length) {
    await chrome.tabs.update(tabs[0].id, { active: true });
    await chrome.windows.update(tabs[0].windowId, { focused: true });
  } else {
    await chrome.tabs.create({ url: API + '/' });
  }
}

document.getElementById('panel').addEventListener('click', openPanel);

analyzeBtn.addEventListener('click', async () => {
  analyzeBtn.disabled = true;
  statusEl.textContent = 'Leyendo el examen de GES…';
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https?:/.test(tab.url || '')) throw new Error('La pestaña activa no es una página web.');
    if (tab.url.startsWith(API)) throw new Error('Esta es la pestaña del panel. Ve a la pestaña de GES con el examen.');

    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'] });
    const snapshot = await chrome.tabs.sendMessage(tab.id, { type: 'capture' });
    if (!snapshot || !snapshot.questions || !snapshot.questions.length) {
      throw new Error('No encontré preguntas en esta página. ¿Es la vista del examen?');
    }

    const res = await fetch(API + '/browser/snapshot?auto=true', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-ExamAgent': '1' },
      body: JSON.stringify(snapshot)
    });
    if (!res.ok) throw new Error(`El servicio local respondió ${res.status}: ${await res.text()}`);
    const data = await res.json();
    await chrome.runtime.sendMessage({ type: 'remember_tab', tabId: tab.id, url: tab.url, title: tab.title });
    statusEl.textContent = `${data.questions} preguntas capturadas. ${data.evaluation_started ? 'Qwen está corrigiendo…' : 'Resultados ya disponibles.'}`;
    await openPanel();
  } catch (e) {
    const m = String(e.message || e);
    statusEl.textContent = 'Error: ' + (m.includes('Failed to fetch') ? 'no se pudo conectar con el servicio local. ¿Está abierto run.bat?' : m);
  } finally {
    analyzeBtn.disabled = false;
  }
});
