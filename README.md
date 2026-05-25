# thesis-generator

> Open-source CLI that writes, verifies, and audits a complete bachelor's thesis from your sources, your data, and your NotebookLM library — using a multi-agent orchestration loop where **the writer is never trusted**.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)]()

## What it does

You provide:
- 📄 Your existing thesis draft (`.docx`) — even if it's only the introduction
- 📚 A folder of PDF sources you've collected
- 📊 Raw research data (Excel/CSV) — survey responses, interview transcripts, etc.
- 📋 The school's formatting regulation (`Zarządzenie ... załącznik 3` for Polish unis)
- 🔗 A **NotebookLM** library URL containing the same sources (the verification engine)
- 📝 A short brief describing what you still need to write

You get:
- ✅ A fully-formatted, source-verified `.docx` (and optional `.pdf`) ready for your promotor
- ✅ A full audit trail in `_reports/` — every citation verified, every number recomputed from raw data, every reviewer claim cross-checked
- ✅ An independent-reviewer report with a numeric grade (2.0–5.0)
- ✅ A versioned history so you can roll back any change

## Why it works (the core insight)

This is not "AI writes a thesis." It is **NotebookLM writes source-grounded prose; a Haiku swarm and Opus orchestrator catch what NotebookLM gets wrong; then NotebookLM rewrites the wrong bits.**

### The 4-step primary pipeline (`tg notebook-pipeline`)

1. **NotebookLM writes** each subsection step-by-step — one focused prompt per subchapter, using the system prompt you configure in NotebookLM (see [Required NotebookLM system prompt](#required-notebooklm-system-prompt) below). NotebookLM is good at writing source-grounded APA-cited prose because it actually reads your library.
2. **Haiku swarm audits citations** — wraps [@erykczekalski's `thesis-citation-audit` skill](#acknowledgements). One Haiku per subsection, uses `pdftotext` to open the actual PDF, checks PDF page vs printed page offset, flags `⚠️ STRONA` / `❌ TREŚĆ` / `❓ BRAK ŹRÓDŁA` / `🔴 BIBLIOGRAFIA`. NotebookLM gets pages and exact attribution wrong sometimes — this is where the swarm earns its keep.
3. **Opus orchestrator** reads every Haiku report, asks targeted follow-ups, and produces a structured fix list (analyst-then-builder pattern from the proven session). Output: `_state/citation_fixes.json`.
4. **NotebookLM second pass** — correction mode. A *different* prompt feeds NotebookLM the fix list and asks for "PRZED → PO" replacement sentences with the right pages and attributions.

### Plus the original verification rings (still available, complementary)

`tg verify --rings A,B,C` runs the original three rings as a backstop:

- **Ring A — Internal**: regex + `python-docx` self-checks (orphan citations, bibliography drift, em-dashes, formatting compliance)
- **Ring B — Haiku per source**: simpler than the audit swarm, one Haiku per cited PDF
- **Ring C — NotebookLM source-grounded cross-check** (two-step: NotebookLM grounds, Haiku judges)

Plus a **raw-data auditor** that recomputes every M, %, χ², t, p, d from your raw Excel — and an **independent reviewer** (a subagent with zero context) prompted as a strict professor.

## Two modes of use

### Mode 1 — Generation (write + verify + ship)

You're starting from a partial draft + sources + research data, and you want the tool to write the missing sections, verify everything, and produce a final docx.

```bash
tg setup my-thesis             # interactive wizard
# (drop your sources, research data, etc. into the scaffolded folders)
tg notebook-pipeline my-thesis # 4 steps: write → audit → orchestrate → correct
```

### Mode 2 — Audit (read-only verification of a finished thesis)

You already have a finished thesis (written by you, by ChatGPT, by a co-author — doesn't matter) and you just want the most thorough quality report possible. **No writing, no mutation, no corrections applied** — just diagnostics.

```bash
tg setup my-audit              # scaffolds the folder structure
# drop your existing thesis.docx + sources/*.pdf + research_data/*.xlsx
tg audit my-audit              # full read-only verification
```

What the audit runs (every phase read-only or operates on a temp copy):

| Phase | What it catches |
|---|---|
| `env_check` | Missing inputs, auth, env vars |
| `inventory` | Maps every source PDF to author/year keys |
| Ring A (regex) | Orphan citations, bibliography drift, em-dashes |
| Citation audit (Haiku swarm) | Wrong page numbers, mis-attributed claims, missing source files, bibliography ↔ text mismatches |
| Opus orchestrator | Synthesizes Haiku findings into a prioritized fix list with concrete correction hints |
| Data audit (heuristic) | Numeric claims that don't match raw Excel cells (fast regex pass) |
| **Numbers recompute (Opus)** | Independent Opus auditor writes its own Python, opens raw data, recomputes EVERY M/SD/χ²/t/p/d/% from scratch, saves a parallel `output/_audits/recompute_audit.xlsx`, diffs against the draft |
| **Hypothesis consistency (Opus)** | Reads H1/H2/H3 declarations + the recomputed numbers → verdict per hypothesis: `SUPPORTED / NOT_SUPPORTED / PARTIALLY / OVER_INTERPRETED / INSUFFICIENT_DATA` |
| Independent reviewer (Opus, zero-context) | Top-5 problems + grade 2.0–5.0 |
| Visuals register | Table + figure count + Spis tabel/rysunków readiness |
| AI-tells check (dry-run humanize) | Em-dashes + forbidden buzzwords (flagged, not removed) |

Output: a single consolidated `_reports/THESIS_AUDIT.md` with executive summary, per-section problems, suggested fixes, and reviewer report. Plus per-phase reports in `_reports/` for drill-down.

```bash
tg audit my-thesis --shallow   # skip the slow LLM phases (citation swarm, reviewer)
tg audit my-thesis --skip data,reviewer  # custom skip list
```

> **For full corrections applied:** after `tg audit`, optionally run `tg notebook-pipeline --skip write` to apply the Opus-orchestrator's fix list via NotebookLM's correction pass. The audit gives you the diagnosis; the pipeline applies the cure.

## Required NotebookLM system prompt

> ⚠️ **Set this BEFORE running `tg notebook-pipeline`** — without the right system prompt, NotebookLM gives conversational answers instead of APA-formatted thesis text.

1. Open your NotebookLM notebook at <https://notebooklm.google.com>
2. Click **Settings** (gear icon) → **System Instructions**
3. Paste the contents of [`docs/notebooklm_system_prompt.pl.pdf`](docs/notebooklm_system_prompt.pl.pdf)
4. Save

The system prompt establishes: APA 7 format, "introduce authors in the sentence" pattern, no meta phrases, mandatory citation tool usage, visual material markers, bibliography format. The per-section prompts that `tg notebook-write` sends are intentionally short because the global behavior lives in this system prompt.

If you write in English, translate the prompt — the structure stays the same.

## Quick start

You have two ways to run this. **The skill path is the recommended one** — it orchestrates everything in a single Claude Code session via the native `Agent` tool, just like the proven workflow that built it.

### Recommended — install as Claude Code skill (native orchestration)

```bash
git clone https://github.com/ekontoTURBO/thesis-generator.git
cd thesis-generator
pip install -e .
tg install-skill                # symlinks (or copies on Windows) skill/ → ~/.claude/skills/thesis-generator/
```

Then from any Claude Code session:

```
/thesis-generator audit /path/to/my-thesis           # verify an existing finished thesis
/thesis-generator generate /path/to/my-new-thesis    # write from scratch
/thesis-generator setup                              # interactive first-run wizard
```

The skill dispatches Haiku swarms via the native `Agent` tool (not subprocess), runs in your current terminal, uses your Claude Code subscription, and you see every step happen in real time.

### Alternative — standalone Python CLI

If you don't want to use Claude Code as the runtime, the Python CLI works standalone (it shells out to `claude -p` under the hood, so you still need Claude Code installed, but it runs end-to-end without a Claude Code session):

```bash
tg setup                        # interactive wizard — branches AUDIT vs GENERATE vs MIXED
tg audit /path/to/my-thesis     # audit-only
tg notebook-pipeline /path/to/my-thesis  # generate + audit + correct
```

The wizard does:

1. **System checks** — Python, `claude` CLI auth status, NotebookLM skill install + auth
2. **Project location** — picks where the thesis lives
3. **Thesis basics** — title, author, school, promotor, language, citation style
4. **NotebookLM library** — auto-discovers libraries you already have, or lets you paste a URL
5. **Scaffolds** the full `inputs/` tree (10 folders, each with a README explaining what goes there)
6. Shows you exactly **where to drop your files**
7. Runs `tg verify-env` to confirm everything's green

Then, once you've dropped your draft + sources + research data:

```bash
tg verify-env my-thesis      # green-light env check
tg inventory my-thesis       # index source PDFs + extract style fingerprint
tg verify my-thesis --rings A # Ring A internal audit (instant, free)
tg verify my-thesis --rings B # Ring B Haiku per-source (uses claude -p)
tg review my-thesis          # zero-context Opus reviewer with grade 2-5
tg visuals my-thesis         # insert tables/charts/images from [TABELA/WYKRES/...] markers
tg humanize my-thesis        # strip em-dashes, flag forbidden words
tg run my-thesis             # all of the above in sequence
```

> **Power user?** `tg init` is the bare-bones scaffold without prompts. `tg setup --non-interactive` accepts every default.

## Requirements

- **Python 3.11+**
- **Claude Code** installed (`claude` on PATH) and authenticated via `claude /login`. The pipeline shells out to `claude -p` in headless mode, so every LLM call rides on your existing Claude Code subscription — **no API key, no billing setup**. Uses Opus for writing/auditing/reviewing, Sonnet for rewrites, Haiku for per-source verification.
- **NotebookLM skill** installed in Claude Code (`~/.claude/skills/notebooklm/`) — wraps `python scripts/run.py ask_question.py`. See [docs/NOTEBOOKLM.md](docs/NOTEBOOKLM.md).
- **Windows**: optional `pywin32` for Word COM (PDF export, static TOC). On other OSes PDF export falls back to LibreOffice headless.

> **Legacy mode:** if you'd rather use the Anthropic SDK directly, set `ANTHROPIC_API_KEY` and `env_check` will fall back to it. The `claude` CLI path is the default because it removes the API-key onboarding step that blocks most students.

## Scope (alpha)

- ✅ Social sciences / economics / marketing (APA 7 citations: `(Autor, rok, s. XX)`)
- ✅ Polish-language theses (UI + reports), English templates included
- ✅ Quantitative (CAWI surveys) + qualitative (IDI transcripts) methodology
- ⏳ STEM theses with LaTeX (planned v0.3)
- ⏳ Medical / Vancouver citations (planned v0.3)
- ⏳ Web GUI (planned v0.2)

## Architecture

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/PIPELINE.md](docs/PIPELINE.md).

```
INPUTS                    ORCHESTRATOR (main session)                  OUTPUTS
─────                     ─────────────────────────                    ───────
draft.docx        ──►  ┌─► env-check                              ──►  Praca.docx
sources/*.pdf     ──►  │   inventory                              ──►  Praca.pdf
raw_data.xlsx     ──►  │   write    ─► [Sonnet × N parallel]      ──►  _reports/
zarządzenie.docx  ──►  │   verify   ─► [Haiku × N parallel]            ├ progress.md
NotebookLM URL    ──►  │            ─► [NotebookLM × N background]     ├ verification.md
brief.md          ──►  │            ─► [Opus × 1 data audit]           ├ data_audit.md
                       │   review   ─► [Opus × 1 zero-context]         ├ reviewer.md
                       └─► ship                                        └ run.log
```

## Read the brief

If you're contributing, read [`THESIS_GENERATOR_BRIEF.md`](THESIS_GENERATOR_BRIEF.md) first — it's the mined working session that proved this pipeline works, including 15 specific gotchas and the prompts that survived contact with reality.

## Acknowledgements

This tool would not exist without:

- **[NotebookLM Claude Code Skill](https://github.com/PleasePrompto/notebooklm-skill)** by **[Please Prompto!](https://github.com/PleasePrompto)** — the source-grounded engine that powers both the writer (step 1) and the correction pass (step 4). We wrap their skill as a subprocess; all the hard browser-automation, persistent-auth, and NotebookLM-integration work is theirs. MIT-licensed. There's also an [MCP variant](https://github.com/PleasePrompto/notebooklm-mcp) of the same idea if you'd rather wire NotebookLM into MCP clients.
- **[thesis-citation-audit Claude Code Skill](https://github.com/erykczekalski/thesis-citation-audit)** by **Eryk Czekalski** — the Haiku-per-section citation audit swarm in step 2. The skill's `extract_thesis.py` / `split_sections.py` / `merge_report.py` scripts + the `section_prompt.md` template do the heavy lifting; this package orchestrates them as a subprocess via `claude -p`.
- **[Anthropic](https://anthropic.com)** — Claude (Opus, Sonnet, Haiku via `claude -p`) is the writer / reviewer / verifier across the whole pipeline.
- **Google** — NotebookLM (Gemini under the hood) is the source-grounded LLM that anchors verification to your actual library, not training data.
- **[python-docx](https://python-docx.readthedocs.io/)**, **[pdfplumber](https://github.com/jsvine/pdfplumber)**, **[openpyxl](https://openpyxl.readthedocs.io/)**, **[matplotlib](https://matplotlib.org/)** — the heavy-lifters underneath every docx-mutation, PDF-read, Excel-recompute, and chart-render.

If you use this for your thesis, an acknowledgement in your work is appreciated but not required. Credit to Please Prompto for the NotebookLM skill is.

## License

MIT. Use it, fork it, ship it.

## Not legal/academic advice

This tool produces *drafts*. You are responsible for what you submit. Read everything. The independent-reviewer grade is a sanity check, not a guarantee.
