"""E2E test: Ring C (NotebookLM) + humanize on the stub draft.

Bypasses env_check (which hard-gates on missing ANTHROPIC_API_KEY) and exercises
the phases that don't need the Claude API:
  - inventory (already ran)
  - Ring A   (already ran via CLI)
  - Ring C   (NotebookLM only — the user's emphasis)
  - humanize (regex/python-docx)

Reports each phase's outcome and the actual NotebookLM verdicts.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from thesis_generator.config import ThesisProject
from thesis_generator.docx_ops.humanize import humanize_docx
from thesis_generator.verify.notebooklm_ring import run_ring_c, save_report

PROJECT_DIR = Path(__file__).parent
project = ThesisProject.load(PROJECT_DIR)
print(f"Project: {project.title}")
print(f"NotebookLM library: {project.notebooklm.library_name}")
print(f"NotebookLM URL: {project.notebooklm.library_url}")
print()


# ---- HUMANIZE ----
print("=" * 70)
print("PHASE: humanize")
print("=" * 70)
# Work on a COPY so we don't destroy the test draft
import shutil

draft_copy = PROJECT_DIR / "inputs" / "draft_humanized.docx"
shutil.copy(project.resolve_input(project.inputs.draft), draft_copy)
stats = humanize_docx(draft_copy, project.humanization)
print(stats.render())
print()


# ---- RING C (NotebookLM) ----
print("=" * 70)
print("PHASE: Ring C — NotebookLM source-grounded verification")
print("=" * 70)
print("Sending 4 verification queries to NotebookLM (this takes 1-3 min each)…")
print("Library: 94 sources on VR/WoM/behavioral economics")
print()

# Paraphrase map keyed on (surname, year). Each entry has the actual claim
# the stub draft makes about that source. NotebookLM will cross-check them.
paraphrases = {
    ("Hoch", "2002"): {
        "paraphrase": "Konsumenci uznają rekomendacje innych konsumentów za bardziej wiarygodne niż komunikaty marketingowe marek.",
        "cited_page": "s. 137",
    },
    ("Trusov", "2009"): {
        "paraphrase": "eWOM kształtuje sprzedaż w sposób mierzalny i trwały.",
        "cited_page": "s. 90",
    },
    ("Rosario", "2016"): {
        "paraphrase": "Efekt eWOM jest silniejszy w kategoriach produktów doświadczalnych niż użytkowych.",
        "cited_page": "s. 305",
    },
    ("Berger", "2013"): {
        "paraphrase": "Mechanika wiralności opiera się na trzech elementach: zaskoczeniu, emocjach i społecznej wymianie.",
        "cited_page": "s. 14",
    },
}

t0 = time.time()
ring_c_result = asyncio.run(run_ring_c(project, paraphrases=paraphrases))
dt = time.time() - t0
print(f"Ring C completed in {dt:.0f}s")
print()

report_path = save_report(ring_c_result, project)
print(f"Report saved: {report_path}")
print()

# Print verdict summary
print("VERDICTS:")
for r in ring_c_result.results:
    excerpt = (r.excerpt[:100] + "…") if len(r.excerpt) > 100 else r.excerpt
    print(f"  {r.citation_key:20s} {r.verdict.value:12s} | {excerpt}")

print()
print("DONE. Reports in:", project.reports_dir())
