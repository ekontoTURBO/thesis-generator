---
name: thesis-generator
description: Use when user wants to write a bachelor's thesis from scratch, audit an existing finished thesis against its sources, or do both. Orchestrates NotebookLM as the source-grounded writer, dispatches Haiku swarms to verify every citation against PDF page numbers, runs an Opus statistician that recomputes every claim in a parallel Excel workbook, and produces a graded reviewer report — all in one Claude Code session via Agent tool. Polish + English theses. NO Anthropic API key needed — uses your Claude Code subscription.
argument-hint: [audit|generate|setup] [project_dir | draft_path]
disable-model-invocation: true
---

## What This Skill Does

Three modes in one orchestrator:

1. **audit** — verify an EXISTING finished thesis without writing or mutating it. Catches wrong page numbers, mis-attributed claims, missing source files, off-by-N numbers, bibliography mismatches, over-interpreted hypotheses, AI tells, formatting drift.
2. **generate** — write a new thesis subchapter-by-subchapter via NotebookLM, then audit the citations, then have NotebookLM correct itself.
3. **setup** — interactive first-run wizard for either mode (recommended for new users).

This skill is the ORCHESTRATOR. All deterministic operations (file I/O, regex, docx mutation, Excel parsing, chart generation) live in the `thesis_generator` Python package which exposes a `tg` CLI. The skill calls `tg` via Bash for the heavy plumbing and dispatches `Agent` (Haiku/Opus) for the work that needs reasoning.

**Side effects:** writes ~10-30 markdown reports + 1-2 xlsx workbooks + per-section state files into `<project>/_reports/`, `<project>/_state/`, `<project>/output/`. The user's `inputs/draft.docx` is NEVER mutated in audit mode; in generate mode mutations go to `output/Praca.docx` (the original draft is the seed, not the target). Dispatches many parallel Haiku sub-agents — real token cost. `disable-model-invocation: true` ensures only the user can fire this.

## When to Use This Skill

Trigger when the user:
- Asks to verify, audit, check, or review a finished thesis
- Asks to write, generate, or build a thesis from sources
- Mentions citation checking, page-number verification, statistics audit
- Mentions Polish thesis (`praca licencjacka`, `praca magisterska`) or English bachelor's/master's thesis
- Drops a `draft.docx` or `praca_*.docx` and asks "what's wrong with this?"
- Uses phrases like "thesis pipeline", "audit my thesis", "weryfikacja pracy", "audyt cytowań"

Skip when:
- The work is a journal article, blog post, or other non-thesis academic writing — the workflow assumes thesis structure (chapters, subsections, bibliography, hypotheses)
- The user just wants a quick citation check on 1-2 references — use `Read` + `WebFetch` directly
- No `tg` CLI is installed — tell them to `pip install -e .` from the repo

## Required Inputs

Three positional arguments:

1. **$1 — mode**: `audit` | `generate` | `setup`. If missing, ask via `AskUserQuestion`.
2. **$2 — project_dir | draft_path**: full path to either an existing thesis-generator project folder, OR (in audit mode) a path to a standalone `.docx` to wrap. If missing, ask.
3. **$3 — optional sources_folder**: only needed in audit mode when wrapping a standalone docx (no `inputs/sources/` exists yet).

Validate every path exists before any work.

## Dependencies

Check BEFORE doing any work — if missing, tell the user how to install and stop:

- **`tg` CLI on PATH** — verify with `which tg`. If missing: tell user to `cd /path/to/thesis-generator && pip install -e .`.
- **`claude` CLI authenticated** — verify with `claude --print --model haiku "test"`. If `Not logged in`, tell user to run `claude /login`. (The wrapped Python pipeline ALSO uses `claude -p` internally for the long-form Opus/Haiku calls that don't need shared context.)
- **NotebookLM skill at `~/.claude/skills/notebooklm/`** by [@PleasePrompto](https://github.com/PleasePrompto/notebooklm-skill) — required for steps that talk to NotebookLM. Verify the folder exists.
- **`thesis-citation-audit` skill at `~/.claude/skills/thesis-citation-audit/`** — required for the Haiku swarm audit. Verify the folder exists.
- **`pdftotext` (Poppler) on PATH** — required by Haiku sub-agents to verify PDFs. Verify with `which pdftotext`.

If any is missing, stop and tell the user with the exact install command.

## Workflow — AUDIT mode

Use when the user already has a finished thesis and just wants the most thorough quality report possible. **Never mutate the draft.**

### Step 1 — Confirm task + paths

Restate to user: "Auditing thesis `<path>` against sources at `<path>` — no part of the draft will be modified. Will produce a consolidated report at `<project>/_reports/THESIS_AUDIT.md`."

If user passed a bare `.docx` path (not a project folder), ask via `AskUserQuestion` where their sources folder is.

### Step 2 — Project setup

Use `TaskCreate` with this plan:

1. Verify deps + paths
2. Scaffold project + symlink user files
3. Inventory + Ring A (fast, parallel)
4. Citation audit (Haiku swarm — parallel)
5. Opus orchestrator (fix list synthesis)
6. Numbers recompute (Opus — independent xlsx)
7. Hypothesis consistency (Opus)
8. Independent reviewer (Opus, zero-context)
9. Consolidated report

Mark task 1 in_progress. If the user's path is already a thesis-generator project (has `thesis.yaml`), skip to step 3. Otherwise:

```bash
tg setup "<project>" --non-interactive --audit-mode
```

Then symlink or copy the user's draft + sources into `<project>/inputs/`. Use symlinks on Linux/macOS, file copies on Windows (Windows symlinks need admin).

### Step 3 — Inventory + Ring A (parallel via Bash)

```bash
tg inventory "<project>"
tg verify "<project>" --rings A
```

Read the resulting `<project>/_state/inventory.json` + `<project>/_reports/ring_a_internal.md` so you have the citation list + bibliography drift in your context for later steps.

### Step 4 — Citation audit (Haiku swarm via Agent tool — IMPORTANT)

This is the critical step. The proven session dispatched 10-24 parallel Haikus directly via the `Agent` tool in a single Claude Code session — NOT via `claude -p` subprocess. Do the same here.

For each subsection in `<project>/_state/citation_audit/sections/_index.json` (created by the `tg` pipeline OR by running `tg audit-citations` once for the bootstrap), dispatch one `Agent` call with:
  - `subagent_type: general-purpose`
  - model hint in the prompt body: "Use Haiku."
  - prompt from `templates/citation_audit_section.md` (this folder)
  - parameter substitution: `{{section_id}}`, `{{section_file}}`, `{{sources_folder}}`, `{{bibliography_file}}`, `{{report_path}}`
  - `run_in_background: true` for all but the last so progress notifications come in async

Fire in waves of 6-8 at a time. As each completes, mark it in the TaskCreate plan. The Haiku sub-agents use `Bash` + `pdftotext` to verify pages — they will NOT use `Read` on big PDFs (gotcha #3 from the brief).

Each sub-agent writes its report directly to disk; you don't need to capture the agent's text output.

### Step 5 — Opus orchestrator synthesis (in-context, no subagent)

YOU (the orchestrator, running on Opus) read every section report under `<project>/_state/citation_audit/reports/`. Walk them carefully — look for patterns (e.g. "every Heilman citation has same year mismatch → systematic error").

Produce a structured fix list and write it as `<project>/_state/citation_fixes.json`:

```json
[
  {"section_id": "1.2", "paragraph_tag": "P0042",
   "original_sentence": "...", "cited_as": "(Hoch, 2002, s. 137)",
   "flag": "⚠️ STRONA", "correction_hint": "actual claim is on s. 142"},
  ...
]
```

Then write `<project>/_reports/citation_audit_synthesis.md` with the executive-summary block: critical issues, bibliography mismatches, file mismatches, page drift, patterns, prioritized recommendations.

### Step 6 — Numbers recompute (Opus subagent with Bash)

Dispatch ONE `Agent` call (Opus, `allowedTools: ["Bash", "Read", "Write"]`) with the prompt from `templates/numbers_recompute.md`. The agent will:
1. Read `<project>/_state/extracted_claims.json` (produce it first via `tg extract-claims "<project>" --json`)
2. Open the raw research-data files (paths listed in `thesis.yaml`)
3. Write its own Python at `<project>/_state/recompute_script.py`
4. Run it via Bash
5. Save parallel xlsx at `<project>/output/_audits/recompute_audit.xlsx`
6. Return JSON-Lines diffs

Read the agent's response. Persist the diffs to `<project>/_state/recompute_diffs.json` and write `<project>/_reports/numbers_recompute.md`.

### Step 7 — Hypothesis consistency (Opus, in-context)

If the draft has H1/H2/H3 declarations (check via `tg extract-hypotheses "<project>" --json`), YOU (Opus orchestrator) read:
- The hypothesis statements + author's claimed verdicts
- The recomputed diffs from step 6

Judge each hypothesis: `SUPPORTED | NOT_SUPPORTED | PARTIALLY | OVER_INTERPRETED | INSUFFICIENT_DATA`. Write `<project>/_reports/hypothesis_consistency.md`.

### Step 8 — Independent reviewer (zero-context Opus subagent)

Dispatch ONE `Agent` call (Opus, NO `allowedTools` — pure text). The prompt is from `templates/independent_reviewer.md`. Pass ONLY the thesis text + (optional) school regulation. Critical: do NOT pass any context about how the thesis was produced, prior audit findings, or session history. This is the fresh-eyes pass.

Read the response, parse grade (2.0–5.0) + top problems, write `<project>/_reports/independent_reviewer.md`.

### Step 9 — Render consolidated report

```bash
tg render-audit-report "<project>"
```

This stitches every per-phase report into `<project>/_reports/THESIS_AUDIT.md` with executive summary on top.

### Step 10 — Brief user

Report:
- Path to the consolidated report
- Headline numbers: total citations checked, % OK, count of critical issues
- Reviewer grade
- Top 3 most urgent fixes
- "Run `/thesis-generator generate` to apply the Opus orchestrator's fix list via NotebookLM" if they want auto-correction

## Workflow — GENERATE mode

Use when writing a new thesis from sources. Same orchestration pattern but starts with NotebookLM writing each subsection.

### Step 1 — Confirm task + collect section specs

Ask via `AskUserQuestion`:
- Which sections does the user want to write today? (e.g. "4.1, 4.2, 4.3")
- For each: title + 2-5 sentences describing scope + which priority sources to use

### Step 2 — NotebookLM writes each section (sequential)

For each section spec, dispatch the `notebooklm` skill via Bash:

```bash
tg notebook-write "<project>" --section <id> --title "<title>" --focus "<focus>" --sources "<comma-sep>"
```

This calls NotebookLM with the user's configured system prompt and saves the section to `<project>/_state/notebook_section_<id>.md`. Show the user the result; ask if they want to continue or revise.

### Step 3 — Assemble + audit + correct (= AUDIT workflow steps 3-9)

Once sections are written, run the AUDIT workflow steps 3-9 to verify them. Then:

### Step 4 — NotebookLM correction pass

For each section that has fixes in `_state/citation_fixes.json`, dispatch:

```bash
tg notebook-fix "<project>" --section <id> --fixes _state/citation_fixes.json
```

NotebookLM produces "PRZED → PO" replacement sentences. YOU apply them via:

```bash
tg apply-edits "<project>" --json <section_corrections.json>
```

### Step 5 — Final pass (visuals, humanize, reviewer)

```bash
tg visuals "<project>"           # process TABELA/WYKRES/ILUSTRACJA markers
tg humanize "<project>"          # strip em-dashes, flag forbidden words
tg review "<project>"            # independent reviewer grade
```

## Workflow — SETUP mode

Just run the wizard:

```bash
tg setup "<project_dir>"
```

It branches AUDIT vs GENERATE internally based on the user's first answer, so this skill mode is mostly a thin wrapper for new users who don't know which mode they want.

## Critical guardrails

- **NEVER mutate the user's draft in audit mode.** If `tg audit` would touch the original, that's a bug — file it.
- **NEVER hallucinate citation verdicts.** If a sub-agent can't open a PDF, status is ❓ BRAK ŹRÓDŁA — never invent.
- **Tool routing**: prefer the `Agent` tool over `claude -p` subprocess wherever possible. Subprocess is the fallback for when we need a fresh isolated context (e.g. the Opus recomputer that writes its own Python and shells out — that one is genuinely a subprocess because the inner Bash use case needs full freedom).
- **Concurrent agents**: max 8 in flight at once. The proven session hit 24 and bumped into rate limits; 8-12 is the safe band.
- **Cost discipline**: a full deep audit (steps 3-9) is ~$3-8 in tokens. A shallow audit (Ring A + visuals + humanize only) is < $0.10. Default to deep; recommend shallow if user mentions cost.
- **Polish ↔ English**: detect the thesis language from the inventory's style fingerprint and propagate it to every Haiku prompt + reviewer prompt. Mismatch (Polish thesis, English Haiku reports) confuses the merged report.

## Supporting Files

- `scripts/install.sh` — one-liner installer for this skill (copies to `~/.claude/skills/`)
- `templates/citation_audit_section.md` — Haiku prompt for one subsection's citation verification (mirrors the `thesis-citation-audit` skill template)
- `templates/numbers_recompute.md` — Opus prompt for independent statistical recomputation
- `templates/independent_reviewer.md` — zero-context Opus prompt for the strict-professor grader
- `templates/correction_pass.md` — NotebookLM correction-mode prompt

## Related skills

- [`notebooklm`](https://github.com/PleasePrompto/notebooklm-skill) by Please Prompto — REQUIRED. Source-grounded query engine.
- [`thesis-citation-audit`](https://github.com/erykczekalski/thesis-citation-audit) by Eryk Czekalski — REQUIRED for AUDIT step 4. Per-section Haiku citation verifier.
