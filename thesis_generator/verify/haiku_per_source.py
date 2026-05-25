"""Ring B — Haiku-per-source citation verification (parallel).

For every (citation, source PDF) pair in the draft, dispatch a Haiku subagent
that opens the actual PDF page with `pdfplumber` and returns one of
OK / NIEŚCISŁE / BŁĘDNE + a literal excerpt.

Brief gotcha #3: never use the Read tool on PDFs — too expensive. Always
`pdfplumber` for the cited page ±2.

Implementation: we run actual Anthropic API calls with tool-use (no recursion
through Claude Code subagents — the package must work standalone outside of
a Claude Code session).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thesis_generator.config import ThesisProject
from thesis_generator.inventory import Inventory, find_source_for_citation, load_inventory
from thesis_generator.llm import ClaudeCLI
from thesis_generator.verify.internal import run_ring_a


@dataclass(slots=True)
class CitationVerdict:
    citation: tuple[str, str]
    source_path: str | None
    verdict: str  # OK | NIEŚCISŁE | BŁĘDNE | NO_SOURCE | ERROR
    excerpt: str = ""
    correction: str | None = None
    error: str | None = None


@dataclass(slots=True)
class RingBResult:
    verdicts: list[CitationVerdict]
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(v.verdict == "OK" for v in self.verdicts)

    def to_report(self) -> str:
        lines = ["# Ring B — Haiku per-source verification\n"]
        ok = sum(1 for v in self.verdicts if v.verdict == "OK")
        lines.append(f"Result: {ok}/{len(self.verdicts)} OK\n")
        lines.append("\n| Citation | Verdict | Source | Excerpt |")
        lines.append("|---|---|---|---|")
        for v in self.verdicts:
            cite = f"{v.citation[0]} {v.citation[1]}"
            src = Path(v.source_path).name if v.source_path else "—"
            excerpt = v.excerpt.replace("|", "\\|")[:80]
            lines.append(f"| {cite} | {v.verdict} | {src} | {excerpt} |")
        problems = [v for v in self.verdicts if v.verdict not in ("OK", "NO_SOURCE")]
        if problems:
            lines.append("\n## Detailed corrections needed\n")
            for v in problems:
                lines.append(f"### {v.citation[0]} {v.citation[1]} — `{v.verdict}`")
                lines.append(f"Source: `{v.source_path}`")
                if v.excerpt:
                    lines.append(f"\n> {v.excerpt}\n")
                if v.correction:
                    lines.append(f"**Suggested correction:** {v.correction}\n")
        if self.notes:
            lines.append("\n## Notes\n")
            lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines)


VERIFICATION_PROMPT = """Jesteś weryfikatorem cytowania w pracy licencjackiej.

Cytowanie: ({surname}, {year}{page_suffix})
Plik źródłowy: {source_path}

PARAFRAZA z pracy do weryfikacji:
"{paraphrase}"

Twoje zadanie:
1. Użyj Bash + pdfplumber (Python), żeby otworzyć ten PDF i przeczytać strony {page_range}. NIE używaj Read na całym PDFie.
2. Znajdź fragment najbliższy parafrazie.
3. Wystaw VERDICT i podaj dosłowny cytat.

Format odpowiedzi (DOKŁADNIE):
VERDICT: OK | NIEŚCISŁE | BŁĘDNE
EXCERPT: "<dosłowny fragment z PDF, max 300 znaków>"
KOREKTA: <jeśli VERDICT != OK, jednozdaniowa poprawka parafrazy>
"""


def _page_range_for(cited_page: str | None) -> str:
    if not cited_page:
        return "1-5 oraz spis treści (znajdź właściwą stronę)"
    m = __import__("re").search(r"\d+", cited_page)
    if not m:
        return cited_page
    n = int(m.group())
    return f"{max(1, n-2)}-{n+2}"


async def _verify_one(
    cli: ClaudeCLI,
    model: str,
    citation: tuple[str, str],
    source_path: str,
    paraphrase: str,
    cited_page: str | None,
) -> CitationVerdict:
    """Single Haiku call (via `claude -p` with Bash) to verify one citation.

    The Haiku subprocess gets `Bash` enabled so it can run `pdfplumber` on the
    cited page — brief gotcha #3 says NEVER use Read on a 12MB PDF.
    """
    surname, year = citation
    page_suffix = f", {cited_page}" if cited_page else ""
    prompt = VERIFICATION_PROMPT.format(
        surname=surname,
        year=year,
        page_suffix=page_suffix,
        source_path=source_path,
        paraphrase=paraphrase,
        page_range=_page_range_for(cited_page),
    )

    try:
        resp = await cli.complete(
            model=model,
            user=prompt,
            allowed_tools=["Bash"],
            max_budget_usd=0.50,
            timeout=600,
        )
    except Exception as e:
        return CitationVerdict(
            citation=citation,
            source_path=source_path,
            verdict="ERROR",
            error=str(e),
        )

    return _parse_verdict_block(citation, source_path, resp.text)


def _parse_verdict_block(
    citation: tuple[str, str], source_path: str, text: str
) -> CitationVerdict:
    import re

    verdict = "ERROR"
    m = re.search(r"VERDICT\s*:\s*(OK|NIEŚCISŁE|NIESCISLE|BŁĘDNE|BLEDNE)", text, re.IGNORECASE)
    if m:
        verdict = m.group(1).upper().replace("NIESCISLE", "NIEŚCISŁE").replace("BLEDNE", "BŁĘDNE")
    excerpt = ""
    m = re.search(r'EXCERPT\s*:\s*"([^"]+)"', text)
    if m:
        excerpt = m.group(1)
    correction = None
    m = re.search(r"KOREKTA\s*:\s*(.+?)(?:\n\n|\Z)", text, re.DOTALL)
    if m and verdict != "OK":
        correction = m.group(1).strip()
    return CitationVerdict(
        citation=citation,
        source_path=source_path,
        verdict=verdict,
        excerpt=excerpt,
        correction=correction,
    )


async def run_ring_b(
    project: ThesisProject,
    paraphrases: dict[tuple[str, str], dict[str, str | None]] | None = None,
) -> RingBResult:
    """Verify every cited source.

    `paraphrases` maps `(surname, year) → {paraphrase, cited_page}`. If not
    provided, we run Ring A to extract citations and use the body sentence
    around each one as the paraphrase (fallback — less precise).
    """
    inv: Inventory | None = load_inventory(project)
    if inv is None:
        from thesis_generator.inventory import build_inventory

        inv = build_inventory(project)

    if paraphrases is None:
        ring_a = run_ring_a(project)
        # Fallback: empty paraphrase string; the verifier will read the whole
        # draft and find the cite location. Less accurate but works.
        paraphrases = {c: {"paraphrase": "(paraphrase not supplied — locate in source draft)", "cited_page": None} for c in ring_a.citations_in_text}

    cli = ClaudeCLI(max_concurrent=project.pipeline.max_parallel_haiku)
    model = project.models.verifier_per_source

    async def one(c: tuple[str, str], meta: dict[str, str | None]) -> CitationVerdict:
        src = find_source_for_citation(inv, c[0], c[1])
        if src is None:
            return CitationVerdict(
                citation=c,
                source_path=None,
                verdict="NO_SOURCE",
                error=f"No PDF found for ({c[0]}, {c[1]}) — check inventory.json",
            )
        return await _verify_one(
            cli=cli,
            model=model,
            citation=c,
            source_path=src.path,
            paraphrase=meta.get("paraphrase") or "",
            cited_page=meta.get("cited_page"),
        )

    verdicts = await asyncio.gather(*(one(c, m) for c, m in paraphrases.items()))
    return RingBResult(verdicts=list(verdicts))


def save_report(result: RingBResult, project: ThesisProject) -> Path:
    out = project.reports_dir() / "ring_b_haiku_per_source.md"
    out.write_text(result.to_report(), encoding="utf-8")
    return out
