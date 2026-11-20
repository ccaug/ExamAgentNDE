# Eficiencia de inferencia — ExamAgent NDE 2.1

## Por qué el coste está donde está
En un LLM local el tiempo lo dominan los **tokens generados** (decodificar es secuencial; en CPU, leer el prompt es mucho más rápido que generar). La versión 2.0 hacía que un modelo con razonamiento generara JSON + texto para cada una de las 80 preguntas. La 2.1 minimiza los tokens generados sin cambiar quién juzga: siempre es un LLM.

## Técnicas implementadas (todas en `app/evaluator.py`, probadas con un Ollama simulado)
| # | Técnica | Qué evita |
|---|---|---|
| 1 | **Cabezales de decisión de 1 token**: el modelo rápido responde una letra (selección) o un dígito 0-4 (abierta), sin razonar (`think:false`, `/no_think`, `num_predict` 4-8). | Cientos de tokens de razonamiento/JSON por pregunta |
| 2 | **Confianza por log-probabilidades** del propio token (normalizadas entre los símbolos válidos), no autoevaluación textual. Si tu Ollama no devuelve logprobs, se degrada solo. | Una segunda llamada para "¿estás seguro?" |
| 3 | **Cascada con acuerdo de jueces independientes**: GES (que ya muestra una nota) actúa como segundo experto gratis. Si el modelo rápido —que resuelve sin ver la nota— coincide con GES, no se gasta más. El modelo no copia la nota. | Arbitrar lo que ya está de acuerdo (la gran mayoría) |
| 4 | **Arbitraje asimétrico**: el modelo fuerte, con razonamiento, solo se usa ante desacuerdo con GES, duda (confianza baja) o rechazos sin contraste. Orden de prioridad: desacuerdos primero. | Pensar en todo |
| 5 | **Caché de decisiones** (SQLite, clave = pregunta + respuesta, independiente del orden de opciones) y **inferencia de clave**: si ya se conoce la opción correcta de una selección única, las demás opciones son incorrectas sin llamar al modelo. | Repetir juicios entre alumnos y re-capturas |
| 6 | **Explicaciones perezosas**: solo se generan para lo que no es plenamente correcto (lo único que se escribe en GES), con un tope de ~110 tokens. | Explicar respuestas correctas |
| 7 | **Presupuesto de tiempo**: `time_budget_s`; al agotarse, el arbitraje se detiene y esas preguntas quedan marcadas "sin verificar · revisar". | Esperas impredecibles |
| 8 | **Selección automática por hardware** (`app/hardware.py`): detecta GPU/VRAM (nvidia-smi, Apple Silicon) y RAM; elige modelo rápido y fuerte entre los instalados; en GPU usa 2 hilos de inferencia; ofrece descargar lo recomendado. `/hardware?bench=true` mide tok/s reales. | Configurar a mano; usar un modelo grande en un portátil |
| 9 | **Ctx pequeño y prompts sin redundancia** (2048 en el nivel rápido), prefijo constante para que Ollama reutilice su KV-cache, modelos precargados al arrancar (`keep_alive`). | Prefill y arranque en frío |
| 10 | **Orden por fases** (todo lo rápido → arbitraje → explicaciones) para evitar cambiar de modelo continuamente. | Recargas de modelos |

Seguridad añadida: el texto del estudiante va delimitado como dato (`<respuesta_estudiante>`), se eliminan etiquetas que intenten cerrarlo y los prompts ordenan ignorar instrucciones incrustadas. Mitiga, no garantiza; sigue siendo recomendable revisar las "dudosas".

## Poda de neuronas / pruning: qué se hizo y qué no
Podar un modelo de verdad (SparseGPT, Minitron, etc.) exige reentrenar/afinar y medir exactitud con tus datos; no se puede "activar" desde la app y Ollama solo carga modelos ya podados/cuantizados. No lo simulé. Lo que sí aporta el mismo efecto (menos cómputo por token) y es real:
- **Cuantización** Q4_K_M (la de Ollama por defecto) y **KV-cache q8_0** (`tune_ollama.bat`).
- **Computación condicional por pregunta**: la cascada es "pruning dinámico" a nivel de tarea.
- **MoE**: `qwen3:30b-a3b` activa ~3B parámetros por token; el perfil `gpu_xl` lo prefiere como modelo de arbitraje si está instalado.
- Si consigues un GGUF podado, créalo con `ollama create` y ponlo en `FAST_MODEL`.

## Qué NO está medido (importante)
No pude ejecutar modelos reales aquí. Verificado con un Ollama simulado: el enrutamiento, las llamadas realmente emitidas (p. ej. una pregunta que coincide con GES = 1 llamada, sin modelo fuerte ni explicación), caché, inferencia de clave, degradación sin logprobs y presupuesto. **No verificado**: velocidad real, exactitud real de Qwen3 pequeño con logprobs, y el formato exacto de `logprobs` de tu versión de Ollama (se parsea de forma defensiva y, si falta, se usa el acuerdo con GES). La velocidad real la ves en el panel «Rendimiento medido» y con `GET /hardware?bench=true`.
Límite físico: el *prefill* (leer ~150-300 tokens por pregunta) sigue costando en CPU lenta; una corrección «imperceptible» es realista con GPU o con CPU rápida y caché caliente, y en CPU modesta se oculta porque la corrección empieza al capturar, mientras revisas.
