"""NotebookLM as the PRIMARY writer — step-by-step subchapter generation.

This is the architectural shift: instead of Claude writing and NotebookLM
verifying (the old approach), NotebookLM WRITES (because it's source-grounded
from the moment it starts) and the Haiku swarm + Opus orchestrator verify the
citations and page numbers — NotebookLM's known weak spot.

The user must configure NotebookLM with the system prompt in
`docs/notebooklm_system_prompt.pl.pdf` so it produces APA-cited prose, NOT
random conversational answers. See README for the one-time setup.

Each `write_section` call sends ONE focused prompt describing the subsection
and returns ~6,000 chars of polished, source-grounded text + a per-section
bibliography. Sequential by design — the user wants to review each subsection
before the next starts (matches the proven session's pattern).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.notebooklm.adapter import NotebookLMAdapter, NotebookLMError


@dataclass(slots=True)
class NotebookSectionSpec:
    """What to ask NotebookLM to write for one subsection."""

    id: str                                    # "1.2.3"
    title: str                                 # "Marketing szeptany online"
    focus: str                                 # 2-5 sentences describing scope
    priority_sources: list[str] = field(default_factory=list)  # author-year refs to prioritize
    target_chars: int = 6000                   # NotebookLM tends to land at this range
    language: str = "pl"


@dataclass(slots=True)
class NotebookSectionDraft:
    spec: NotebookSectionSpec
    body: str                                  # the prose, with inline (Author, year, s. X) citations
    bibliography: list[str]                    # APA-formatted entries
    raw_response: str                          # full NotebookLM response
    truncated: bool = False                    # set if body length was clearly cut


def build_writer_prompt(spec: NotebookSectionSpec, *, additional_context: str = "") -> str:
    """The prompt sent to NotebookLM. Mirrors the user's proven system-prompt PDF.

    The PDF establishes the GLOBAL behavior (style, citation rules, forbidden
    phrases, structure). This per-call prompt just supplies the specifics:
    section number, title, scope, length, priority sources.
    """
    prio = ""
    if spec.priority_sources:
        prio = "\nPriorytetowe źródła do tego podrozdziału:\n" + "\n".join(
            f"  - {s}" for s in spec.priority_sources
        )

    extra = f"\n\nDodatkowy kontekst:\n{additional_context}" if additional_context else ""

    return f"""Napisz podrozdział pracy licencjackiej.

Numer i tytuł: **{spec.id} {spec.title}**

Zakres / na co się skupić:
{spec.focus}

Cel długości: ~{spec.target_chars} znaków ze spacjami (akceptowalny zakres ±20%).{prio}{extra}

Wymagania (przypomnienie do systemowego promptu konfiguracji):
- Każde twierdzenie z cytowaniem APA 7 — format `(Autor, rok, s. XX)`.
- Wprowadzaj autorów do tekstu: „Kahneman zauważył...", „Według Hocha...".
- Bez fraz meta typu „w niniejszym podrozdziale", „poniżej przedstawiono".
- Bez em-dashy ` — `; długie zdania są OK, em-dashy NIE.
- Po treści, sekcja **Bibliografia wykorzystana w podrozdziale** z pełnymi wpisami APA 7.
- Jeśli źródło nie pokrywa jakiegoś aspektu — DODAJ na końcu blok `UWAGA:` z listą luk; nie zmyślaj.
"""


def parse_notebook_response(raw: str) -> tuple[str, list[str], bool]:
    """Split NotebookLM response into (body, bibliography_entries, truncated_flag).

    Looks for the `Bibliografia wykorzystana w podrozdziale` heading and treats
    everything after as the bibliography. Each non-empty line in the
    bibliography section becomes one entry.
    """
    truncated = False
    # NotebookLM sometimes wraps responses in markers; trim them.
    text = raw.strip()

    # Heuristic for truncation: trailing word without sentence terminator.
    if text and text[-1] not in ".!?\")]}":
        truncated = True

    m = re.search(
        r"^#{0,3}\s*Bibliografia[^\n]*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    )
    if not m:
        return text, [], truncated

    body = text[: m.start()].rstrip()
    bib_block = text[m.end():].strip()
    # Split bibliography into entries by paragraph (one entry per non-empty line/paragraph)
    entries = [line.strip() for line in re.split(r"\n\s*\n|\n(?=[A-ZŁŚŻŹĆ])", bib_block) if line.strip()]
    # Drop any leading "===" or "----" lines
    entries = [e for e in entries if not re.match(r"^[=\-_*]{3,}\s*$", e)]
    return body, entries, truncated


def write_section(
    adapter: NotebookLMAdapter,
    spec: NotebookSectionSpec,
    *,
    additional_context: str = "",
) -> NotebookSectionDraft:
    """Send ONE prompt to NotebookLM and return a structured draft.

    Raises NotebookLMError if the skill returns an error or auth fails.
    """
    prompt = build_writer_prompt(spec, additional_context=additional_context)
    raw = adapter.ask(prompt)
    body, bib, trunc = parse_notebook_response(raw)
    return NotebookSectionDraft(
        spec=spec,
        body=body,
        bibliography=bib,
        raw_response=raw,
        truncated=trunc,
    )
