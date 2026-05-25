"""Numbering register + Spis tabel / Spis rysunków generation.

Visual materials in a Polish bachelor's thesis are numbered globally (Tabela 1,
Tabela 2, ... or per-chapter Tabela 1.1, 1.2). The proven session used global
numbering with the caption format:

    Tabela N. Tytuł
    Źródło: ...

    Rysunek N. Tytuł
    Źródło: ...

The registry assigns numbers in document order (the order markers appear when
reading top-to-bottom) so cross-references work even when the writer drops
markers with `declared_number` mismatched against the final order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from thesis_generator.visuals.markers import VisualKind, VisualMarker


@dataclass(slots=True)
class VisualEntry:
    kind: VisualKind
    number: int  # final assigned number (1-based, per kind)
    title: str
    source: str | None
    raw_text: str  # original marker substring in the draft
    image_path: str | None = None  # absolute path to generated/located file (for charts/images)
    paragraph_index: int | None = None  # where in the draft it lives

    @property
    def caption(self) -> str:
        # The labels match what the proven session used: "Tabela N. Title" / "Rysunek N. Title".
        # ILUSTRACJA shares the "Rysunek" prefix with WYKRES because both are figure-like.
        label = {
            VisualKind.TABLE: "Tabela",
            VisualKind.CHART: "Rysunek",
            VisualKind.IMAGE: "Rysunek",
            VisualKind.SUGGESTED: "(sugerowane)",
        }[self.kind]
        return f"{label} {self.number}. {self.title}"

    @property
    def source_line(self) -> str:
        return f"Źródło: {self.source}" if self.source else "Źródło: opracowanie własne."


class VisualsRegistry:
    """Owns the numbering scheme. Builds Spis tabel / Spis rysunków."""

    def __init__(self) -> None:
        self.tables: list[VisualEntry] = []
        self.figures: list[VisualEntry] = []
        # WYKRES + ILUSTRACJA share the figures sequence (proven session convention).
        self.suggestions: list[VisualEntry] = []

    def assign(self, markers: Sequence[VisualMarker]) -> list[VisualEntry]:
        """Walk markers in document order, assign final numbers."""
        entries: list[VisualEntry] = []
        t_count = f_count = s_count = 0
        for m in markers:
            if m.kind == VisualKind.TABLE:
                t_count += 1
                num = t_count
            elif m.kind in (VisualKind.CHART, VisualKind.IMAGE):
                f_count += 1
                num = f_count
            else:  # SUGGESTED
                s_count += 1
                num = s_count
            entry = VisualEntry(
                kind=m.kind,
                number=num,
                title=m.title,
                source=m.source,
                raw_text=m.raw_text,
            )
            if m.file:
                entry.image_path = m.file
            entries.append(entry)
            if m.kind == VisualKind.TABLE:
                self.tables.append(entry)
            elif m.kind in (VisualKind.CHART, VisualKind.IMAGE):
                self.figures.append(entry)
            else:
                self.suggestions.append(entry)
        return entries

    # ---- Spisy / index pages ----

    def render_spis_tabel(self) -> str:
        if not self.tables:
            return ""
        lines = ["Spis tabel"]
        for e in self.tables:
            lines.append(f"Tabela {e.number}. {e.title}")
        return "\n".join(lines)

    def render_spis_rysunkow(self) -> str:
        if not self.figures:
            return ""
        lines = ["Spis rysunków"]
        for e in self.figures:
            lines.append(f"Rysunek {e.number}. {e.title}")
        return "\n".join(lines)

    def render_full_report(self) -> str:
        """Markdown summary for the `_reports/visuals.md` file."""
        out = ["# Visual materials register\n"]
        out.append(f"- tables: {len(self.tables)}")
        out.append(f"- figures (charts + images): {len(self.figures)}")
        out.append(f"- suggested visuals (need spec): {len(self.suggestions)}\n")

        if self.tables:
            out.append("## Tables\n| # | Title | Source |\n|---|---|---|")
            for e in self.tables:
                out.append(f"| {e.number} | {e.title} | {e.source or '—'} |")

        if self.figures:
            out.append("\n## Figures\n| # | Kind | Title | Source |\n|---|---|---|---|")
            for e in self.figures:
                out.append(f"| {e.number} | {e.kind.value} | {e.title} | {e.source or '—'} |")

        if self.suggestions:
            out.append("\n## Suggested (need human decision)\n")
            for e in self.suggestions:
                out.append(f"- _{e.title}_ — fill in `[Dane: ...]` and re-run `tg visuals`")
        return "\n".join(out)
