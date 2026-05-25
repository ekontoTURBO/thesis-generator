"""Step 0 of the pipeline — environment verification (HARD GATE).

The proven session opened with this exact gate. It saved hours of later cleanup
by catching missing files, double-space filename bugs, and folder confusion
*before* anything was written.

The rule: NEVER guess paths, NEVER create stubs for missing inputs. Either
everything is present (with byte-exact filename match) or we refuse to start.
"""

from __future__ import annotations

import platform
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.config import ThesisProject


@dataclass(slots=True)
class EnvCheckResult:
    ok: bool
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: dict[str, str] = field(default_factory=dict)

    def render(self) -> str:
        lines = []
        status = "✅ OK" if self.ok else "❌ MISSING REQUIRED INPUTS"
        lines.append(f"# Environment check — {status}\n")
        if self.missing:
            lines.append("## Missing\n")
            lines.extend(f"- {m}" for m in self.missing)
            lines.append("")
        if self.warnings:
            lines.append("## Warnings\n")
            lines.extend(f"- ⚠️ {w}" for w in self.warnings)
            lines.append("")
        if self.info:
            lines.append("## Environment\n")
            for k, v in self.info.items():
                lines.append(f"- **{k}**: {v}")
        return "\n".join(lines)


def _check_file(path: Path, label: str, required: bool = True) -> tuple[bool, list[str], list[str]]:
    """Verify a single file. Returns (exists, [missing_msgs], [warnings])."""
    missing: list[str] = []
    warnings: list[str] = []

    if not path.exists():
        if required:
            missing.append(f"{label}: not found at `{path}`")
        else:
            warnings.append(f"{label}: optional, not found at `{path}`")
        return False, missing, warnings

    # Filename ambiguity checks (the brief's gotchas #1 + #7)
    name = path.name
    if "  " in name:
        warnings.append(f"{label}: filename `{name}` has DOUBLE SPACES — fragile, but matched OK")
    if name != unicodedata.normalize("NFC", name):
        warnings.append(f"{label}: filename `{name}` has non-NFC Unicode — may break on some tools")
    # Word lock file (gotcha #4)
    lock = path.parent / f"~${path.name}"
    if lock.exists():
        warnings.append(f"{label}: Word lock file `{lock.name}` exists — close the document in Word before running")

    return True, [], warnings


def _check_python_env() -> dict[str, str]:
    info = {
        "Python": sys.version.split()[0],
        "Platform": platform.system(),
        "PYTHONIOENCODING": __import__("os").environ.get("PYTHONIOENCODING", "(not set — may break on Polish chars)"),
    }
    for tool in ("python", "python3"):
        path = shutil.which(tool)
        info[f"which({tool})"] = path or "—"
    return info


def check_env(project: ThesisProject) -> EnvCheckResult:
    """Top-level: verify every input declared in `thesis.yaml` actually exists."""
    result = EnvCheckResult(ok=True)
    result.info.update(_check_python_env())
    result.info["project_dir"] = str(project.project_dir)

    # Required: draft + sources_dir
    draft = project.resolve_input(project.inputs.draft)
    ok, miss, warn = _check_file(draft, "inputs.draft (existing .docx)", required=True)
    if not ok:
        result.ok = False
    result.missing.extend(miss)
    result.warnings.extend(warn)

    sources_dir = project.resolve_input(project.inputs.sources_dir)
    if not sources_dir.exists() or not sources_dir.is_dir():
        result.ok = False
        result.missing.append(f"inputs.sources_dir: not a directory at `{sources_dir}`")
    else:
        pdfs = list(sources_dir.rglob("*.pdf"))
        result.info["sources found"] = str(len(pdfs))
        if not pdfs:
            result.warnings.append(f"inputs.sources_dir: `{sources_dir}` contains 0 PDFs")

    # Optional structured inputs — report what was auto-discovered for transparency
    research = project.effective_research_data_dir()
    if research:
        subfolders: list[str] = []
        for sub in ("surveys", "interviews", "observations", "existing"):
            folder = research / sub
            if folder.exists():
                # Count real user files, ignore README scaffolds + hidden files.
                n = sum(
                    1
                    for f in folder.iterdir()
                    if f.is_file() and f.name != "README.md" and not f.name.startswith(".")
                )
                subfolders.append(f"{sub}/ ({n})")
        result.info["research_data"] = (
            f"✅ {research} — {', '.join(subfolders) if subfolders else 'empty'}"
        )
    else:
        result.warnings.append(
            "research_data_dir not configured and inputs/research_data/ does not exist. "
            "Drop your surveys, interview transcripts, observations there for data audit + Ring B."
        )

    interviews = project.effective_interviews_dir()
    if interviews:
        n_pdfs = len(list(interviews.glob("*.pdf"))) + len(list(interviews.glob("*.docx")))
        result.info["interviews"] = f"✅ {interviews} ({n_pdfs} transcripts)"

    school = project.effective_school_dir()
    if school:
        result.info["school_dir"] = f"✅ {school}"

    reg = project.effective_regulation()
    if reg:
        result.info["regulation"] = f"✅ {reg.name}"
    else:
        result.warnings.append(
            "No school formatting regulation found. Drop it into inputs/school/regulation.docx "
            "or set inputs.regulation in thesis.yaml — without it the reviewer can't check formatting compliance."
        )

    brief = project.effective_school_brief()
    if brief:
        result.info["school_brief"] = f"✅ {brief.name}"

    # Aggregate explicit + auto-discovered research data files for downstream audit.
    rd_files = project.effective_research_data_files()
    if rd_files:
        result.info["research_data files"] = f"{len(rd_files)} (xlsx/csv/json)"
    elif "data_audit" in {"data_audit"}:  # data audit will run regardless
        result.warnings.append(
            "No research data files (xlsx/csv) found. Data audit will be a no-op. "
            "Drop your survey results into inputs/research_data/surveys/."
        )

    # NotebookLM auth check (only if Ring C requested)
    if "C" in project.pipeline.verification_rings:
        if project.notebooklm is None:
            result.ok = False
            result.missing.append(
                "notebooklm: not configured but Ring C is in pipeline.verification_rings. "
                "Add a `notebooklm:` block to thesis.yaml or remove 'C' from verification_rings."
            )
        else:
            try:
                from thesis_generator.notebooklm import NotebookLMAdapter

                adapter = NotebookLMAdapter(
                    library_url=project.notebooklm.library_url,
                    library_name=project.notebooklm.library_name,
                )
                authed = adapter.check_auth()
                result.info["NotebookLM auth"] = "✅ authenticated" if authed else "❌ NOT authenticated"
                if not authed:
                    result.warnings.append(
                        "NotebookLM is NOT authenticated. Run: "
                        "`python ~/.claude/skills/notebooklm/scripts/run.py auth_manager.py setup` "
                        "(opens a browser for Google login)."
                    )
            except Exception as e:
                result.warnings.append(f"NotebookLM check failed: {e}")

    # LLM backend — prefer `claude` CLI (uses user's Claude Code subscription),
    # fall back to ANTHROPIC_API_KEY if CLI not available.
    import os
    import shutil

    claude_bin = shutil.which("claude")
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))

    if claude_bin:
        result.info["LLM backend"] = f"✅ claude CLI ({claude_bin})"
        try:
            from thesis_generator.llm import ClaudeCLI

            ok, msg = ClaudeCLI(claude_bin=claude_bin).check_auth()
            result.info["claude CLI auth"] = "✅ authenticated" if ok else f"❌ {msg}"
            if not ok and not has_api_key:
                result.ok = False
                result.missing.append(
                    "claude CLI not authenticated AND ANTHROPIC_API_KEY not set. "
                    "Run `claude /login` interactively, or `export ANTHROPIC_API_KEY=sk-...`."
                )
        except Exception as e:
            result.warnings.append(f"claude CLI auth check raised: {e}")
    elif has_api_key:
        result.info["LLM backend"] = "ANTHROPIC_API_KEY (no claude CLI on PATH)"
    else:
        result.ok = False
        result.missing.append(
            "No LLM backend available. Install Claude Code (https://claude.com/code) "
            "and run `claude /login`, OR set ANTHROPIC_API_KEY."
        )

    # Word lock file in output dir
    output_dir = project.output_dir()
    locks = list(output_dir.glob("~$*"))
    if locks:
        result.warnings.append(f"Word lock files in output dir: {[l.name for l in locks]} — close in Word first")

    return result
