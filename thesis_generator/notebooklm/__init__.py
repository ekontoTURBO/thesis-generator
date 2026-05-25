"""NotebookLM adapter — the source-grounded verification engine (Ring C).

Wraps the **NotebookLM Claude Code Skill** by [Please Prompto!]
(https://github.com/PleasePrompto/notebooklm-skill) — MIT, 2025. We do NOT
reimplement NotebookLM access; we shell out to their `scripts/run.py
ask_question.py --question "..." --notebook-url "..."` interface. All
browser automation, persistent auth, library management, and Gemini query
plumbing is theirs. This module is a thin orchestration layer that calls
their CLI, parses the response, and integrates verdicts into our pipeline.

If you find Ring C catches a hallucination Ring B missed, that catch belongs
to Please Prompto's skill. Star their repo.

The skill drives a headless browser session, asks Gemini one question at a
time, and returns a source-grounded answer with citations. This is the kingpin
of the verification pipeline because it sees the *whole* library at once —
catching hallucinations that per-source Haiku verification misses (e.g. "the
cited PDF exists but the claim isn't in it").
"""

from thesis_generator.notebooklm.adapter import (
    NotebookLMAdapter,
    NotebookLMError,
    VerificationVerdict,
    VerificationResult,
)
from thesis_generator.notebooklm.writer import (
    NotebookSectionDraft,
    NotebookSectionSpec,
    build_writer_prompt,
    parse_notebook_response,
    write_section,
)
from thesis_generator.notebooklm.correction import (
    CitationFix,
    CorrectionResult,
    build_correction_prompt,
    parse_corrections,
    request_corrections,
)

__all__ = [
    "NotebookLMAdapter",
    "NotebookLMError",
    "VerificationVerdict",
    "VerificationResult",
    # Writer
    "NotebookSectionDraft",
    "NotebookSectionSpec",
    "build_writer_prompt",
    "parse_notebook_response",
    "write_section",
    # Correction
    "CitationFix",
    "CorrectionResult",
    "build_correction_prompt",
    "parse_corrections",
    "request_corrections",
]
