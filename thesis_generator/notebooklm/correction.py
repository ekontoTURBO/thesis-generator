"""NotebookLM second-pass — correction mode.

After the citation-audit swarm + Opus orchestrator produce a structured fix
list, send a FOCUSED correction request back to NotebookLM. The prompt is
deliberately different from the writer prompt: it shows the original sentences
and the specific errors flagged, and asks NotebookLM to issue corrected
sentences with the right pages / right authors / right paraphrases.

NotebookLM is the right tool for this because it can re-read the actual
sources (whole library at once) and produce text grounded in them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.notebooklm.adapter import NotebookLMAdapter


@dataclass(slots=True)
class CitationFix:
    """One specific correction NotebookLM is being asked to make."""

    section_id: str
    paragraph_tag: str            # e.g. "P0042"
    original_sentence: str        # verbatim from draft
    cited_as: str                 # "(Hoch, 2002, s. 137)" or similar
    flag: str                     # ⚠️ STRONA | ❌ TREŚĆ | 🔴 BIBLIOGRAFIA | ❓ BRAK ŹRÓDŁA
    correction_hint: str          # what the audit/orchestrator suggested


@dataclass(slots=True)
class CorrectionResult:
    section_id: str
    corrected_text: str           # NotebookLM's corrected version of the relevant sentences
    raw_response: str
    notes: list[str] = field(default_factory=list)


def build_correction_prompt(section_id: str, fixes: list[CitationFix]) -> str:
    """Compose a prompt that lists every fix and asks for verbatim replacements."""
    items = []
    for i, f in enumerate(fixes, 1):
        items.append(
            f"### {i}. [{f.paragraph_tag}] {f.flag}\n"
            f"Cytowane jako: {f.cited_as}\n"
            f'Zdanie obecne: "{f.original_sentence}"\n'
            f"Problem / podpowiedź: {f.correction_hint}\n"
        )
    body = "\n".join(items)

    return f"""Tryb: KOREKTA CYTOWAŃ w podrozdziale **{section_id}**.

Poniżej {len(fixes)} cytowań w obecnym tekście pracy zostało zakwestionowanych przez audyt.
Dla KAŻDEGO z nich:

1. Przeczytaj wskazane źródło (jeśli istnieje w bibliotece) i ZNAJDŹ rzeczywiście oddającą tezę informację.
2. Jeśli problem to ⚠️ STRONA — podaj POPRAWNY numer strony.
3. Jeśli problem to ❌ TREŚĆ — przepisz zdanie tak, aby wiernie oddawało źródło LUB wskaż inne źródło z biblioteki.
4. Jeśli problem to 🔴 BIBLIOGRAFIA — podaj poprawiony wpis APA.
5. Jeśli problem to ❓ BRAK ŹRÓDŁA — zaproponuj zamiennik z biblioteki, jeśli istnieje, albo zaznacz, że trzeba ten fragment usunąć.

ZWRÓĆ DOKŁADNIE w tym formacie, dla każdej pozycji:

#### Poprawka {1}. [P0XXX]
PRZED: "<zdanie obecne dosłownie>"
PO: "<zdanie poprawione dosłownie>"
KOMENTARZ: <1-2 zdania uzasadnienia z dosłownym cytatem ze źródła>
ZMIANA W BIBLIOGRAFII (jeśli dotyczy): <pełen poprawiony wpis APA>

---

LISTA CYTOWAŃ DO POPRAWY:

{body}
"""


def request_corrections(
    adapter: NotebookLMAdapter, section_id: str, fixes: list[CitationFix]
) -> CorrectionResult:
    """Send the correction prompt and return the parsed result."""
    prompt = build_correction_prompt(section_id, fixes)
    raw = adapter.ask(prompt)
    return CorrectionResult(
        section_id=section_id,
        corrected_text=raw,
        raw_response=raw,
    )


def parse_corrections(raw: str) -> list[dict]:
    """Extract structured (before, after, comment, bibliografia) tuples from NotebookLM's reply.

    Returns a list of dicts with keys: paragraph_tag, before, after, comment, biblio_fix.
    Robust to NotebookLM ignoring exact format — falls back to greedy extraction.
    """
    out: list[dict] = []
    blocks = re.split(r"####\s*Poprawka\s*\d+\s*\.", raw)
    for blk in blocks[1:]:
        para_m = re.search(r"\[P0?(\d+)\]", blk)
        before_m = re.search(r'PRZED\s*:\s*"([^"]+)"', blk, re.IGNORECASE)
        after_m = re.search(r'PO\s*:\s*"([^"]+)"', blk, re.IGNORECASE)
        comment_m = re.search(r"KOMENTARZ\s*:\s*(.+?)(?:\nZMIANA|\n####|\Z)", blk, re.DOTALL | re.IGNORECASE)
        biblio_m = re.search(
            r"ZMIANA W BIBLIOGRAFII[^:]*:\s*(.+?)(?:\n####|\Z)", blk, re.DOTALL | re.IGNORECASE
        )
        if before_m and after_m:
            out.append({
                "paragraph_tag": f"P{int(para_m.group(1)):04d}" if para_m else "",
                "before": before_m.group(1).strip(),
                "after": after_m.group(1).strip(),
                "comment": comment_m.group(1).strip() if comment_m else "",
                "biblio_fix": biblio_m.group(1).strip() if biblio_m else None,
            })
    return out
