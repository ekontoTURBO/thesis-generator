"""Visual materials — tables, charts, illustrations + numbering register.

Lifted directly from the user's proven workflow (system prompt PDF for
NotebookLM + the `generate_charts.py`, `insert_v75_images.py`, and
`uniform_tables.py` scripts from the May 2026 thesis session).

The writer inserts inline markers in the draft text. This package parses them,
builds or inserts the corresponding artifact, applies the proven style, and
maintains a numbering register that drives the Spis tabel / Spis rysunków
generated at the end.

Marker syntax (parsed by `markers.py`):

    [TABELA 1: Porównanie technik sprzedażowych w VR]
    [Źródło: Smith, 2021, s. 67]
    [Dane: research_data/surveys/sales.xlsx sheet=H1 cells=B2:F7]

    [WYKRES 1: Wzrost sprzedaży VR 2018-2023]
    [Źródło: opracowanie własne na podstawie (Anderson, 2022, s. 45)]
    [Dane: research_data/surveys/sales.xlsx sheet="Wzrost" cells=A1:B6]
    [Typ: line]

    [ILUSTRACJA 1: Sensorama (1962)]
    [Źródło: Wikimedia Commons, domena publiczna]
    [Plik: visuals/sensorama.jpg]
    [Szerokość: 11cm]

    [SUGEROWANY WYKRES: tytuł]              # placeholder, requires manual spec
    [Opis: ...]
"""

from thesis_generator.visuals.markers import VisualKind, VisualMarker, parse_markers
from thesis_generator.visuals.registry import VisualsRegistry
from thesis_generator.visuals.pipeline import process_visuals, VisualsResult

__all__ = [
    "VisualKind",
    "VisualMarker",
    "VisualsRegistry",
    "VisualsResult",
    "parse_markers",
    "process_visuals",
]
