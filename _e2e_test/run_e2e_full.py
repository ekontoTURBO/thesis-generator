"""FULL E2E test using `claude -p` (Claude Code CLI) instead of API key.

Exercises every LLM-dependent phase:
  - writer (Opus generates one section on VR/WoM)
  - Ring B (Haiku per source — skipped, no real PDFs in sources/)
  - Ring C two-step (NotebookLM grounds + Haiku judges via CLI)
  - independent reviewer (Opus grades the stub thesis)

All four use the user's Claude Code subscription. No ANTHROPIC_API_KEY needed.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from thesis_generator.config import ThesisProject
from thesis_generator.docx_ops.humanize import humanize_docx
from thesis_generator.inventory import build_inventory
from thesis_generator.llm import ClaudeCLI
from thesis_generator.review.independent import run_independent_review, save_report as save_review
from thesis_generator.verify.internal import run_ring_a, save_report as save_a
from thesis_generator.verify.notebooklm_ring import run_ring_c, save_report as save_c
from thesis_generator.writer import SectionSpec, write_section

PROJECT_DIR = Path(__file__).parent
project = ThesisProject.load(PROJECT_DIR)

print("=" * 70)
print(f"FULL E2E — {project.title}")
print(f"LLM backend: claude -p (Claude Code CLI, OAuth, no API key)")
print(f"NotebookLM library: {project.notebooklm.library_name}")
print("=" * 70)

cli = ClaudeCLI(max_concurrent=3)

# -------- 1. inventory --------
print("\n[1/5] INVENTORY")
inv = build_inventory(project)
print(f"  → {len(inv.sources)} source PDFs indexed (0 expected — no real sources/)")
print(f"  → draft style: {inv.style.paragraph_count} paragraphs, {len(inv.style.cited_pairs)} citations, "
      f"{inv.style.em_dash_count} em-dashes")

# -------- 2. Ring A --------
print("\n[2/5] RING A (internal regex)")
ring_a = run_ring_a(project)
save_a(ring_a, project)
print(f"  → {len(ring_a.citations_in_text)} citations, {len(ring_a.bib_entries)} bib entries")
print(f"  → missing-from-bib: {[f'{s} {y}' for s,y in ring_a.missing_in_bib]}")
print(f"  → orphans: {[e.first_surname for e in ring_a.orphaned_in_bib]}")
print(f"  → STATUS: {'PASS' if ring_a.passed else 'FAIL'}")

# -------- 3. Writer (Opus via CLI) --------
print("\n[3/5] WRITER (Opus via claude -p)")
spec = SectionSpec(
    id="0.intro_test",
    heading="Wstęp testowy — WoM w VR commerce",
    brief=(
        "Napisz krótki (~1500 znaków) wstęp do pracy licencjackiej o marketingu szeptanym (WoM) "
        "w wirtualnej rzeczywistości. Wprowadź temat, uzasadnij wybór (luka badawcza), zarysuj cel pracy. "
        "Zacytuj co najmniej 2 z istniejących źródeł: Hoch 2002, Trusov 2009, Rosario 2016, Berger 2013, Batorski 2006."
    ),
    target_chars=1500,
    required_citations=["Hoch_2002", "Trusov_2009"],
    raw_data_refs=[],
)
t0 = time.time()
written = asyncio.run(write_section(project, spec, inv, cli=cli))
dt = time.time() - t0
print(f"  → Opus returned {len(written.text)} chars in {dt:.0f}s")
print(f"  → used_citations: {written.used_citations}")
print(f"  → notes: {written.notes[:3]}")
print(f"\n  --- WRITER OUTPUT (first 800 chars) ---")
print(f"  {written.text[:800]}…")

# Save written section
(PROJECT_DIR / "_state" / "writer_test_section.txt").write_text(written.text, encoding="utf-8")

# -------- 4. Ring C two-step (NotebookLM + CLI judge) --------
print("\n[4/5] RING C — TWO-STEP (NotebookLM grounds + Haiku judges via claude -p)")
print("  (4 queries × ~30s NotebookLM + ~10s Haiku judge = ~3 min total)")
paraphrases = {
    ("Hoch", "2002"): {
        "paraphrase": "Konsumenci uznają rekomendacje innych konsumentów za bardziej wiarygodne niż komunikaty marketingowe marek.",
        "cited_page": "s. 137",
    },
    ("Trusov", "2009"): {
        "paraphrase": "eWOM kształtuje sprzedaż w sposób mierzalny i trwały.",
        "cited_page": "s. 90",
    },
    ("Berger", "2013"): {
        "paraphrase": "Mechanika wiralności opiera się na trzech elementach: zaskoczeniu, emocjach i społecznej wymianie.",
        "cited_page": "s. 14",
    },
}
t0 = time.time()
ring_c = asyncio.run(run_ring_c(project, paraphrases=paraphrases))
dt = time.time() - t0
save_c(ring_c, project)
print(f"  → Ring C completed in {dt:.0f}s")
print(f"  → OK: {sum(1 for r in ring_c.results if r.verdict.value == 'OK')}/{len(ring_c.results)}")
for r in ring_c.results:
    excerpt = (r.excerpt[:80] + "…") if len(r.excerpt) > 80 else r.excerpt
    print(f"    {r.citation_key:20s} {r.verdict.value:12s} | {excerpt}")

# -------- 5. Independent reviewer (Opus via CLI) --------
print("\n[5/5] INDEPENDENT REVIEWER (Opus via claude -p, zero context)")
t0 = time.time()
review = run_independent_review(project, cli=cli)
dt = time.time() - t0
save_review(review, project)
print(f"  → Reviewer completed in {dt:.0f}s")
print(f"  → GRADE: {review.grade}")
if review.grade_justification:
    print(f"  → Justification: {review.grade_justification[:200]}…")
print(f"  → {len(review.problems)} problems, {len(review.strengths)} strengths")

print("\n" + "=" * 70)
print("FULL E2E DONE.")
print(f"Reports: {project.reports_dir()}")
print("=" * 70)
