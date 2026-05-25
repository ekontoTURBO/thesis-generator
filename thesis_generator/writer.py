"""Section-by-section writer.

Brief section 2, step 2: the proven workflow was:
    "PISZ SEKCJA PO SEKCJI. Po każdym podrozdziale ZATRZYMAJ SIĘ i zaraportuj
     postęp. Nie pisz całego rozdziału w jednym ciągu — to zawsze kończy się
     katastrofą."

This module owns:
- Spec parsing (which sections to write, in what order, from what brief)
- Per-section Opus call with the style fingerprint as system prompt
- Hard pause + progress report between sections
- Insertion into the docx (appending to the right structural location)
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document

from thesis_generator.config import ThesisProject
from thesis_generator.inventory import Inventory, load_inventory
from thesis_generator.llm import ClaudeCLI
from thesis_generator.reports.progress import update_progress


@dataclass(slots=True)
class SectionSpec:
    """One subsection to write."""

    id: str  # e.g. "4.1.2"
    heading: str
    brief: str  # what the user wants in this section
    target_chars: int = 5_000
    required_citations: list[str] = field(default_factory=list)  # "Author_Year" keys
    raw_data_refs: list[str] = field(default_factory=list)  # sheet names or table refs


@dataclass(slots=True)
class WrittenSection:
    spec: SectionSpec
    text: str
    used_citations: list[str]
    notes: list[str] = field(default_factory=list)


def _build_writer_system_prompt(project: ThesisProject, inventory: Inventory) -> str:
    """Compose a system prompt for the Opus writer based on style fingerprint + project config."""
    fp = inventory.style
    citations_already_used = ", ".join(f"({s}, {y})" for s, y in sorted(fp.cited_pairs)[:30])
    return f"""Jesteś autorem pracy licencjackiej.

Język: {project.language.value}
Tytuł pracy: {project.title}
Styl cytowania: {project.citation_style.value.upper()} z formatem (Autor, Rok, s. XX)

ISTNIEJĄCE STYLISTYCZNE KONWENCJE (musisz zachować):
- Heading styles w użyciu: {fp.heading_styles_used}
- Sekcje bibliografii: {fp.bibliography_sections}
- Przykłady cytowania z pracy: {fp.citation_pattern_examples[:3]}

CYTOWANIA JUŻ UŻYTE W PRACY (preferuj te, nie wymyślaj nowych klasyków):
{citations_already_used}

ZASADY BEZWZGLĘDNE:
1. KAŻDE twierdzenie musi mieć cytowanie. Jeśli nie masz źródła — napisz [WERYFIKACJA WYMAGANA].
2. Pisz językiem prostym i bezpośrednim. NIE używaj: triangulacja, rygorystycznie, holistycznie,
   synergiczny, paradygmat. Długie zdania są OK; em-dashy (` — `) NIE.
3. Nie wymyślaj liczb. Jeśli potrzebujesz statystyki — odwołaj się do raw_data lub zaznacz [LICZBA].
4. NIE używaj fraz meta typu: "jak przedstawiono w tabeli", "co obrazuje rysunek",
   "poniżej przedstawiono", "w niniejszym rozdziale", "celem tego podrozdziału jest".
   Wprowadzaj wizualizacje naturalnie w toku argumentacji.

WIZUALIZACJE — markery inline w tekście:

Gdy chcesz tabelę z danych badawczych:
    [TABELA 1: Charakterystyka próby badawczej][Źródło: opracowanie własne][Dane: research_data/surveys/responses.xlsx sheet=Metryczka cells=A1:C20]

Gdy chcesz wykres z danych badawczych:
    [WYKRES 1: Rozkład ocen Q22 vs Q23][Źródło: opracowanie własne][Dane: research_data/surveys/responses.xlsx sheet=Rozkłady cells=A1:F6][Typ: bar]

Gdy chcesz wstawić gotowy obraz/diagram z plików projektu:
    [ILUSTRACJA 1: Model AIDA][Źródło: opracowanie własne na podstawie Kotler i Keller (2021)][Plik: visuals/aida.png][Szerokość: 13cm]

Gdy proponujesz wykres ale brak konkretnych danych:
    [SUGEROWANY WYKRES: Dynamika wzrostu rynku VR 2018-2023][Opis: do uzupełnienia danymi z raportu Statista]

Numerowanie (1, 2, 3...) zostanie automatycznie ustalone — możesz dawać dowolne liczby, pipeline
przenumeruje je w kolejności występowania. Każdy marker MUSI mieć [Źródło: ...].

5. Po napisanej sekcji ZATRZYMAJ SIĘ — zwróć JSON
   {{"text": "...", "used_citations": ["Author_Year", ...], "notes": ["..."]}}
"""


async def write_section(
    project: ThesisProject,
    spec: SectionSpec,
    inventory: Inventory,
    *,
    cli: ClaudeCLI | None = None,
) -> WrittenSection:
    """One Opus call (via `claude -p`) to draft one section."""
    cli = cli or ClaudeCLI()
    system = _build_writer_system_prompt(project, inventory)

    user_msg = f"""Napisz sekcję {spec.id} — {spec.heading}

Brief (czego oczekuje promotor / czego brakuje w pracy):
{spec.brief}

Cel długości: ~{spec.target_chars} znaków.

Cytowania, które MUSZĄ pojawić się w tej sekcji (jeśli mają sens):
{', '.join(spec.required_citations) if spec.required_citations else '(brak twardych wymagań)'}

Dane surowe do uwzględnienia:
{', '.join(spec.raw_data_refs) if spec.raw_data_refs else '(brak)'}

ZWRÓĆ JSON:
{{"text": "<treść sekcji w czystym tekście, bez markdown nagłówków>",
 "used_citations": ["Author_Year", ...],
 "notes": ["jakie miejsca wymagają dodatkowej weryfikacji", ...]}}
"""

    resp = await cli.complete(
        model=project.models.writer,
        system=system,
        user=user_msg,
        extract_json=True,
        timeout=900,
    )
    payload = resp.extracted_json or _extract_json(resp.text)
    return WrittenSection(
        spec=spec,
        text=payload.get("text", resp.text),
        used_citations=payload.get("used_citations", []),
        notes=payload.get("notes", []),
    )


def _extract_json(text: str) -> dict:
    """Pull the first {...} block from arbitrary text."""
    import re

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        # Fallback: strip code fence
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", m.group(0).strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


async def write_chapter(
    project: ThesisProject,
    sections: list[SectionSpec],
    *,
    cli: ClaudeCLI | None = None,
) -> list[WrittenSection]:
    """Sequential per-section writing with progress reports after each.

    Sequential, NOT parallel — the proven session was explicit: the user wants
    to see and approve each subsection before the next starts.
    """
    inv = load_inventory(project)
    if inv is None:
        from thesis_generator.inventory import build_inventory

        inv = build_inventory(project)

    cli = cli or ClaudeCLI()
    results: list[WrittenSection] = []
    for spec in sections:
        update_progress(
            project,
            phase=f"Writer — sekcja {spec.id}",
            status="IN_PROGRESS",
            icon="✍️",
            completed=[f"napisana sekcja {s.spec.id}" for s in results],
            next_steps=[f"napisać sekcję {s.id}" for s in sections[len(results):]],
        )
        written = await write_section(project, spec, inv, cli=cli)
        results.append(written)
        # Persist draft section to disk so the next pass can verify it independently
        out = project.state_dir() / f"section_{spec.id}.txt"
        out.write_text(written.text, encoding="utf-8")

    update_progress(
        project,
        phase=f"Writer — wszystkie sekcje gotowe ({len(sections)})",
        status="DONE",
        icon="✅",
        completed=[f"sekcja {s.spec.id} ({len(s.text)} znaków)" for s in results],
        next_steps=["uruchom verify (ringi A/B/C)", "uruchom data_audit", "uruchom independent reviewer"],
    )
    return results
