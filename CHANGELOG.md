# Changelog

All notable changes to this project will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Numbers audit (dedicated Opus auditor + hypothesis consistency)

The single most under-tested area of any thesis is the statistics. The proven session caught 5/75 numbers as off-by-N (e.g. "6 respondentów" → really 4; "65% kolejny headset" → really ~34%). The previous `data_audit` did heuristic regex matching against cell values — fast but only catches obvious mismatches. The new `numbers_audit` package goes further:

**New module** `thesis_generator.numbers_audit`:

- `extractor.py` — parses every numeric claim (M, SD, n, χ², t, p, d, V Craméra, Pearson r, %, raw counts) from the draft, plus every H1/H2/H3 hypothesis declaration + verdict keyword.
- `recomputer.py` — dispatches ONE Opus call with `--allowedTools "Bash Read Write"`. Opus writes its own Python script per thesis (each thesis has different data shape), opens the raw research data, recomputes EVERY claimed statistic from scratch, saves a parallel `output/_audits/recompute_audit.xlsx`, and returns JSON-lines diffs (claimed vs recomputed + status: OK / MISMATCH / UNVERIFIABLE / INTERPRETATION_OK).
- `consistency.py` — second Opus call: given the hypothesis statements + the recomputed numbers, judges per-hypothesis whether the data actually supports the author's verdict. Returns `SUPPORTED / NOT_SUPPORTED / PARTIALLY / OVER_INTERPRETED / INSUFFICIENT_DATA`.

**Why Opus and not Haiku/regex:** every thesis has a different data shape. Opus needs to (a) inspect the data structure, (b) write correct Python for the specific statistics claimed, (c) judge when a small delta is rounding noise vs a real error.

**CLI:**
- `tg recompute-data <project>` — recompute only, produces parallel xlsx + markdown report
- `tg check-hypotheses <project>` — recompute + hypothesis consistency pass

**Integration with `tg audit`:** deep mode now runs both phases automatically; consolidated `_reports/THESIS_AUDIT.md` includes the recompute mismatches and hypothesis verdicts in dedicated sections.

**Cost discipline:** `--max-claims` flag caps how many claims Opus processes per run (default 80). For very large theses, run multiple times with different slices.

4 new regression tests pin the extractor, the JSON-lines diff parser, and the verdict parser.

### Added — Audit-only mode (`tg audit`)

New top-level command and pipeline for the "I already have a finished thesis, just check it" use case. Every phase is read-only or operates on a temp copy — the original draft.docx is never touched.

**New module** `thesis_generator.audit_only`:
- `run_audit(project, deep=True|False, skip=(...))` — orchestrates every read-only verification phase
- `AuditResult` dataclass collecting every phase's output
- Single consolidated report at `_reports/THESIS_AUDIT.md` with executive summary, per-section findings, prioritized fix list, reviewer report, AI-tells check
- `deep=False` skips the slow LLM phases (citation swarm + Opus reviewer) for instant feedback
- `skip=(...)` accepts any subset of: `env, inventory, ring_a, citation_audit, orchestrate, data, reviewer, visuals, humanize`

**Read-only invariants enforced and tested:**
- Humanize runs against a temp copy of the draft
- Visuals does counts via `parse_markers` without inserting anything
- No phase calls `doc.save()` on the original
- Regression test `test_audit_only_runs_shallow_on_existing_thesis` verifies size + mtime of draft unchanged after audit

**CLI:** `tg audit <project> [--shallow] [--skip phase1,phase2]`

**README:** new "Two modes of use" section explaining (1) generation mode vs (2) audit mode, with a how-to for bringing your own thesis.

### Fixed — Ring A bibliography section detection

Ring A now handles bibliographies without explicit `I. Literatura naukowa` / `II. Raporty` section dividers — most student theses use a flat layout. Without this fix, `_find_bib_markers` produced an empty `section_at` dict and Ring A reported zero bibliography entries, suppressing every orphan/missing-from-bib finding.

### Added — major architectural shift: NotebookLM-first 4-step pipeline

The primary writing flow now flips: **NotebookLM writes, Haiku+Opus verify, NotebookLM corrects.** The previous Claude-writer-first path is still available (Ring A/B/C), but the new `tg notebook-pipeline` is the recommended flow because NotebookLM is genuinely better at writing source-grounded prose — its weakness is precise page numbers and exact attribution, which is exactly what the audit swarm catches.

**The 4 steps:**

1. **`tg notebook-write`** — NotebookLM writes one subsection per call, step-by-step, using the user-configured system prompt
   - New module `thesis_generator.notebooklm.writer` with `NotebookSectionSpec`, `NotebookSectionDraft`, `build_writer_prompt`, `parse_notebook_response`, `write_section`
   - Per-section prompt is intentionally short — the global behavior (APA 7 format, author-introduction pattern, forbidden meta phrases, visual material markers, bibliography format) lives in the **NotebookLM System Instructions**, which the user must paste from `docs/notebooklm_system_prompt.pl.pdf` once
2. **`tg audit-citations`** — Haiku swarm citation audit
   - New module `thesis_generator.citation_audit.adapter` wraps [@ekontoTURBO/thesis-citation-audit](https://github.com/ekontoTURBO/thesis-citation-audit) (Eryk's own Claude Code skill) as a subprocess
   - One Haiku per subsection, dispatched via `ClaudeCLI` (so no API key needed)
   - Uses the skill's `extract_thesis.py` / `split_sections.py` / `merge_report.py` scripts + the proven `section_prompt.md` template verbatim
   - Each Haiku flags `⚠️ STRONA` / `❌ TREŚĆ` / `❓ BRAK ŹRÓDŁA` / `🔴 BIBLIOGRAFIA` per the skill's legend
3. **`tg orchestrate-fixes`** — Opus reads every Haiku report, extracts structured fixes
   - New module `thesis_generator.citation_audit.orchestrator` implements the analyst-then-builder pattern (brief Pattern 4)
   - Opus call per problematic section, plus one final synthesis call for a thesis-wide executive summary
   - Output: `_state/citation_fixes.json` with `(section, paragraph, original, cited_as, flag, hint)` per fix
4. **NotebookLM correction pass** — second NotebookLM query with a *different* prompt
   - New module `thesis_generator.notebooklm.correction` with `CitationFix`, `build_correction_prompt`, `parse_corrections`, `request_corrections`
   - Correction prompt explicitly bans free-form expansion — only "PRZED: ... PO: ... KOMENTARZ: ..." replacement format
   - One NotebookLM call per affected section (parallelized via the adapter's semaphore)

**End-to-end orchestrator:** `tg notebook-pipeline <project> [--skip step1,step2,...]` runs all 4 in sequence, persists every artifact (drafts, audit reports, fix JSON, corrections) under `_state/` and `_reports/`.

**Wizard updated** — after picking a NotebookLM library, the setup wizard now shows a yellow Panel reminding the user to paste the system prompt from `docs/notebooklm_system_prompt.pl.pdf` into NotebookLM Settings → System Instructions.

**System prompt PDF shipped in repo** — `docs/notebooklm_system_prompt.pl.pdf` (77 KB) is the proven prompt the original session used. Polish version; translate for English theses.

### Added — Credits for thesis-citation-audit skill

The Haiku audit swarm in step 2 is powered by Eryk Czekalski's own [`thesis-citation-audit`](https://github.com/ekontoTURBO/thesis-citation-audit) Claude Code skill. Credit is surfaced in:

- `README.md` Acknowledgements (alongside PleasePrompto's NotebookLM skill)
- `thesis_generator/citation_audit/__init__.py` module docstring
- This changelog

### Added — Interactive setup wizard (`tg setup`)

New top-level command walks first-time users through every onboarding step:

1. System checks — Python version, `claude` CLI authentication status, NotebookLM skill installation + auth status
2. Project location — prompts (or accepts as arg)
3. Thesis basics — title, author, school, promotor, language, citation style
4. NotebookLM library — auto-discovers libraries from the skill's `library.json`, lets user pick / paste a new URL / skip
5. Scaffolds the full `inputs/` tree (10 folders with README explaining each)
6. Shows a "drop your files here" table
7. Runs `tg verify-env` and prints a ready/next-steps panel

Idempotent — re-running on an existing project keeps user edits and only updates what was changed in the prompts.

### Added — Credits for the NotebookLM Claude Code Skill

Ring C verification is powered by [@PleasePrompto](https://github.com/PleasePrompto)'s [NotebookLM Claude Code Skill](https://github.com/PleasePrompto/notebooklm-skill) (MIT, 2025). Credit is now surfaced in:

- `README.md` — new Acknowledgements section
- `docs/NOTEBOOKLM.md` — credit header above the setup instructions
- `thesis_generator/notebooklm/__init__.py` — module docstring credit
- This changelog

### Added — Visuals pipeline (tables, charts, illustrations + Spis tabel/rysunków)

New module `thesis_generator.visuals` implements the visual-materials mechanic
from the user's NotebookLM system prompt + the proven session's
`generate_charts.py`, `insert_v75_images.py`, and `uniform_tables.py` scripts.

**Inline markers** the writer drops in the draft text:

    [TABELA 1: title][Źródło: ...][Dane: file.xlsx sheet=H1 cells=B2:F7]
    [WYKRES 1: title][Źródło: opracowanie własne][Dane: ...][Typ: bar|line|pie|scatter]
    [ILUSTRACJA 1: title][Źródło: ...][Plik: visuals/foo.png][Szerokość: 11cm]
    [SUGEROWANY WYKRES: title][Opis: ...]            # placeholder

**`tg visuals <project>`** runs the pipeline end-to-end:
1. Parses every marker (Polish + English keys both accepted).
2. Assigns sequential numbers in document order (separate sequences for tables vs figures).
3. WYKRES → matplotlib chart (Navy/Gray/Accent palette, 200 DPI, serif font) saved to `output/_charts/`.
4. TABELA → loaded from Excel range, styled (D9D9D9 header, Arial 10pt, black borders).
5. ILUSTRACJA → user-supplied PNG/JPG with caption + source.
6. Styles every table uniformly (catches manually-pasted tables too).
7. Appends `Spis tabel` + `Spis rysunków` before BIBLIOGRAFIA.

Writer system prompt now teaches the marker syntax and explicitly bans meta
phrases like "jak przedstawiono w tabeli" / "co obrazuje rysunek" per the
NotebookLM system prompt.

New `inputs/visuals/` folder in `tg init` scaffold for user-supplied images.

4 new smoke tests pin the marker parser, registry numbering, chart rendering,
and uniform table styling. Live e2e on a 3-marker stub draft: 3/3 inserted,
table + chart + image all in the final docx, Spisy generated.

### Added — Word-document repair (full port from proven session)

`docx_ops.repair.repair_docx` now implements the complete two-pass fix for the
Ctrl+F9 wrap disaster (brief gotcha #5):

- **Pass A** — `<w:instrText>` → `<w:t>` conversion for orphaned text wrapped
  as field-code instructions. Preserves legitimate fields (TOC, PAGE, PAGEREF,
  HYPERLINK, SEQ, REF, STYLEREF, NUMPAGES).
- **Pass B** — removes outer `fldChar` shells at depth 0 that wrap arbitrary
  content (the "frame" left behind after Pass A).

Always writes a `<name>_corrupted_backup.docx` before touching the file. Verified
end-to-end with a synthetic corruption test (150 instrText elements wrapped in
a fake field shell → fully restored).

### Added — Conventional inputs/ folder layout

`tg init` now scaffolds the complete folder tree with `README.md` in each folder
explaining what goes there:

```
my-thesis/inputs/
├── draft.docx
├── sources/                 # academic literature (PDFs you cite)
├── research_data/
│   ├── surveys/             # CAWI/PAPI questionnaires (xlsx/csv/json)
│   ├── interviews/          # IDI/FGI transcripts (pdf/docx/md)
│   ├── observations/        # ethnography, field notes
│   └── existing/            # secondary data (GUS, industry reports)
├── school/
│   ├── regulation.docx      # formatting regulation
│   ├── brief.pdf            # promotor's task brief
│   └── templates/
└── notes/                   # anything else
```

`ThesisProject.effective_research_data_dir()`, `effective_interviews_dir()`,
`effective_school_dir()`, `effective_regulation()`, `effective_school_brief()`,
and `effective_research_data_files()` auto-discover this layout. Users only
need to set `draft` and `sources_dir` in `thesis.yaml`; everything else falls
back to the conventional paths when present.

### Improved — Ring C grounding prompt forces source-specific quoting

E2E showed that the previous grounding prompt let NotebookLM ramble about
adjacent topics — Trusov and Berger came back UNKNOWN because the grounded
content was actually about other library sources. The new prompt:

- Says **WYŁĄCZNIE na podstawie źródła: {name}**
- Explicitly forbids quoting other library sources
- Gives a 3-step structure (find → quote → judge)
- Provides an explicit "source doesn't contain this" escape path

### Documented — NotebookLM auth refresh cycle

`docs/NOTEBOOKLM.md` now documents the ~30-day browser session expiry and the
`tg notebooklm auth` refresh flow.

### Changed — major: LLM backend switched from Anthropic SDK to `claude -p`

The writer, Ring B (Haiku-per-source), independent reviewer, and Ring C judge step now shell out to the `claude` CLI in print mode instead of importing the Anthropic SDK. Removes the `ANTHROPIC_API_KEY` requirement — every LLM call rides on the user's existing Claude Code subscription auth.

- New module `thesis_generator.llm.ClaudeCLI` — subprocess wrapper around `claude -p` with sync/async APIs, bounded concurrency, `--json-schema` support, and `--max-budget-usd` safety caps.
- `env_check` now prefers the CLI path; ANTHROPIC_API_KEY is a documented fallback.
- Ring B Haiku verifiers use `--allowedTools "Bash"` so they can still run `pdfplumber` on cited PDFs (brief gotcha #3 preserved).
- Two-step Ring C: NotebookLM grounds → Haiku judges via CLI (no API key needed for the judge).
- 2 new smoke tests for the adapter; 16 total still pass.

### Fixed (from 2026-05-23 e2e test)
- Ring A regex now handles Polish `i in.` (= English `et al.`) in both parens and narrative citation forms.
- `NotebookLMAdapter._parse_verdict` is strict — requires `^VERDICT:` at line start, no longer false-positives on stray "OK" in prose.
- `humanize_docx` forbidden_words check uses stem matching, so `triangulacja` catches `triangulacji`, `triangulację`, etc.
- Ring C reports now include the raw NotebookLM response (in collapsed `<details>`) for debugging.

## [0.1.0] — 2026-05-23 — Alpha scaffold

Initial open-source scaffold extracted from a real, completed bachelor's-thesis
session that produced 14 versions across 11 days. The proven workflow is
documented in `THESIS_GENERATOR_BRIEF.md`.

### Added
- Pydantic project config (`ThesisProject`) loaded from `thesis.yaml`
- Hard-gate environment check (`tg verify-env`) — fails loudly on missing inputs, ambiguous filenames, missing API keys, NotebookLM auth
- Source + style inventory (`tg inventory`) — recursive PDF indexing, style fingerprint extraction
- Three-ring verification system:
  - Ring A: internal regex/python-docx (citations vs bibliography, em-dash count, alphabetization)
  - Ring B: parallel Haiku-per-source (each verifier uses `pdfplumber`, not Read)
  - Ring C: NotebookLM source-grounded cross-check via the `notebooklm` Claude Code skill adapter
- Raw-data audit (`tg audit-data`) — recomputes numeric claims against raw Excel
- Independent reviewer (`tg review`) — zero-context Opus, "strict but fair professor", grade 2.0–5.0
- Humanization pass (`tg humanize`) — em-dash removal, forbidden-word flagging
- Five orchestration patterns documented + parameterized:
  independent-reviewer / one-per-source / sonnet-rewriter-swarm /
  analyst-then-builder / JSON-decision-file
- Rolling progress report (`_reports/PROGRESS.md`) — disaster-recovery state
- Full CLI (`thesis-generator` / `tg`) with `init`, `verify-env`, `inventory`,
  `verify`, `review`, `audit-data`, `humanize`, `run`, `notebooklm`
- Smoke test suite (`tests/test_smoke.py`)

### Known limitations
- Word COM PDF export is not yet implemented (`output.pdf` is a no-op)
- The `repair_docx` Ctrl+F9-disaster fix is diagnose-only; auto-unwrap is TODO
- Section writer requires programmatic invocation; no CLI `write` command yet
- NotebookLM skill must be installed separately (not bundled)
- Only Polish APA 7 fully supported; English templates included but untested at scale

### Brief reference
- Source session: `e54b3e7a-833a-4507-a785-ebb757360999.jsonl` (12 MB, 3815 records)
- Mined into: `THESIS_GENERATOR_BRIEF.md` (3617 words, 10 sections, 15 gotchas)
- Final session output: `Praca_licencjacka_Eryk_Czekalski.docx/.pdf` — reviewer grade 4.5
