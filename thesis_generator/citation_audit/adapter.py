"""Subprocess adapter for the `thesis-citation-audit` skill.

The skill's scripts do the docx extraction, structure detection, and per-section
splitting. We call them directly (they're standalone Python). Then we dispatch
Haiku sub-agents via our `ClaudeCLI` adapter using the skill's prompt template
(`section_prompt.md`) verbatim — so the swarm runs on `claude -p`, no API key.

Why not just invoke the skill via `/thesis-citation-audit`? Because the skill
is marked `disable-model-invocation: true` and is a one-shot tool. We need
programmatic orchestration so we can chain it into the broader pipeline
(writer → audit → orchestrator → correction → ship).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from thesis_generator.config import ThesisProject
from thesis_generator.llm import ClaudeCLI


class CitationAuditError(RuntimeError):
    """Raised when the skill's scripts fail or the skill isn't installed."""


def _default_skill_dir() -> Path:
    candidates = [
        Path.home() / ".claude" / "skills" / "thesis-citation-audit",
        Path(os.environ.get("CLAUDE_SKILLS_DIR", "")) / "thesis-citation-audit"
        if os.environ.get("CLAUDE_SKILLS_DIR")
        else None,
    ]
    for c in candidates:
        if c and c.exists():
            return c
    raise CitationAuditError(
        "thesis-citation-audit skill not found. Install it into "
        "`~/.claude/skills/thesis-citation-audit/`. See docs/CITATION_AUDIT.md."
    )


@dataclass(slots=True)
class SectionReport:
    """One Haiku sub-agent's output for one subsection."""

    section_id: str
    report_path: Path
    report_text: str = ""
    ok_count: int = 0
    page_issues: int = 0          # ⚠️ STRONA
    content_issues: int = 0       # ❌ TREŚĆ
    missing_source: int = 0       # ❓ BRAK ŹRÓDŁA
    biblio_issues: int = 0        # 🔴 BIBLIOGRAFIA
    total: int = 0


@dataclass(slots=True)
class CitationAuditResult:
    workdir: Path
    sections: list[SectionReport] = field(default_factory=list)
    merged_report_path: Path | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def total_citations(self) -> int:
        return sum(s.total for s in self.sections)

    @property
    def total_problems(self) -> int:
        return sum(s.total - s.ok_count for s in self.sections)


# ---------------------------------------------------------------- Public API


def run_citation_audit(
    project: ThesisProject,
    *,
    cli: ClaudeCLI | None = None,
    max_parallel: int = 6,
) -> CitationAuditResult:
    """Run the full Haiku-per-section citation-audit swarm against the project's draft.

    Steps:
      1. Extract docx → text + structure + citations (skill's extract_thesis.py)
      2. Split into per-subsection files (skill's split_sections.py)
      3. Dispatch one Haiku per subsection via ClaudeCLI (skill's section_prompt.md)
      4. Merge into one report (skill's merge_report.py)
    """
    skill = _default_skill_dir()
    cli = cli or ClaudeCLI(max_concurrent=max_parallel)

    draft = project.resolve_input(project.inputs.draft)
    sources = project.resolve_input(project.inputs.sources_dir)
    workdir = project.state_dir() / "citation_audit"
    workdir.mkdir(parents=True, exist_ok=True)

    result = CitationAuditResult(workdir=workdir)

    # ---- Step 1: extract ----
    _run_script(
        skill / "scripts" / "extract_thesis.py",
        [str(draft), str(workdir)],
        label="extract_thesis",
    )

    # ---- Step 2: split per subsection ----
    _run_script(
        skill / "scripts" / "split_sections.py",
        [str(workdir)],
        label="split_sections",
    )

    index_path = workdir / "sections" / "_index.json"
    if not index_path.exists():
        raise CitationAuditError(f"split_sections did not produce {index_path}")
    sections_index = json.loads(index_path.read_text(encoding="utf-8"))
    bibliography_file = workdir / "bibliography.txt"
    reports_dir = workdir / "reports"
    reports_dir.mkdir(exist_ok=True)

    # ---- Step 3: dispatch Haiku swarm in parallel ----
    template_path = skill / "templates" / "section_prompt.md"
    template = template_path.read_text(encoding="utf-8")

    # Each entry in _index.json describes one subsection. We use its `section_id`
    # for the report filename. `source_folder_hint` (if present) tells us which
    # subfolder of `sources/` to point Haiku at; default = whole sources/ folder.
    section_specs = [
        _build_section_spec(s, sources, bibliography_file, reports_dir, template)
        for s in sections_index
    ]
    completed = asyncio.run(_dispatch_swarm(cli, section_specs))

    for spec, completed_ok in zip(section_specs, completed):
        report_path = spec["report_path"]
        sr = SectionReport(section_id=spec["section_id"], report_path=report_path)
        if completed_ok and report_path.exists():
            sr.report_text = report_path.read_text(encoding="utf-8", errors="replace")
            _tally(sr)
        result.sections.append(sr)

    # ---- Step 4: merge ----
    merged = project.reports_dir() / "citation_audit.md"
    try:
        _run_script(
            skill / "scripts" / "merge_report.py",
            [str(workdir), str(merged)],
            label="merge_report",
        )
        result.merged_report_path = merged
    except CitationAuditError as e:
        result.notes.append(f"merge_report failed: {e} (per-section reports still in {reports_dir})")

    return result


# ---------------------------------------------------------------- Internals


def _build_section_spec(
    entry: dict, sources: Path, bibliography: Path, reports_dir: Path, template: str
) -> dict:
    section_id = entry["section_id"]
    section_file = entry.get("section_file") or entry.get("path")
    report_path = reports_dir / f"section_{section_id.replace('.', '_')}_report.md"

    # Source folder hint: per-chapter subfolders are common
    sub_hint = entry.get("source_folder_hint")
    sf = (sources / sub_hint).resolve() if sub_hint and (sources / sub_hint).exists() else sources

    prompt = (
        template
        .replace("{{section_id}}", section_id)
        .replace("{{section_file}}", str(section_file))
        .replace("{{sources_folder}}", str(sf))
        .replace("{{bibliography_file}}", str(bibliography))
        .replace("{{report_path}}", str(report_path))
    )
    return {
        "section_id": section_id,
        "report_path": report_path,
        "prompt": prompt,
    }


async def _dispatch_swarm(cli: ClaudeCLI, specs: list[dict]) -> list[bool]:
    """Fire one Haiku per section in parallel (bounded by ClaudeCLI's semaphore).

    Each agent gets Bash + Read enabled so it can run `pdftotext` and verify pages.
    """
    async def one(spec: dict) -> bool:
        try:
            await cli.complete(
                model="haiku",
                user=spec["prompt"],
                allowed_tools=["Bash", "Read", "Write"],
                max_budget_usd=1.5,
                timeout=1800,
            )
            return spec["report_path"].exists()
        except Exception as e:
            # The report file may still get written even if the call fails partway;
            # caller checks existence after.
            return spec["report_path"].exists()

    return list(await asyncio.gather(*(one(s) for s in specs)))


def _run_script(script: Path, args: list[str], *, label: str) -> None:
    """Run one of the skill's scripts as a subprocess."""
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.run(
        cmd,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if proc.returncode != 0:
        raise CitationAuditError(
            f"{label} failed (exit {proc.returncode}): {(proc.stderr or '')[:1000]}"
        )


def _tally(sr: SectionReport) -> None:
    """Count status markers in the report text."""
    t = sr.report_text
    sr.ok_count = t.count("✅") + t.count("Status:** ✅")
    sr.page_issues = t.count("⚠️")
    sr.content_issues = t.count("❌")
    sr.missing_source = t.count("❓")
    sr.biblio_issues = t.count("🔴")
    sr.total = sr.ok_count + sr.page_issues + sr.content_issues + sr.missing_source + sr.biblio_issues
