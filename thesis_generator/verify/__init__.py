"""The three-ring verification system."""

from thesis_generator.verify.internal import RingAResult, run_ring_a
from thesis_generator.verify.haiku_per_source import RingBResult, run_ring_b
from thesis_generator.verify.notebooklm_ring import RingCResult, run_ring_c
from thesis_generator.verify.data_audit import DataAuditResult, run_data_audit

__all__ = [
    "RingAResult",
    "RingBResult",
    "RingCResult",
    "DataAuditResult",
    "run_ring_a",
    "run_ring_b",
    "run_ring_c",
    "run_data_audit",
]
