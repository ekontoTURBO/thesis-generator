"""Chart generation — matplotlib with the proven session's style palette.

Lifted directly from `C:/tmp/generate_charts.py` of the proven session:
- Navy + gray + accent-orange palette
- Serif font, 11 pt, 200 DPI
- No top/right spines, light grid
- Bar charts with value labels on top

Charts are saved to `output/_charts/` so they survive across pipeline reruns
and the user can inspect them outside the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import openpyxl

# Lazy matplotlib import — heavy package, only load when actually generating.
_matplotlib_ready = False


def _ensure_matplotlib_ready() -> None:
    global _matplotlib_ready
    if _matplotlib_ready:
        return
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "serif",
        "font.size": 11,
        "figure.dpi": 200,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.15,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "axes.axisbelow": True,
    })
    _matplotlib_ready = True


# Proven palette
NAVY = "#1E3A5F"
GRAY = "#6B7280"
ACCENT = "#E07B39"


@dataclass(slots=True)
class ChartData:
    """A flat representation of what the chart should plot."""

    title: str
    x_labels: list[str]
    series: list[tuple[str, list[float]]]  # (name, values) per series
    y_label: str = ""
    chart_type: str = "bar"  # bar | line | scatter | pie
    show_value_labels: bool = True


def load_chart_data_from_xlsx(
    file: Path, sheet: str, cells: str, *, has_header_row: bool = True
) -> ChartData:
    """Read a rectangular range from xlsx → ChartData.

    Layout assumed (the conventional one for survey results):
        row 1 = header (first column blank or empty, then series names)
        col 1 = x labels
        col 2..N = series values

    Example: range B2:E7 with header at B1:E1 and labels in A2:A7.
    """
    wb = openpyxl.load_workbook(str(file), data_only=True, read_only=True)
    ws = wb[sheet]
    rng = list(ws[cells])
    if not rng:
        wb.close()
        return ChartData(title="(empty range)", x_labels=[], series=[])

    headers: list[str] = []
    if has_header_row:
        # Headers = first row of the range, skip first cell (x-label column header)
        first_row = rng[0]
        headers = [str(c.value or f"S{i+1}") for i, c in enumerate(first_row[1:])]
        body_rows = rng[1:]
    else:
        headers = [f"S{i+1}" for i in range(len(rng[0]) - 1)]
        body_rows = rng

    x_labels: list[str] = []
    series_values: list[list[float]] = [[] for _ in headers]
    for row in body_rows:
        if not row:
            continue
        x_labels.append(str(row[0].value) if row[0].value is not None else "")
        for i, cell in enumerate(row[1:]):
            try:
                series_values[i].append(float(cell.value) if cell.value is not None else 0.0)
            except (TypeError, ValueError):
                series_values[i].append(0.0)
    wb.close()

    return ChartData(
        title="",
        x_labels=x_labels,
        series=list(zip(headers, series_values)),
    )


def render_chart(data: ChartData, output_path: Path, *, title: str | None = None) -> Path:
    """Render a ChartData to PNG at `output_path`. Returns the same path."""
    _ensure_matplotlib_ready()
    import matplotlib.pyplot as plt
    import numpy as np

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    palette = [NAVY, ACCENT, GRAY]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))

    chart_type = (data.chart_type or "bar").lower()
    n_series = len(data.series)
    x = np.arange(len(data.x_labels))

    if chart_type == "bar":
        if n_series <= 1:
            name, values = data.series[0] if data.series else ("", [])
            bars = ax.bar(x, values, color=NAVY, label=name)
            if data.show_value_labels:
                for b, v in zip(bars, values):
                    ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}",
                            ha="center", va="bottom", fontsize=9)
        else:
            width = 0.8 / n_series
            for i, (name, values) in enumerate(data.series):
                offset = (i - (n_series - 1) / 2) * width
                bars = ax.bar(x + offset, values, width, label=name, color=palette[i % len(palette)])
                if data.show_value_labels:
                    for b, v in zip(bars, values):
                        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}",
                                ha="center", va="bottom", fontsize=9)
        ax.set_xticks(x)
        ax.set_xticklabels(data.x_labels)

    elif chart_type == "line":
        for i, (name, values) in enumerate(data.series):
            ax.plot(data.x_labels, values, marker="o", label=name, color=palette[i % len(palette)])

    elif chart_type == "scatter":
        for i, (name, values) in enumerate(data.series):
            ax.scatter(data.x_labels, values, label=name, color=palette[i % len(palette)])

    elif chart_type == "pie":
        # For pie, take the first series and ignore the rest.
        name, values = data.series[0] if data.series else ("", [])
        ax.pie(values, labels=data.x_labels, autopct="%1.1f%%",
               colors=[NAVY, ACCENT, GRAY, "#9CA3AF", "#1F2937"][: len(values)])
        ax.axis("equal")

    else:
        raise ValueError(f"Unsupported chart type: {chart_type}")

    if data.y_label and chart_type not in ("pie",):
        ax.set_ylabel(data.y_label)
    if title or data.title:
        ax.set_title(title or data.title, loc="left", pad=10)
    if n_series > 0 and chart_type != "pie":
        ax.legend(loc="upper right", frameon=False)

    plt.savefig(str(output_path))
    plt.close(fig)
    return output_path
