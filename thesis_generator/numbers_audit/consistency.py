"""Hypothesis ↔ conclusion consistency check — second Opus call.

After `recomputer.py` produces the parallel workbook + diff list, this module
asks: do the conclusions in the thesis actually follow from the data?

Specifically:
  - For every H1/H2/H3 declaration in the methodology section, is there a
    matching test result + verdict in the results section?
  - When the draft says "H1 została potwierdzona" — does the recomputed test
    statistic + p-value actually support that?
  - When the conclusion says "wyniki wskazują, że X" — is X really what the
    data shows, or is it an over-interpretation?

One Opus call given: hypothesis statements (extractor) + recompute diffs
+ key conclusion sentences. Returns per-hypothesis verdict.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.config import ThesisProject
from thesis_generator.llm import ClaudeCLI
from thesis_generator.numbers_audit.extractor import (
    HypothesisStatement,
    extract_hypotheses,
)
from thesis_generator.numbers_audit.recomputer import (
    NumericRecomputeResult,
    RecomputeDiff,
)


@dataclass(slots=True)
class HypothesisVerdict:
    hypothesis_id: str
    declaration: str
    claimed_verdict: str | None      # "potwierdzona" | "odrzucona" | "częściowo" | None
    judged_verdict: str              # SUPPORTED | NOT_SUPPORTED | PARTIALLY | OVER_INTERPRETED | INSUFFICIENT_DATA
    reasoning: str                   # 2-4 sentences
    relevant_stats: list[str] = field(default_factory=list)  # which recomputed numbers were used


@dataclass(slots=True)
class HypothesisConsistencyResult:
    verdicts: list[HypothesisVerdict] = field(default_factory=list)
    raw_response: str = ""
    markdown_report_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def overinterpretations(self) -> int:
        return sum(1 for v in self.verdicts if v.judged_verdict == "OVER_INTERPRETED")

    @property
    def supported(self) -> int:
        return sum(1 for v in self.verdicts if v.judged_verdict == "SUPPORTED")


_SYSTEM_PROMPT = """Jesteś niezależnym statystykiem-recenzentem pracy licencjackiej.
Czytasz: (a) hipotezy i ich werdykty z pracy, (b) niezależnie przeliczone statystyki
z surowych danych. Twoje zadanie: dla każdej hipotezy ocenić czy dane RZECZYWIŚCIE
ją potwierdzają lub odrzucają.

Możliwe werdykty:
- SUPPORTED — dane mocno popierają hipotezę zgodnie z deklaracją autora
- NOT_SUPPORTED — dane NIE popierają hipotezy (a autor twierdzi że tak)
- PARTIALLY — częściowe wsparcie, autor powinien zniuansować
- OVER_INTERPRETED — autor wyciąga wnioski silniejsze niż dane uzasadniają
- INSUFFICIENT_DATA — brak danych żeby ocenić

Bądź konkretny — cytuj REKOMPUTOWANE wartości (nie te z pracy) i p-values.
"""


_USER_PROMPT_TEMPLATE = """## Hipotezy z pracy

{hypotheses}

## Wyniki niezależnej rekompilacji statystyk

{diffs}

## Twoje zadanie

Dla KAŻDEJ hipotezy (H1, H2, H3...) wystaw werdykt w formacie:

#### VERDICT
HYPOTHESIS_ID: H1
DECLARATION: "<dosłowna treść hipotezy z deklaracji>"
CLAIMED_VERDICT: <co autor twierdzi w pracy — "potwierdzona" | "odrzucona" | "częściowo" | null>
JUDGED_VERDICT: <SUPPORTED | NOT_SUPPORTED | PARTIALLY | OVER_INTERPRETED | INSUFFICIENT_DATA>
REASONING: <2-4 zdania uzasadnienia z konkretnymi statystykami (p, t, χ², d) z rekompilacji>
RELEVANT_STATS: <comma-separated list of P0XXX tags z diff listy które były podstawą werdyktu>

#### VERDICT
HYPOTHESIS_ID: H2
...
"""


def check_hypothesis_consistency(
    project: ThesisProject,
    recompute: NumericRecomputeResult,
    *,
    cli: ClaudeCLI | None = None,
) -> HypothesisConsistencyResult:
    """Dispatch ONE Opus call to judge per-hypothesis consistency."""
    cli = cli or ClaudeCLI(max_concurrent=1)
    result = HypothesisConsistencyResult()

    draft = project.resolve_input(project.inputs.draft)
    hypotheses = extract_hypotheses(draft)
    if not hypotheses:
        result.notes.append("No H1/H2/H3 hypothesis statements detected in draft.")
        return result

    if not recompute.diffs:
        result.notes.append("No recompute diffs available — run `tg recompute-data` first.")
        return result

    h_block = "\n".join(h.to_prompt_line() for h in hypotheses)
    diffs_block = "\n".join(
        f"  - [{d.paragraph_tag}] {d.claimed} → recomputed {d.recomputed} ({d.status}). {d.note[:140]}"
        for d in recompute.diffs
    )
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        hypotheses=h_block,
        diffs=diffs_block,
    )

    resp = asyncio.run(cli.complete(
        model="opus",
        system=_SYSTEM_PROMPT,
        user=user_prompt,
        timeout=600,
    ))
    result.raw_response = resp.text
    result.verdicts = _parse_verdicts(resp.text)

    # Persist report
    md = _render_report(result, project)
    out_md = project.reports_dir() / "hypothesis_consistency.md"
    out_md.write_text(md, encoding="utf-8")
    result.markdown_report_path = out_md

    return result


# ---------------------------------------------------------------- Parser


def _parse_verdicts(text: str) -> list[HypothesisVerdict]:
    out: list[HypothesisVerdict] = []
    for blk in re.split(r"####\s*VERDICT\b", text)[1:]:
        hid_m = re.search(r"HYPOTHESIS_ID\s*:\s*(\S+)", blk)
        decl_m = re.search(r'DECLARATION\s*:\s*"([^"]+)"', blk)
        claimed_m = re.search(r"CLAIMED_VERDICT\s*:\s*(\S+?)(?:\n|$)", blk)
        judged_m = re.search(r"JUDGED_VERDICT\s*:\s*(\S+)", blk)
        reason_m = re.search(
            r"REASONING\s*:\s*(.+?)(?=\nRELEVANT_STATS|\n####|\Z)",
            blk,
            re.DOTALL,
        )
        stats_m = re.search(r"RELEVANT_STATS\s*:\s*(.+?)(?=\n####|\Z)", blk, re.DOTALL)
        if not (hid_m and judged_m):
            continue
        relevant = []
        if stats_m:
            relevant = [s.strip() for s in re.split(r"[,\s]+", stats_m.group(1)) if s.strip().startswith("P")]
        claimed_v = claimed_m.group(1).strip().strip(",;") if claimed_m else None
        if claimed_v and claimed_v.lower() == "null":
            claimed_v = None
        out.append(HypothesisVerdict(
            hypothesis_id=hid_m.group(1).strip(),
            declaration=decl_m.group(1).strip() if decl_m else "",
            claimed_verdict=claimed_v,
            judged_verdict=judged_m.group(1).strip().upper(),
            reasoning=reason_m.group(1).strip() if reason_m else "",
            relevant_stats=relevant,
        ))
    return out


def _render_report(result: HypothesisConsistencyResult, project: ThesisProject) -> str:
    lines = [f"# Hypothesis-consistency audit — {project.title}\n"]
    lines.append(f"**Hypotheses judged:** {len(result.verdicts)}")
    lines.append(f"**SUPPORTED:** {result.supported}")
    lines.append(f"**OVER_INTERPRETED:** {result.overinterpretations}")
    not_sup = sum(1 for v in result.verdicts if v.judged_verdict == "NOT_SUPPORTED")
    lines.append(f"**NOT_SUPPORTED:** {not_sup}\n")

    for v in result.verdicts:
        icon = {
            "SUPPORTED": "✅",
            "NOT_SUPPORTED": "❌",
            "PARTIALLY": "⚠️",
            "OVER_INTERPRETED": "🚨",
            "INSUFFICIENT_DATA": "❓",
        }.get(v.judged_verdict, "•")
        lines.append(f"\n## {icon} {v.hypothesis_id} — {v.judged_verdict}")
        lines.append(f"_Declaration:_ {v.declaration}")
        if v.claimed_verdict:
            lines.append(f"_Author's verdict in draft:_ {v.claimed_verdict}")
        lines.append(f"\n{v.reasoning}")
        if v.relevant_stats:
            lines.append(f"\n_Relevant recomputed stats:_ {', '.join(v.relevant_stats)}")

    if result.notes:
        lines.append("\n## Notes")
        for n in result.notes:
            lines.append(f"- {n}")

    return "\n".join(lines)
