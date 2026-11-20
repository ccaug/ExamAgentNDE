# ExamAgent NDE — ICER 2027 Artifact

This repository accompanies the ICER 2027 submission *"Autonomous AI-Assisted
Self-Assessment and Corrective Feedback for Computing Education: A Platform-
and Model-Independent Browser-Driven Architecture"*.

**Deployment reported in the paper.** ExamAgent NDE 2.1 with `qwen3:1.7b`
(fast tier) and `qwen3:4b` (arbitration tier), on an Intel i7-1165G7 with
16 GB RAM and no discrete GPU. Fourteen student exams, 80 questions each
(1,120 questions total), zero instructor corrections, 1,120 writes verified,
10–15 minutes per exam.

**How to reproduce.** Install Python 3.10+, Ollama, and Chrome. Run `run.bat`,
load the extension from `chrome_extension/`, open an exam in the platform,
and click *Analizar examen*. See `README.md` below for the full workflow.

**Data.** The anonymised CSV of the deployment is in
`data/examagent-informe.csv`. The survey data is in `survey/responses.csv`.

**Design rationale.** See `EFFICIENCY.md` for why the cascade works.

---

# ExamAgent NDE 2.1

Flujo: **Analizar examen → Qwen corrige todo → editas lo que quieras → LANZAR NOTA FINAL.**

## Instalación (una vez)
1. Extrae el ZIP en una carpeta nueva y ejecuta `run.bat` (instala dependencias y abre el panel).
2. Instala Ollama. **Los modelos se eligen solos** según tu hardware (GPU/VRAM/RAM): un modelo pequeño rápido y otro mayor solo para arbitrar. Si faltan, el panel ofrece descargarlos. Opcional: `tune_ollama.bat` (flash attention, KV cache q8_0). Detalles: `EFFICIENCY.md`.
3. Chrome → `chrome://extensions` → activa *Modo de desarrollador* → elimina la extensión anterior → *Cargar descomprimida* → carpeta `chrome_extension`.

## Uso
1. Abre el examen en GES y pulsa la extensión → **Analizar examen**. Se abre el panel.
2. Qwen evalúa las 80 preguntas **en cascada** (1 token por decisión; el modelo fuerte solo arbitra desacuerdos/dudas), **incluidas las que GES ya calificó**. Verás nota GES, nota IA y nota final.
3. Edita en el panel la nota o explicación de cualquier pregunta (se guarda al instante). Filtro «Dudosas» para las que el modelo no pudo juzgar con seguridad.
4. **LANZAR NOTA FINAL**: la extensión recorre GES, pulsa *Editar* en cada pregunta que cambia, escribe puntos (y explicación), pulsa *Aceptar*, comprueba que GES muestra la nota y sigue. Se detiene ante cualquier anomalía.
   - Recomendado la primera vez: **Simulacro** (abre y cierra el formulario sin escribir) y **Probar con 1 pregunta**.
   - No cierres ni recargues la pestaña de GES mientras sube. Hay un botón *Detener* en GES y en el panel.

## Seguridad integrada
- Solo se suben las notas que difieren de GES (o explicaciones editadas por ti), salvo que marques «Reescribir todas».
- Se verifica la dirección de la pestaña, el rango de cada nota y el valor mostrado tras guardar; al terminar se relee todo el examen y se comparan las notas.
- Registro de auditoría: `data/publish_log.jsonl`. Informe CSV desde el panel.
- Servicio solo en 127.0.0.1; solo el panel y la extensión pueden ordenar escrituras.

## Límites
- La calidad depende de los modelos instalados; los pequeños son más flojos en respuestas abiertas (por eso se arbitran y se marcan «dudosas»). Usa la clave/instrucciones opcionales y revisa las «dudosas».
- El editor de GES se localiza por sus etiquetas («Editar», «Puntos para la respuesta», «Cambiar explicación», «Aceptar»). Si difieren, el simulacro lo detecta antes de escribir nada.
- Un examen (un estudiante) por captura.

## Pruebas (desarrollo)
`python -m pytest tests -q` y `node tests/e2e_dom.test.js` (requiere `npm i jsdom`, backend en :8765 y `python tests/fake_ollama.py`).
