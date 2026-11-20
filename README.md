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
and click *Analyze exam*. See `README.md` below for the full workflow.

**Data.** The anonymised CSV of the deployment is in
`data/examagent-informe.csv`. The survey data is in `survey/responses.csv`.

**Design rationale.** See `EFFICIENCY.md` for why the cascade works.

---

# ExamAgent NDE 2.1

Workflow: **Analyze exam → Qwen grades everything → edit whatever you want → LAUNCH FINAL GRADE.**

## Installation (one time)
1. Extract the ZIP into a new folder and run `run.bat` (installs dependencies and opens the dashboard).
2. Install Ollama. **Models are selected automatically** according to your hardware (GPU/VRAM/RAM): a small fast model and a larger one used only for arbitration. If missing, the dashboard offers to download them. Optional: `tune_ollama.bat` (flash attention, KV cache q8_0). Details: `EFFICIENCY.md`.
3. Chrome → `chrome://extensions` → enable *Developer mode* → remove the previous extension → *Load unpacked* → folder `chrome_extension`.

## Usage
1. Open the exam in GES and click the extension → **Analyze exam**. The dashboard opens.
2. Qwen evaluates the 80 questions **in cascade** (1 token per decision; the strong model only arbitrates disagreements/doubts), **including those GES already graded**. You will see the GES grade, the AI grade, and the final grade.
3. Edit the grade or explanation of any question in the dashboard (saved instantly). Use the "Doubtful" filter for those the model could not judge with confidence.
4. **LAUNCH FINAL GRADE**: the extension walks through GES, clicks *Edit* on each question that changes, writes points (and explanation), clicks *Accept*, verifies that GES shows the grade, and moves on. It stops on any anomaly.
   - Recommended the first time: **Simulate** (opens and closes the form without writing) and **Test with 1 question**.
   - Do not close or reload the GES tab while it is uploading. There is a *Stop* button in GES and in the dashboard.

## Built-in safety
- Only grades that differ from GES (or explanations you edited) are uploaded, unless you check "Rewrite all".
- The tab URL, the range of each grade, and the value shown after saving are verified; at the end the whole exam is re-read and the grades are compared.
- Audit log: `data/publish_log.jsonl`. CSV report from the dashboard.
- Service only on 127.0.0.1; only the dashboard and the extension can issue write commands.

## Limits
- Quality depends on the installed models; smaller ones are weaker on open-ended answers (which is why they are arbitrated and marked "doubtful"). Use the optional key/instructions and review the "doubtful" ones.
- The GES editor is located by its labels ("Edit", "Points for the answer", "Change explanation", "Accept"). If they differ, the simulate mode detects it before writing anything.
- One exam (one student) per capture.

## Tests (development)
`python -m pytest tests -q` and `node tests/e2e_dom.test.js` (requires `npm i jsdom`, backend on :8765, and `python tests/fake_ollama.py`).
