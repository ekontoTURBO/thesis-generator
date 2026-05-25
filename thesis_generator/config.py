"""Project configuration model.

Each thesis is one directory on disk. Inside it lives `thesis.yaml` with the
spec for inputs, models, NotebookLM library, and pipeline parameters. The
generator never writes to inputs, never mutates the YAML — only reads it and
writes derived artifacts into the project directory.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class CitationStyle(str, Enum):
    APA7 = "apa7"
    VANCOUVER = "vancouver"  # planned
    CHICAGO = "chicago"  # planned


class Language(str, Enum):
    PL = "pl"
    EN = "en"


class ModelRouting(BaseModel):
    """Which Claude model handles which job.

    Defaults match the proven session: Opus writes/audits, Sonnet rewrites,
    Haiku verifies per source.
    """

    writer: str = "claude-opus-4-7"
    auditor: str = "claude-opus-4-7"
    reviewer: str = "claude-opus-4-7"
    rewriter: str = "claude-sonnet-4-6"
    verifier_per_source: str = "claude-haiku-4-5-20251001"


class Inputs(BaseModel):
    """User-provided files. Paths are relative to project root.

    Recommended layout (created by `tg init`):

        inputs/
        ├── draft.docx                         # your existing partial thesis
        ├── sources/                           # PDF library — academic literature you cite
        │   └── (drop your .pdf files here, recursive — sub-folders OK)
        ├── research_data/                     # YOUR research data
        │   ├── surveys/                       # CAWI/PAPI questionnaires (xlsx, csv, json)
        │   ├── interviews/                    # IDI/FGI transcripts (pdf, docx, md)
        │   ├── observations/                  # field notes, ethnography
        │   └── existing/                      # secondary data (GUS, industry reports as xlsx)
        ├── school/                            # documents from the university
        │   ├── regulation.docx                # formatting regulation / Zarządzenie
        │   ├── brief.pdf                      # promotor's task brief / system prompt
        │   └── templates/                     # title page, declarations, etc.
        └── notes/                             # anything else (guidelines, correspondence)

    You only need `draft` and `sources_dir`. Everything else is optional and
    auto-discovered when the folder exists.
    """

    draft: Path = Field(..., description="Existing thesis .docx (even if just the introduction)")
    sources_dir: Path = Field(..., description="Folder containing academic source PDFs")

    # Research data — can be expressed either as a single dir (auto-discovers
    # subfolders) or as a flat list of files (legacy / explicit mode).
    research_data_dir: Path | None = Field(
        None,
        description="Folder containing YOUR research data (surveys/interviews/observations/existing). "
        "Auto-discovered subfolders are: surveys/, interviews/, observations/, existing/.",
    )
    raw_data: list[Path] = Field(
        default_factory=list,
        description="Explicit list of Excel/CSV files (legacy). If empty, research_data_dir is scanned.",
    )

    # Interviews — either inside research_data_dir/interviews/ or pointed at directly.
    interviews_dir: Path | None = Field(
        None,
        description="Folder with IDI/FGI transcript PDFs. If unset, research_data_dir/interviews is used.",
    )

    # School documents — either inside school/ or pointed at directly.
    school_dir: Path | None = Field(
        None,
        description="Folder with school-issued documents. Defaults to inputs/school/ when present.",
    )
    regulation: Path | None = Field(
        None, description="School formatting regulation .docx (overrides auto-discovery)"
    )
    school_brief: Path | None = Field(
        None, description="The school's task brief / system prompt PDF"
    )

    additional: list[Path] = Field(
        default_factory=list, description="Anything else the writer should know about"
    )


class NotebookLM(BaseModel):
    """NotebookLM library used as the source-grounded verification engine.

    Required for Ring C verification. The library must contain the same sources
    listed in `inputs.sources_dir` (or a strict superset) — otherwise
    NotebookLM will reject queries with "I don't see that source."
    """

    library_url: str = Field(..., description="https://notebooklm.google.com/notebook/<UUID>")
    library_name: str = Field(..., description="Human-readable name for logging")
    max_words_per_query: int = 400
    parallel_queries: int = 3
    timeout_seconds: int = 300


class HumanizationPolicy(BaseModel):
    """Post-write language polish — removes obvious AI tells from the draft.

    Defaults match what the user enforced 3x in the proven session.
    """

    remove_em_dashes: bool = True
    """Replace ` — ` with `, ` (preserves en-dashes in page ranges)."""

    forbidden_words: list[str] = Field(
        default_factory=lambda: ["triangulacja", "rygorystycznie", "holistycznie", "synergiczny", "paradygmat"]
    )
    """Stripped or paraphrased if they appear. Domain-specific override expected."""

    sentence_length_variance: bool = True
    """Aim for 1-in-5 unusually long sentence (the 'human pacing' trick)."""

    chevron_quotes: bool = True
    """Use «...» for second-level Polish quotes (only if existing draft uses them)."""

    fake_access_dates: bool = False
    """If true, randomize netografia access dates across `fake_date_range`."""

    fake_date_range: tuple[str, str] = ("2024-03-01", "2025-06-30")


class Output(BaseModel):
    """Where the final artifacts land."""

    dir: Path = Field(Path("output"), description="Where final .docx/.pdf go (relative to project root)")
    docx_name: str = "Praca_licencjacka.docx"
    pdf: bool = True
    versioned: bool = True
    """Keep all intermediate Praca_v1.docx ... Praca_vN.docx in `output/_versions/`."""


class Pipeline(BaseModel):
    """High-level pipeline behavior."""

    section_by_section: bool = True
    """If true, writer pauses after every subsection for progress report."""

    verification_rings: list[str] = Field(default_factory=lambda: ["A", "B", "C"])
    """Which rings to run. A=internal, B=Haiku-per-source, C=NotebookLM."""

    re_verify_on_edit: bool = True
    """If the user edits the .docx, re-run all verification."""

    reviewer_passes: int = 1
    """How many independent-reviewer passes per ship (1 = standard, 3 = paranoid)."""

    max_parallel_haiku: int = 12
    """Concurrent Haiku verifiers. Brief says 10-24 worked. >24 hits rate limits."""

    fail_on_grade_below: float = 4.0
    """Pipeline `ship` refuses to export below this grade. 5.0 = perfect, 2.0 = fail."""


class ThesisProject(BaseModel):
    """The single source of truth for a thesis run."""

    project_dir: Path
    title: str
    author: str
    school: str = ""
    promotor: str = ""
    language: Language = Language.PL
    citation_style: CitationStyle = CitationStyle.APA7

    inputs: Inputs
    notebooklm: NotebookLM | None = None
    """REQUIRED if Ring C is in `pipeline.verification_rings`."""

    models: ModelRouting = Field(default_factory=ModelRouting)
    humanization: HumanizationPolicy = Field(default_factory=HumanizationPolicy)
    output: Output = Field(default_factory=Output)
    pipeline: Pipeline = Field(default_factory=Pipeline)

    @field_validator("project_dir")
    @classmethod
    def _abspath(cls, v: Path) -> Path:
        return Path(v).expanduser().resolve()

    @classmethod
    def load(cls, project_dir: str | Path) -> "ThesisProject":
        """Load `<project_dir>/thesis.yaml` and return a validated project."""
        project_dir = Path(project_dir).expanduser().resolve()
        yaml_path = project_dir / "thesis.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"No thesis.yaml at {yaml_path}. Run `thesis-generator init` first.")
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        data["project_dir"] = project_dir
        return cls.model_validate(data)

    def resolve_input(self, p: Path) -> Path:
        """Resolve any input path against the project dir."""
        p = Path(p)
        return p if p.is_absolute() else (self.project_dir / p).resolve()

    # ---- Effective-path helpers (auto-discovery for the recommended layout) ----

    def effective_research_data_dir(self) -> Path | None:
        """Return research_data_dir, defaulting to inputs/research_data if it exists."""
        if self.inputs.research_data_dir:
            p = self.resolve_input(self.inputs.research_data_dir)
            return p if p.exists() else None
        guess = self.project_dir / "inputs" / "research_data"
        return guess if guess.exists() else None

    def effective_interviews_dir(self) -> Path | None:
        """interviews_dir if set, else research_data_dir/interviews/ if it exists."""
        if self.inputs.interviews_dir:
            p = self.resolve_input(self.inputs.interviews_dir)
            return p if p.exists() else None
        rd = self.effective_research_data_dir()
        if rd:
            sub = rd / "interviews"
            return sub if sub.exists() else None
        return None

    def effective_school_dir(self) -> Path | None:
        """school_dir if set, else inputs/school/ if it exists."""
        if self.inputs.school_dir:
            p = self.resolve_input(self.inputs.school_dir)
            return p if p.exists() else None
        guess = self.project_dir / "inputs" / "school"
        return guess if guess.exists() else None

    def effective_regulation(self) -> Path | None:
        """regulation if set, else school_dir/regulation.docx if it exists."""
        if self.inputs.regulation:
            p = self.resolve_input(self.inputs.regulation)
            return p if p.exists() else None
        sd = self.effective_school_dir()
        if sd:
            for name in ("regulation.docx", "Zarządzenie.docx", "zalacznik.docx"):
                cand = sd / name
                if cand.exists():
                    return cand
        return None

    def effective_school_brief(self) -> Path | None:
        if self.inputs.school_brief:
            p = self.resolve_input(self.inputs.school_brief)
            return p if p.exists() else None
        sd = self.effective_school_dir()
        if sd:
            for ext in ("brief.pdf", "brief.docx", "system_prompt.pdf", "system_prompt.docx"):
                cand = sd / ext
                if cand.exists():
                    return cand
        return None

    def effective_research_data_files(self) -> list[Path]:
        """Combined list: explicit raw_data + auto-discovered files under research_data_dir.

        Looks for .xlsx, .xls, .csv, .json under research_data_dir/surveys/ and
        research_data_dir/existing/. Returns absolute paths, deduplicated.
        """
        files: list[Path] = []
        seen: set[Path] = set()
        for p in self.inputs.raw_data:
            ap = self.resolve_input(p)
            if ap not in seen:
                files.append(ap)
                seen.add(ap)
        rd = self.effective_research_data_dir()
        if rd:
            for sub in ("surveys", "existing"):
                folder = rd / sub
                if folder.exists():
                    for pat in ("*.xlsx", "*.xls", "*.csv", "*.json"):
                        for f in folder.glob(pat):
                            ap = f.resolve()
                            if ap not in seen:
                                files.append(ap)
                                seen.add(ap)
        return files

    def reports_dir(self) -> Path:
        d = self.project_dir / "_reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def state_dir(self) -> Path:
        d = self.project_dir / "_state"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def output_dir(self) -> Path:
        d = self.resolve_input(self.output.dir)
        d.mkdir(parents=True, exist_ok=True)
        return d


def anthropic_api_key() -> str:
    """Return the API key from env, with a clear error if missing.

    DEPRECATED: the default LLM backend is now `claude -p` (Claude Code CLI)
    which uses the user's subscription auth. This helper is kept for users who
    explicitly want the Anthropic SDK path. See `thesis_generator.llm.ClaudeCLI`.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY env var is not set. Either install Claude Code from "
            "https://claude.com/code (recommended — uses your subscription, no API key needed) "
            "or `export ANTHROPIC_API_KEY=sk-...` for the legacy SDK path."
        )
    return key
