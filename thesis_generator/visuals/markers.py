"""Marker parser — extracts visual-material directives from draft text.

The writer (or user) drops inline markers in the draft:

    [TABELA 1: title][Źródło: ...][Dane: file.xlsx sheet=H1 cells=B2:F7]
    [WYKRES 1: title][Źródło: ...][Dane: ... ][Typ: bar]
    [ILUSTRACJA 1: title][Źródło: ...][Plik: visuals/foo.png][Szerokość: 12cm]
    [SUGEROWANY WYKRES: title][Opis: ...]

This parser is permissive about whitespace and order of metadata fields, and
tolerates both Polish (Źródło) and English (Source) attribute names so the
writer can be slightly sloppy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator


class VisualKind(str, Enum):
    TABLE = "TABELA"
    CHART = "WYKRES"
    IMAGE = "ILUSTRACJA"
    SUGGESTED = "SUGEROWANY"  # placeholder, needs human/LLM follow-up


@dataclass(slots=True)
class DataSpec:
    """Where to pull the underlying numeric data from."""

    file: str  # relative path under project root
    sheet: str | None = None
    cells: str | None = None  # e.g. "B2:F7"
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class VisualMarker:
    kind: VisualKind
    declared_number: int | None  # the N in "TABELA N" if writer numbered it; None for SUGGESTED
    title: str
    source: str | None = None
    description: str | None = None  # `[Opis: ...]` field
    data: DataSpec | None = None
    file: str | None = None  # for ILUSTRACJA
    width_cm: float | None = None
    chart_type: str | None = None  # "bar" / "line" / "pie" / "scatter" — for WYKRES
    raw_text: str = ""  # original substring in the draft (for removal/replacement)

    @property
    def is_suggestion(self) -> bool:
        return self.kind == VisualKind.SUGGESTED


# Matches one outer marker bracket. The opening label is one of TABELA / WYKRES /
# ILUSTRACJA / SUGEROWANY (followed by optional WYKRES/TABELA/ILUSTRACJA word
# for "SUGEROWANY WYKRES" etc.), then optional number, then `:` and the title.
_OPENING_RE = re.compile(
    r"\[\s*"
    r"(TABELA|WYKRES|ILUSTRACJA|SUGEROWANY(?:\s+(?:WYKRES|TABELA|ILUSTRACJA))?)\s*"
    r"(\d+)?"
    r"\s*:\s*"
    r"([^\]]+?)"
    r"\s*\]",
    re.UNICODE | re.IGNORECASE,
)

# Metadata bracket pairs that may follow the opening marker, in any order.
# Examples: [Źródło: ...] [Source: ...] [Dane: ...] [Data: ...] [Plik: ...]
# [File: ...] [Szerokość: 12cm] [Width: 12cm] [Typ: bar] [Type: bar]
# [Opis: ...] [Description: ...]
_META_KEYS = {
    "źródło": "source",
    "source": "source",
    "dane": "data",
    "data": "data",
    "plik": "file",
    "file": "file",
    "szerokość": "width",
    "width": "width",
    "typ": "chart_type",
    "type": "chart_type",
    "opis": "description",
    "description": "description",
}
_META_RE = re.compile(
    r"\[\s*(" + "|".join(_META_KEYS.keys()) + r")\s*:\s*([^\]]+?)\s*\]",
    re.UNICODE | re.IGNORECASE,
)


def _parse_data_spec(raw: str) -> DataSpec:
    """Parse a `[Dane: ...]` payload.

    Accepts forms like:
        file.xlsx sheet=H1 cells=B2:F7
        file.xlsx sheet="Sampling H1" cells=A1:C20
        file.xlsx sheet=H1 cells=B2:F7 some_extra=value
    """
    parts = re.findall(r'(\w+)\s*=\s*"([^"]+)"|(\w+)\s*=\s*(\S+)', raw)
    # parts is a list of tuples (k1, v1, k2, v2) — exactly one of each pair populated
    kv: dict[str, str] = {}
    for k1, v1, k2, v2 in parts:
        key = (k1 or k2).lower()
        val = v1 or v2
        kv[key] = val

    # The path is whatever isn't matched as key=value (i.e. leading file path)
    # Strip the known k=v segments off the raw string to recover the file path.
    file_part = re.sub(r'(\w+)\s*=\s*("[^"]+"|\S+)', "", raw).strip()

    return DataSpec(
        file=file_part,
        sheet=kv.pop("sheet", None),
        cells=kv.pop("cells", None),
        extra=kv,
    )


def _parse_width(raw: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*cm?", raw, re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_markers(text: str) -> list[VisualMarker]:
    """Walk `text` and yield every visual marker found.

    Each marker spans an opening bracket + any contiguous metadata brackets that
    follow it (separated only by whitespace / newlines).
    """
    out: list[VisualMarker] = []
    for m in _OPENING_RE.finditer(text):
        kind_str = m.group(1).upper().strip()
        if kind_str.startswith("SUGEROWANY"):
            kind = VisualKind.SUGGESTED
        else:
            kind = VisualKind(kind_str)

        declared_num = int(m.group(2)) if m.group(2) else None
        title = m.group(3).strip()

        # Grab any metadata brackets immediately following the opening one.
        cursor = m.end()
        meta: dict[str, str] = {}
        full_raw = m.group(0)
        while cursor < len(text):
            # allow whitespace/newlines between brackets
            tail = text[cursor:cursor + 200]
            ws = re.match(r"\s*", tail)
            ws_len = ws.end() if ws else 0
            mm = _META_RE.match(text, cursor + ws_len)
            if not mm:
                break
            key = _META_KEYS[mm.group(1).lower()]
            meta[key] = mm.group(2).strip()
            full_raw = text[m.start():mm.end()]
            cursor = mm.end()

        marker = VisualMarker(
            kind=kind,
            declared_number=declared_num,
            title=title,
            source=meta.get("source"),
            description=meta.get("description"),
            file=meta.get("file"),
            width_cm=_parse_width(meta["width"]) if "width" in meta else None,
            chart_type=meta.get("chart_type"),
            data=_parse_data_spec(meta["data"]) if "data" in meta else None,
            raw_text=full_raw,
        )
        out.append(marker)
    return out


def strip_markers(text: str, markers: list[VisualMarker]) -> str:
    """Remove every marker's raw text from the source string."""
    out = text
    for m in markers:
        if m.raw_text and m.raw_text in out:
            out = out.replace(m.raw_text, "", 1)
    # Collapse any double-spaces left behind
    out = re.sub(r"\s{3,}", "\n\n", out)
    return out
