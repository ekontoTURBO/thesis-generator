"""Citation audit — wraps Eryk Czekalski's `thesis-citation-audit` Claude Code skill.

Source: `C:\\Users\\erykc\\.claude\\skills\\thesis-citation-audit\\`

The skill itself performs sentence-by-sentence APA verification of every
citation in a thesis docx against source PDFs, via parallel Haiku sub-agents
(one per subsection). This package shells out to the skill's scripts
(`extract_thesis.py`, `split_sections.py`, `merge_report.py`) and orchestrates
the Haiku swarm via our own `ClaudeCLI` adapter — so the whole thing runs
without ANTHROPIC_API_KEY.

Then `orchestrator.py` runs the second-tier swarm: Opus reads the Haiku
reports section-by-section, asks follow-up questions per problematic citation,
and produces a structured fix list that feeds into the NotebookLM correction
pass.
"""

from thesis_generator.citation_audit.adapter import (
    CitationAuditError,
    CitationAuditResult,
    SectionReport,
    run_citation_audit,
)
from thesis_generator.citation_audit.orchestrator import (
    OpusOrchestratorResult,
    orchestrate_fixes,
)

__all__ = [
    "CitationAuditError",
    "CitationAuditResult",
    "SectionReport",
    "OpusOrchestratorResult",
    "run_citation_audit",
    "orchestrate_fixes",
]
