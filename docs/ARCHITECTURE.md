# Architecture

## Mental model

This is **not** an "AI thesis writer." It is a **verification pipeline with a writer at the front**. The writer is never trusted: every paragraph goes through three independent verification rings before it can ship, and a fourth zero-context reviewer produces a numeric grade that gates the export.

## Layered structure

```
┌────────────────────────────────────────────────────────────────┐
│  CLI / Programmatic API   (thesis_generator.cli, .pipeline)    │
├────────────────────────────────────────────────────────────────┤
│  Pipeline orchestrator   (thesis_generator.pipeline)           │
│      env_check → inventory → write → verify → review → ship    │
├────────────────────────────────────────────────────────────────┤
│  Phase modules                                                 │
│   env_check        inventory      writer                       │
│   verify/internal  verify/haiku   verify/notebooklm_ring       │
│   verify/data_audit                                            │
│   review/independent                                           │
│   docx_ops/humanize  docx_ops/repair  docx_ops/apply_edits     │
│   reports/progress                                             │
├────────────────────────────────────────────────────────────────┤
│  Orchestration primitives  (orchestration/patterns.py)         │
│   independent_reviewer | one_per_source | sonnet_rewriter      │
│   analyst_then_builder | json_decision_file                    │
├────────────────────────────────────────────────────────────────┤
│  External adapters                                             │
│   llm.ClaudeCLI (subprocess `claude -p`, OAuth, default)       │
│   anthropic SDK (optional, legacy — set ANTHROPIC_API_KEY)     │
│   notebooklm (Claude Code skill, subprocess + browser)         │
│   python-docx   pdfplumber   openpyxl   pywin32 (optional)     │
└────────────────────────────────────────────────────────────────┘
```

## Why subprocess for LLM calls

The original architecture used the Anthropic SDK directly with `ANTHROPIC_API_KEY`. The CLI-subprocess path replaces that because:

- **No API key onboarding.** A first-time user of this tool already has Claude Code installed. Asking them to also sign up for the developer console, set up billing, and export an env var is a hard onboarding gate. `claude -p` reuses their existing subscription auth via OAuth/keychain.
- **Same model access.** `--model opus|sonnet|haiku` works identically.
- **Tool use comes for free.** Ring B Haiku needs `bash` access to run `pdfplumber` on cited PDFs. `claude -p --allowedTools "Bash"` enables exactly that, scoped to one subprocess.
- **Structured output.** `--json-schema` enforces the writer's `{text, used_citations, notes}` contract.
- **Budget cap.** `--max-budget-usd` is a per-call safety net.
- **Concurrency = N processes.** No shared client state to leak between async tasks. Bounded by `ClaudeCLI(max_concurrent=N)`.

Trade-off: each call has ~2-5s process-startup overhead. For a thesis pipeline that takes tens of minutes, this is in the noise. For high-frequency low-latency apps the SDK is still the right choice.

## State model — everything is a file

The proven session made one deliberate choice: **no database, no service, no background daemon**. Every artifact is a regular file under the project directory. A student must be able to inspect, edit, and back up any intermediate state with normal tools.

```
my-thesis/
├── thesis.yaml                  # the single config source of truth
├── inputs/                      # user-provided, NEVER modified by the tool
│   ├── draft.docx
│   ├── sources/*.pdf
│   ├── survey_responses.xlsx
│   └── regulation.docx
├── _state/                      # tool-managed, machine-readable
│   ├── inventory.json
│   ├── section_4.1.txt
│   ├── progress_history.json
│   └── *_edits.json
├── _reports/                    # tool-managed, human-readable
│   ├── PROGRESS.md              # rolling state — read this to resume after a crash
│   ├── env_check.md
│   ├── ring_a_internal.md
│   ├── ring_b_haiku_per_source.md
│   ├── ring_c_notebooklm.md
│   ├── data_audit.md
│   ├── independent_reviewer.md
│   └── humanize.md
└── output/                      # the final artifact
    ├── Praca.docx
    ├── Praca.pdf
    └── _versions/
        ├── Praca_v1.docx
        └── Praca_v2.docx
```

## Concurrency model

Three concurrency strategies live in the pipeline:

1. **Sequential** — env_check, inventory, independent reviewer, ship. Each one's output feeds the next.
2. **Bounded parallel** — verify rings B and C run N citations concurrently with `asyncio.Semaphore`. Brief observation: >24 parallel Haikus hits Anthropic rate limits; default is 12.
3. **Section-by-section** — writer.py is *intentionally* sequential. The user wants to see and approve each subsection before the next starts. This is a feature, not a limitation.

## Why subprocess for NotebookLM

NotebookLM has no public API. The Claude Code skill drives a headless browser session. Talking to it via subprocess (rather than importing it as a library) means:
- A crashed browser session can't take down our orchestrator
- Auth state lives in the skill's own files — we don't have to manage Google OAuth ourselves
- The skill can evolve independently of this package

The tradeoff: each query spawns a Python process and a browser. Latency is 30s–5min per query, not 200ms. That's why we cap parallel queries at 3 and run Ring C bounded-parallel in the background.

## Failure model

| Phase | If it fails, the pipeline… |
|---|---|
| env_check | **Aborts hard.** Missing inputs = nothing else can run. |
| inventory | Aborts hard. Verifiers depend on the index. |
| Ring A | Continues. Failure becomes a finding in the report. |
| Ring B | Continues. Per-citation failures land in the report; pipeline-wide network errors are caught. |
| Ring C | Continues. NotebookLM auth/timeout is reported, not crash. |
| Data audit | Continues. Heuristic flags only — never auto-fixes. |
| Independent reviewer | Continues. Missing grade becomes a note in the report. |
| Humanize | Continues. Forbidden words are reported, not auto-rewritten. |
| Ship | **Aborts hard if grade < `pipeline.fail_on_grade_below`.** |

This matches the proven session's pattern: verify everywhere, fail loudly, but let the human make the final call on borderline issues.
