"""Word document operations — humanization, repair, edit application, formatting."""

from thesis_generator.docx_ops.humanize import HumanizationStats, humanize_docx
from thesis_generator.docx_ops.repair import RepairReport, repair_docx
from thesis_generator.docx_ops.apply_edits import EditApplyResult, apply_edits_from_json

__all__ = [
    "HumanizationStats",
    "humanize_docx",
    "RepairReport",
    "repair_docx",
    "EditApplyResult",
    "apply_edits_from_json",
]
