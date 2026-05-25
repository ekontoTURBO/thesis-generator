"""Numbers audit — dedicated Opus agents for independent recomputation + hypothesis consistency.

The proven session (May 2026 thesis) caught 5/75 numbers as off-by-N or
approximations (e.g. "6 respondentów" → actually 4; "65% kolejny headset" →
actually ~34%). The pattern was: Opus opens raw xlsx, computes statistics
from scratch, writes results to a parallel workbook, then diffs against
what the draft claims.

This package productizes that pattern:

  1. `recomputer.py` — Opus agent with Bash + Read tools, dispatched via
     `claude -p`. Reads raw research-data files, writes its own Python script
     to compute every statistic claimed in the draft (M, %, χ², t, p, d,
     V Craméra, Pearson r, distributions), runs it, saves an XLSX with the
     parallel calculations, and produces a markdown diff.

  2. `consistency.py` — second Opus call that reads the methodology section
     (hypotheses) + the results section (claimed support/rejection of H1/H2/H3)
     + the recomputed numbers, and judges per-hypothesis: SUPPORTED /
     NOT_SUPPORTED / PARTIALLY / OVER_INTERPRETED.

  3. `extractor.py` — pulls numeric claims (with context) and hypothesis
     statements out of the draft so we can feed Opus only what it needs.
"""

from thesis_generator.numbers_audit.recomputer import (
    NumericRecomputeResult,
    run_recompute,
)
from thesis_generator.numbers_audit.consistency import (
    HypothesisVerdict,
    HypothesisConsistencyResult,
    check_hypothesis_consistency,
)
from thesis_generator.numbers_audit.extractor import (
    NumericClaim,
    HypothesisStatement,
    extract_numeric_claims,
    extract_hypotheses,
)

__all__ = [
    "NumericRecomputeResult",
    "run_recompute",
    "HypothesisVerdict",
    "HypothesisConsistencyResult",
    "check_hypothesis_consistency",
    "NumericClaim",
    "HypothesisStatement",
    "extract_numeric_claims",
    "extract_hypotheses",
]
