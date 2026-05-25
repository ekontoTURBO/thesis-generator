"""Top-level pipeline orchestrator.

This is what `tg run my-thesis/` calls. Sequences every phase and writes the
PROGRESS.md disaster-recovery file after every step.

Phases (matches brief section 2):
    0. env_check
    1. inventory
    2. write (if writer specs supplied)
    3. verify_ring_a   (internal)
    4. verify_ring_b   (Haiku per source) — parallel
    5. verify_ring_c   (NotebookLM)       — parallel-bounded
    6. data_audit      (raw xlsx recompute)
    7. independent_review
    8. humanize        (em-dashes, forbidden words)
    9. ship            (final docx + optional pdf)

Any phase can be skipped via `phases=` parameter. Failures in a verification
ring don't abort the pipeline by default — they accumulate into the report.
The `fail_on_grade_below` config gate is the only hard stop before ship.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thesis_generator.config import ThesisProject
from thesis_generator.env_check import check_env
from thesis_generator.inventory import build_inventory
from thesis_generator.reports.progress import update_progress
from thesis_generator.review.independent import run_independent_review, save_report as save_review_report
from thesis_generator.verify.internal import run_ring_a, save_report as save_a_report
from thesis_generator.verify.haiku_per_source import run_ring_b, save_report as save_b_report
from thesis_generator.verify.notebooklm_ring import run_ring_c, save_report as save_c_report
from thesis_generator.verify.data_audit import run_data_audit, save_report as save_data_report
from thesis_generator.docx_ops.humanize import humanize_docx


@dataclass(slots=True)
class PipelineResult:
    project: ThesisProject
    phases_completed: list[str] = field(default_factory=list)
    artifacts: dict[str, Path] = field(default_factory=dict)
    failed_phases: list[tuple[str, str]] = field(default_factory=list)
    final_grade: float | None = None

    @property
    def ok(self) -> bool:
        return not self.failed_phases


ALL_PHASES = (
    "env_check",
    "inventory",
    "verify_a",
    "verify_b",
    "verify_c",
    "data_audit",
    "independent_review",
    "humanize",
)


def run_pipeline(
    project: ThesisProject,
    *,
    phases: tuple[str, ...] = ALL_PHASES,
    paraphrases: dict | None = None,
) -> PipelineResult:
    """Run the pipeline synchronously. Async phases are wrapped here.

    `paraphrases` is the citation-paraphrase map for verification rings B and C.
    If None, Ring B/C will use a fallback that reads sentences around each
    citation (less accurate; users should populate paraphrases from the writer's
    output for best results).
    """
    return asyncio.run(_run_pipeline_async(project, phases=phases, paraphrases=paraphrases))


async def _run_pipeline_async(
    project: ThesisProject,
    *,
    phases: tuple[str, ...],
    paraphrases: dict | None,
) -> PipelineResult:
    result = PipelineResult(project=project)

    # 0. env_check
    if "env_check" in phases:
        env = check_env(project)
        out = project.reports_dir() / "env_check.md"
        out.write_text(env.render(), encoding="utf-8")
        result.artifacts["env_check"] = out
        if env.ok:
            result.phases_completed.append("env_check")
        else:
            result.failed_phases.append(("env_check", f"missing: {env.missing}"))
            update_progress(
                project,
                phase="env_check",
                status="BLOCKED",
                icon="❌",
                blockers=env.missing,
            )
            return result  # hard gate

    # 1. inventory
    if "inventory" in phases:
        inv = build_inventory(project)
        result.phases_completed.append("inventory")
        result.artifacts["inventory"] = project.state_dir() / "inventory.json"

    # 2. Ring A
    ring_a_result = None
    if "verify_a" in phases:
        ring_a_result = run_ring_a(project)
        result.artifacts["ring_a"] = save_a_report(ring_a_result, project)
        result.phases_completed.append("verify_a")

    # 3. Ring B (parallel Haiku)
    if "verify_b" in phases:
        try:
            ring_b_result = await run_ring_b(project, paraphrases=paraphrases)
            result.artifacts["ring_b"] = save_b_report(ring_b_result, project)
            result.phases_completed.append("verify_b")
        except Exception as e:
            result.failed_phases.append(("verify_b", str(e)))

    # 4. Ring C (NotebookLM)
    if "verify_c" in phases and project.notebooklm is not None and paraphrases:
        try:
            ring_c_result = await run_ring_c(project, paraphrases=paraphrases)
            result.artifacts["ring_c"] = save_c_report(ring_c_result, project)
            result.phases_completed.append("verify_c")
        except Exception as e:
            result.failed_phases.append(("verify_c", str(e)))

    # 5. Data audit
    if "data_audit" in phases:
        try:
            audit = run_data_audit(project)
            result.artifacts["data_audit"] = save_data_report(audit, project)
            result.phases_completed.append("data_audit")
        except Exception as e:
            result.failed_phases.append(("data_audit", str(e)))

    # 6. Independent reviewer
    if "independent_review" in phases:
        try:
            review = run_independent_review(project)
            result.artifacts["reviewer"] = save_review_report(review, project)
            result.final_grade = review.grade
            result.phases_completed.append("independent_review")
        except Exception as e:
            result.failed_phases.append(("independent_review", str(e)))

    # 7. Humanize
    if "humanize" in phases:
        try:
            draft = project.resolve_input(project.inputs.draft)
            stats = humanize_docx(draft, project.humanization)
            out = project.reports_dir() / "humanize.md"
            out.write_text(stats.render(), encoding="utf-8")
            result.artifacts["humanize"] = out
            result.phases_completed.append("humanize")
        except Exception as e:
            result.failed_phases.append(("humanize", str(e)))

    update_progress(
        project,
        phase="Pipeline complete",
        status="DONE" if result.ok else "BLOCKED",
        icon="🎉" if result.ok else "⚠️",
        completed=result.phases_completed,
        findings=[f"Independent reviewer grade: {result.final_grade}" if result.final_grade else "Reviewer did not run"],
        blockers=[f"{p}: {r}" for p, r in result.failed_phases],
    )
    return result
