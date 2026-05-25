"""Independent numerical recomputation — Opus agent with Bash tool.

Dispatches ONE long Opus call (via `claude -p` with `--allowedTools "Bash Read Write"`)
that:
  1. Receives a list of every numeric claim in the draft (with paragraph + sentence)
  2. Receives paths to every raw research-data file (xlsx/csv)
  3. Writes its own Python script that re-loads the raw data, computes every
     statistic from scratch (M, SD, %, χ², t-tests, correlations, etc.)
  4. Runs the script (via Bash tool)
  5. Saves a parallel workbook `output/_audits/recompute_audit.xlsx` with one
     sheet per statistic, showing inputs + computation + recomputed value
  6. Produces a markdown diff: for every claim, RECOMPUTED vs CLAIMED, with
     a delta and an OK/MISMATCH/UNVERIFIABLE flag

Why Opus and not Haiku: each thesis has a different data shape and different
statistics. Opus is needed to (a) read the data structure, (b) write correct
Python for the specific statistics claimed, (c) judge when a "small delta"
is rounding noise vs a real error.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.config import ThesisProject
from thesis_generator.llm import ClaudeCLI
from thesis_generator.numbers_audit.extractor import NumericClaim, extract_numeric_claims


@dataclass(slots=True)
class RecomputeDiff:
    """One claim's verdict after independent recomputation."""

    paragraph_tag: str
    claimed: str            # raw text as in draft
    recomputed: str         # what Opus actually got
    delta: str              # "Δ = 1.2" or "exact match" or "—"
    status: str             # OK | MISMATCH | UNVERIFIABLE | INTERPRETATION_OK
    note: str = ""          # 1-2 sentence explanation
    raw_value_claimed: float | None = None
    raw_value_recomputed: float | None = None


@dataclass(slots=True)
class NumericRecomputeResult:
    workbook_path: Path | None = None
    diffs: list[RecomputeDiff] = field(default_factory=list)
    raw_opus_response: str = ""
    markdown_report_path: Path | None = None
    script_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.diffs)

    @property
    def mismatches(self) -> int:
        return sum(1 for d in self.diffs if d.status == "MISMATCH")

    @property
    def unverifiable(self) -> int:
        return sum(1 for d in self.diffs if d.status == "UNVERIFIABLE")

    @property
    def ok_count(self) -> int:
        return sum(1 for d in self.diffs if d.status in ("OK", "INTERPRETATION_OK"))


_SYSTEM_PROMPT = """Jesteś niezależnym audytorem statystycznym dla pracy licencjackiej.
Twoje zadanie: zweryfikować każde twierdzenie liczbowe w pracy przeciwko surowym danym badawczym.

ZASADY:
1. NIE ufaj liczbom w pracy. Sprawdź każdą od zera.
2. Nigdy nie zmyślaj. Jeśli dane nie pozwalają na obliczenie — zaznacz UNVERIFIABLE z wyjaśnieniem.
3. Pisz własny skrypt Python, uruchom go przez Bash, zapisz parallel workbook z wyliczeniami.
4. Małe delta (np. 4.21 vs 4.205) to OK — zaokrąglenie. Wielkie delta (4.21 vs 1.63) to MISMATCH.
5. Jeśli claim jest jakościowy ("większość", "znacząco więcej") sprawdź czy dane to potwierdzają (INTERPRETATION_OK lub MISMATCH).
6. Dla testów statystycznych (t, χ², ANOVA) PRZELICZ test od podstaw, nie tylko porównaj cyfry.
"""


_USER_PROMPT_TEMPLATE = """## Twoje zadanie

Zwerifikuj WSZYSTKIE poniższe twierdzenia liczbowe z pracy licencjackiej przeciwko surowym danym.

## Surowe dane badawcze

{data_files}

## Lista twierdzeń liczbowych do weryfikacji ({n_claims})

{claims}

## Co masz zrobić

1. Napisz Pythona ({script_path}) który:
   a) wczytuje surowe dane (openpyxl/pandas — masz oba zainstalowane)
   b) dla KAŻDEGO twierdzenia z listy wylicza odpowiednią statystykę od zera
   c) zapisuje wszystkie wyniki do {workbook_path} — jeden arkusz per kategoria (Metryczka, Statystyki opisowe, Testy H1, Testy H2, ...)
   d) DRUKUJE na stdout: dla każdego claim linia w formacie JSON:
      {{"paragraph_tag": "P0042", "claimed": "65%", "recomputed": "64.7%", "delta": "Δ=0.3pp", "status": "OK", "note": "..."}}

2. Uruchom skrypt przez Bash. Złap output.

3. Zwróć w odpowiedzi:
   - Krótkie podsumowanie (3-5 zdań): ile OK, ile MISMATCH, jakie wzorce błędów
   - Pełen blok JSON-Lines z wyników (każdy claim w osobnej linii JSON)

OUTPUT FORMAT (DOKŁADNIE):

```
## SUMMARY
<3-5 zdań>

## DIFFS
<jeden JSON per linia, format jak wyżej>
```
"""


def run_recompute(
    project: ThesisProject,
    *,
    cli: ClaudeCLI | None = None,
    max_claims: int = 80,
) -> NumericRecomputeResult:
    """Dispatch ONE Opus call to recompute every numeric claim and produce a parallel workbook."""
    cli = cli or ClaudeCLI(max_concurrent=1)
    result = NumericRecomputeResult()

    # 1. Extract numeric claims from draft
    draft = project.resolve_input(project.inputs.draft)
    claims = extract_numeric_claims(draft)
    if not claims:
        result.notes.append("No numeric claims found in draft.")
        return result
    if len(claims) > max_claims:
        result.notes.append(
            f"Capped at {max_claims}/{len(claims)} claims (use --max-claims to raise)."
        )
        claims = claims[:max_claims]

    # 2. Collect raw data file paths
    data_files = project.effective_research_data_files()
    if not data_files:
        result.notes.append("No raw research data files found — recompute cannot run.")
        return result

    # 3. Prepare workspace
    audit_dir = project.output_dir() / "_audits"
    audit_dir.mkdir(parents=True, exist_ok=True)
    result.workbook_path = audit_dir / "recompute_audit.xlsx"
    result.script_path = project.state_dir() / "recompute_script.py"

    # 4. Build the prompt
    data_block = "\n".join(f"  - `{f}`" for f in data_files)
    claims_block = "\n".join(c.to_prompt_line() for c in claims)
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        data_files=data_block,
        n_claims=len(claims),
        claims=claims_block,
        script_path=str(result.script_path).replace("\\", "/"),
        workbook_path=str(result.workbook_path).replace("\\", "/"),
    )

    # 5. Dispatch Opus with Bash + Read + Write tools enabled
    resp = asyncio.run(_run_opus(cli, user_prompt))
    result.raw_opus_response = resp.text

    # 6. Parse the response into structured diffs
    result.diffs = _parse_opus_diffs(resp.text)

    # 7. Persist markdown report
    md = _render_report(result, project, claims)
    out_md = project.reports_dir() / "numbers_recompute.md"
    out_md.write_text(md, encoding="utf-8")
    result.markdown_report_path = out_md

    return result


# ---------------------------------------------------------------- Internals


async def _run_opus(cli: ClaudeCLI, user_prompt: str):
    return await cli.complete(
        model="opus",
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        allowed_tools=["Bash", "Read", "Write"],
        max_budget_usd=3.0,
        timeout=1800,
    )


def _parse_opus_diffs(text: str) -> list[RecomputeDiff]:
    """Pull JSON-lines out of the `## DIFFS` section."""
    diffs: list[RecomputeDiff] = []
    m = re.search(r"##\s*DIFFS\s*\n+(.+)", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return diffs
    body = m.group(1)
    for line in body.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        diffs.append(RecomputeDiff(
            paragraph_tag=d.get("paragraph_tag", ""),
            claimed=str(d.get("claimed", "")),
            recomputed=str(d.get("recomputed", "")),
            delta=str(d.get("delta", "")),
            status=str(d.get("status", "UNVERIFIABLE")).upper(),
            note=str(d.get("note", "")),
        ))
    return diffs


def _render_report(
    result: NumericRecomputeResult,
    project: ThesisProject,
    claims: list[NumericClaim],
) -> str:
    lines = [f"# Numbers recompute audit — {project.title}\n"]
    lines.append(f"**Workbook:** `{result.workbook_path}`")
    lines.append(f"**Script:** `{result.script_path}`\n")
    lines.append(f"**Total claims:** {result.total}")
    lines.append(f"**OK:** {result.ok_count}")
    lines.append(f"**Mismatches:** {result.mismatches}")
    lines.append(f"**Unverifiable:** {result.unverifiable}\n")

    if result.notes:
        lines.append("## Notes")
        for n in result.notes:
            lines.append(f"- {n}")

    # Summary block from Opus
    m = re.search(r"##\s*SUMMARY\s*\n+(.+?)(?=\n##|\Z)", result.raw_opus_response, re.DOTALL | re.IGNORECASE)
    if m:
        lines.append("\n## Opus summary\n")
        lines.append(m.group(1).strip())

    # Detailed diffs
    mismatches = [d for d in result.diffs if d.status == "MISMATCH"]
    if mismatches:
        lines.append("\n## ❌ Mismatches\n")
        lines.append("| Paragraph | Claimed | Recomputed | Δ | Note |")
        lines.append("|---|---|---|---|---|")
        for d in mismatches:
            note = d.note.replace("|", "\\|").replace("\n", " ")[:120]
            lines.append(f"| {d.paragraph_tag} | {d.claimed} | {d.recomputed} | {d.delta} | {note} |")

    unverifiable = [d for d in result.diffs if d.status == "UNVERIFIABLE"]
    if unverifiable:
        lines.append("\n## ❓ Unverifiable\n")
        for d in unverifiable:
            lines.append(f"- `{d.paragraph_tag}` {d.claimed}: {d.note}")

    return "\n".join(lines)
