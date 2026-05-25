"""Opus orchestrator — reads Haiku swarm reports, asks targeted follow-ups, produces fix list.

After the Haiku-per-section swarm completes, Opus walks every section report.
For each non-✅ citation it asks the section's Haiku a focused follow-up
("show me the exact page in the PDF where the claim actually appears, or
suggest a replacement source"), then synthesizes a structured fix list:

  [
    { section_id: "1.2", paragraph_tag: "P0042", original: "...",
      cited_as: "(Hoch, 2002, s. 137)", flag: "⚠️ STRONA",
      correction_hint: "actual claim is on s. 142" }
    ...
  ]

This is the "analyst-then-builder" orchestration pattern from the brief —
multiple analyst agents (Haikus) produce raw findings, then one orchestrator
(Opus) integrates and prioritizes them.

The output feeds directly into `notebooklm.correction.request_corrections`
which sends the fix list back to NotebookLM for a second-pass rewrite.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.citation_audit.adapter import CitationAuditResult, SectionReport
from thesis_generator.config import ThesisProject
from thesis_generator.llm import ClaudeCLI
from thesis_generator.notebooklm.correction import CitationFix


@dataclass(slots=True)
class OpusOrchestratorResult:
    fixes: list[CitationFix] = field(default_factory=list)
    summary: str = ""
    per_section_summaries: dict[str, str] = field(default_factory=dict)

    def by_section(self) -> dict[str, list[CitationFix]]:
        out: dict[str, list[CitationFix]] = {}
        for f in self.fixes:
            out.setdefault(f.section_id, []).append(f)
        return out


# ---------------------------------------------------------------- Main entry


def orchestrate_fixes(
    project: ThesisProject,
    audit: CitationAuditResult,
    *,
    cli: ClaudeCLI | None = None,
) -> OpusOrchestratorResult:
    """Run Opus once per problematic section. Returns a flat fix list."""
    cli = cli or ClaudeCLI(max_concurrent=3)
    result = OpusOrchestratorResult()

    problematic = [s for s in audit.sections if s.total > s.ok_count]
    if not problematic:
        result.summary = "Audit found no problems — all citations passed."
        return result

    # Sequential per-section Opus calls (each is one focused analysis).
    fixes_async = asyncio.run(_run_all_sections(cli, project, problematic))

    for section, (section_fixes, section_summary) in zip(problematic, fixes_async):
        result.fixes.extend(section_fixes)
        result.per_section_summaries[section.section_id] = section_summary

    # Overall summary (Opus call across all section summaries)
    if result.per_section_summaries:
        synth = asyncio.run(_synthesize_summary(cli, result.per_section_summaries))
        result.summary = synth

    # Persist fix list as JSON for downstream NotebookLM correction
    out_path = project.state_dir() / "citation_fixes.json"
    out_path.write_text(
        json.dumps(
            [
                {
                    "section_id": f.section_id,
                    "paragraph_tag": f.paragraph_tag,
                    "original_sentence": f.original_sentence,
                    "cited_as": f.cited_as,
                    "flag": f.flag,
                    "correction_hint": f.correction_hint,
                }
                for f in result.fixes
            ],
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return result


async def _run_all_sections(
    cli: ClaudeCLI, project: ThesisProject, sections: list[SectionReport]
) -> list[tuple[list[CitationFix], str]]:
    return list(await asyncio.gather(*(_orchestrate_section(cli, s) for s in sections)))


async def _orchestrate_section(
    cli: ClaudeCLI, section: SectionReport
) -> tuple[list[CitationFix], str]:
    """Read one Haiku report, ask Opus to extract structured fixes + a per-section summary."""
    prompt = _ORCH_PROMPT.format(
        section_id=section.section_id,
        report=section.report_text[:50_000],  # cap so very long reports don't blow context
    )
    resp = await cli.complete(
        model="opus",
        system=_ORCH_SYSTEM,
        user=prompt,
        timeout=600,
    )
    fixes = _parse_opus_fixes(resp.text, section_id=section.section_id)
    summary_m = re.search(
        r"##?\s*SUMMARY\s*\n+(.+?)(?=\n##|\n\Z|\Z)",
        resp.text,
        re.DOTALL | re.IGNORECASE,
    )
    summary = summary_m.group(1).strip() if summary_m else ""
    return fixes, summary


async def _synthesize_summary(cli: ClaudeCLI, per_section: dict[str, str]) -> str:
    """One last Opus call to produce a thesis-wide executive summary."""
    body = "\n\n".join(f"### {k}\n{v}" for k, v in per_section.items())
    prompt = (
        "Otrzymałeś podsumowania problemów z cytowaniami z wielu podrozdziałów pracy licencjackiej.\n"
        "Stwórz spójne podsumowanie wykonawcze (max 250 słów):\n"
        " - jakie WZORCE błędów się powtarzają (np. wszystkie cytaty Heilman mają zły rok)\n"
        " - jakie 3 NAJWAŻNIEJSZE klasy fixów uderzą po wszystkich rozdziałach\n"
        " - jaka byłaby kolejność: co poprawić najpierw, co później\n\n"
        f"PODSUMOWANIA PER SEKCJA:\n\n{body}"
    )
    resp = await cli.complete(model="opus", user=prompt, timeout=300)
    return resp.text.strip()


# ---------------------------------------------------------------- Prompts


_ORCH_SYSTEM = """Jesteś orkiestratorem audytu cytowań w pracy licencjackiej.
Czytasz raport jednego sub-agenta (Haiku) o jednej sekcji.
Twoje zadanie: wyciągnąć WSZYSTKIE problematyczne cytowania (status różny od ✅)
i zaproponować konkretne POPRAWKI do wysłania do NotebookLM w drugim przejściu.

Nie wymyślasz nowych źródeł. Jeśli Haiku zaproponował konkretną poprawkę — przepisz ją.
Jeśli nie — zaznacz że potrzeba decyzji człowieka (\"WYMAGA DECYZJI\").

Mów po polsku jeśli raport jest po polsku, po angielsku jeśli po angielsku.
"""


_ORCH_PROMPT = """RAPORT SUB-AGENTA HAIKU DLA SEKCJI {section_id}:

```
{report}
```

ZADANIE:

1. Wypisz KAŻDE problematyczne cytowanie w formacie:

#### FIX
PARAGRAPH_TAG: P0XXX
ORIGINAL_SENTENCE: "<dosłowne zdanie z pracy lub pierwsze 200 znaków akapitu jeśli nie ma cytatu w cudzysłowie>"
CITED_AS: "<jak jest cytowane w pracy, np. (Hoch, 2002, s. 137)>"
FLAG: ⚠️ STRONA | ❌ TREŚĆ | 🔴 BIBLIOGRAFIA | ❓ BRAK ŹRÓDŁA  (wybierz jedną; może być wiele dla jednego cytatu, oddziel `+`)
CORRECTION_HINT: <konkretna podpowiedź do poprawy: poprawny numer strony, alternatywne źródło z biblioteki, lub "WYMAGA DECYZJI" jeśli sub-agent nie wiedział>

#### FIX
...

(po każdym ## FIX nowa linia, kolejny FIX bezpośrednio po)

2. Na końcu sekcja `## SUMMARY` z 3-5 zdaniami o: jakie KLASY błędów się powtarzają, czy widać systematyczność,
co jest najpilniejsze do poprawy.
"""


def _parse_opus_fixes(text: str, *, section_id: str) -> list[CitationFix]:
    """Parse Opus output into structured CitationFix objects."""
    fixes: list[CitationFix] = []
    for blk in re.split(r"####\s*FIX\b", text)[1:]:
        para_m = re.search(r"PARAGRAPH_TAG\s*:\s*(P\d+)", blk)
        orig_m = re.search(r'ORIGINAL_SENTENCE\s*:\s*"([^"]+)"', blk)
        cited_m = re.search(r'CITED_AS\s*:\s*"?([^"\n]+?)"?\s*\n', blk)
        flag_m = re.search(r"FLAG\s*:\s*(.+)", blk)
        hint_m = re.search(
            r"CORRECTION_HINT\s*:\s*(.+?)(?=\n####|\n##\s|\Z)",
            blk,
            re.DOTALL,
        )
        if not (orig_m and cited_m and flag_m):
            continue
        fixes.append(CitationFix(
            section_id=section_id,
            paragraph_tag=para_m.group(1) if para_m else "P????",
            original_sentence=orig_m.group(1).strip(),
            cited_as=cited_m.group(1).strip(),
            flag=flag_m.group(1).strip(),
            correction_hint=hint_m.group(1).strip() if hint_m else "(brak podpowiedzi)",
        ))
    return fixes
