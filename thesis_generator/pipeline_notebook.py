"""4-step NotebookLM-first pipeline (the NEW primary flow).

This replaces the Claude-writer-first approach. The insight: NotebookLM writes
source-grounded prose better than Claude (it actually reads the library), but
NotebookLM is unreliable on EXACT page numbers and occasionally over-attributes
claims. So:

  Step 1 — NotebookLM writes each subsection step-by-step
           (one focused prompt per subchapter, mirrors the user's system prompt)
  Step 2 — Haiku swarm audits every citation against source PDFs
           (wraps the `thesis-citation-audit` skill; one Haiku per subsection,
            uses pdftotext, checks PDF page vs printed page offset, flags
            ⚠️ STRONA / ❌ TREŚĆ / ❓ BRAK ŹRÓDŁA / 🔴 BIBLIOGRAFIA)
  Step 3 — Opus orchestrator reads every Haiku report and produces a
           structured fix list with correction hints
           (analyst-then-builder pattern; outputs `_state/citation_fixes.json`)
  Step 4 — NotebookLM second pass — correction mode
           (different prompt, focused on the fix list, returns "PRZED → PO"
            replacement sentences with the right pages)

Each step writes its artifacts to disk and can be re-run independently. The
full chain runs via `tg notebook-pipeline`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.citation_audit import (
    CitationAuditResult,
    OpusOrchestratorResult,
    orchestrate_fixes,
    run_citation_audit,
)
from thesis_generator.config import ThesisProject
from thesis_generator.llm import ClaudeCLI
from thesis_generator.notebooklm import (
    CitationFix,
    NotebookLMAdapter,
    NotebookSectionDraft,
    NotebookSectionSpec,
    request_corrections,
    write_section,
)


@dataclass(slots=True)
class NotebookPipelineResult:
    drafts: list[NotebookSectionDraft] = field(default_factory=list)
    audit: CitationAuditResult | None = None
    fixes: OpusOrchestratorResult | None = None
    corrections_by_section: dict[str, str] = field(default_factory=dict)
    artifacts: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def run_notebook_pipeline(
    project: ThesisProject,
    *,
    section_specs: list[NotebookSectionSpec] | None = None,
    skip_steps: tuple[str, ...] = (),
) -> NotebookPipelineResult:
    """Run all 4 steps end-to-end.

    `section_specs` lists what NotebookLM should write. If None, the pipeline
    assumes the user wants to audit-and-fix an EXISTING draft (skips step 1).
    """
    result = NotebookPipelineResult()
    cli = ClaudeCLI(max_concurrent=project.pipeline.max_parallel_haiku)

    if project.notebooklm is None:
        result.notes.append("No notebooklm block in thesis.yaml — only steps 2+3 will run.")
    adapter: NotebookLMAdapter | None = None
    if project.notebooklm is not None:
        adapter = NotebookLMAdapter(
            library_url=project.notebooklm.library_url,
            library_name=project.notebooklm.library_name,
            max_words_per_query=project.notebooklm.max_words_per_query,
            parallel_queries=project.notebooklm.parallel_queries,
            timeout_seconds=project.notebooklm.timeout_seconds,
        )

    # ------------------------------------------------------------ Step 1: NotebookLM writes
    if "write" not in skip_steps and section_specs and adapter is not None:
        for spec in section_specs:
            draft = write_section(adapter, spec)
            result.drafts.append(draft)
            # Persist each draft to disk so the user can review before audit
            out = project.state_dir() / f"notebook_section_{spec.id.replace('.', '_')}.md"
            out.write_text(
                f"# {spec.id} {spec.title}\n\n{draft.body}\n\n## Bibliografia wykorzystana\n\n"
                + "\n\n".join(draft.bibliography),
                encoding="utf-8",
            )
            result.artifacts[f"section_{spec.id}"] = out

    # ------------------------------------------------------------ Step 2: Citation audit swarm
    if "audit" not in skip_steps:
        result.audit = run_citation_audit(
            project, cli=cli, max_parallel=project.pipeline.max_parallel_haiku
        )
        if result.audit.merged_report_path:
            result.artifacts["citation_audit"] = result.audit.merged_report_path

    # ------------------------------------------------------------ Step 3: Opus orchestrator
    if "orchestrate" not in skip_steps and result.audit is not None:
        result.fixes = orchestrate_fixes(project, result.audit, cli=cli)
        result.artifacts["citation_fixes"] = project.state_dir() / "citation_fixes.json"

    # ------------------------------------------------------------ Step 4: NotebookLM correction
    if (
        "correct" not in skip_steps
        and result.fixes
        and result.fixes.fixes
        and adapter is not None
    ):
        by_section = result.fixes.by_section()
        for section_id, fixes in by_section.items():
            corr = request_corrections(adapter, section_id, fixes)
            out = project.reports_dir() / f"corrections_{section_id.replace('.', '_')}.md"
            out.write_text(
                f"# Korekty cytowań — sekcja {section_id}\n\n{corr.corrected_text}",
                encoding="utf-8",
            )
            result.corrections_by_section[section_id] = corr.corrected_text
            result.artifacts[f"corrections_{section_id}"] = out

    return result
