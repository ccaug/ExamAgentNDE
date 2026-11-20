#!/usr/bin/env python3
"""Genera la tabla de scores desde data/examagent-informe.csv.

Uso:  python analysis/table_scores.py
"""
import csv
from pathlib import Path

CSV = Path(__file__).resolve().parent.parent / "data" / "examagent-informe.csv"

def main() -> None:
    if not CSV.exists():
        raise SystemExit(f"No existe {CSV}")
    scores: dict[str, float] = {}
    with CSV.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            key = row.get("examen") or row.get("student") or "S01"
            try:
                scores[key] = scores.get(key, 0.0) + float(row["nota_final"])
            except (KeyError, ValueError):
                continue
    if not scores:
        raise SystemExit("No se pudo extraer ninguna nota.")
    ordered = sorted(scores.items(), key=lambda kv: kv[1])
    print("\\begin{tabular}{l" + "r" * len(ordered) + "}")
    print("\\hline")
    print("Exam & " + " & ".join(k for k, _ in ordered) + " \\\\")
    print("Score & " + " & ".join(f"{v:.0f}" for _, v in ordered) + " \\\\")
    print("\\hline")
    print("\\end{tabular}")

if __name__ == "__main__":
    main()
