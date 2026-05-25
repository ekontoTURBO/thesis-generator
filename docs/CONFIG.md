# Configuration reference

Every project is one directory containing a `thesis.yaml`. The schema is enforced by Pydantic — invalid configs fail fast at `ThesisProject.load()`.

## Minimal example

```yaml
title: "Word-of-Mouth marketing w VR"
author: "Eryk Czekalski"
language: pl
citation_style: apa7

inputs:
  draft: inputs/draft.docx
  sources_dir: inputs/sources
  raw_data:
    - inputs/survey.xlsx

notebooklm:
  library_url: "https://notebooklm.google.com/notebook/abc-123"
  library_name: "VR WoM research"
```

## Full reference

### Top-level

| Key | Type | Default | Notes |
|---|---|---|---|
| `title` | str | required | Thesis title (used in writer system prompts) |
| `author` | str | required | Author name (used in ship-time metadata) |
| `school` | str | `""` | Optional, surfaced in reports |
| `promotor` | str | `""` | Optional |
| `language` | `pl` \| `en` | `pl` | Determines which prompt templates are used |
| `citation_style` | `apa7` \| `vancouver` \| `chicago` | `apa7` | Only `apa7` fully implemented in alpha |

### `inputs`

| Key | Type | Required | Notes |
|---|---|---|---|
| `draft` | path | yes | Existing .docx. Even an empty stub works. |
| `sources_dir` | path | yes | Folder with source PDFs. Recursed. |
| `raw_data` | `[path]` | no | Excel/CSV files with raw research data |
| `interviews_dir` | path | no | Folder with IDI transcript PDFs |
| `regulation` | path | no | School formatting regulation .docx |
| `school_brief` | path | no | Promotor's task brief PDF |
| `additional` | `[path]` | no | Anything else the writer should know about |

Paths can be absolute or relative to the project dir.

### `notebooklm`

Required if `pipeline.verification_rings` includes `"C"`.

| Key | Type | Default | Notes |
|---|---|---|---|
| `library_url` | str | required | `https://notebooklm.google.com/notebook/<UUID>` |
| `library_name` | str | required | Logged in audit reports |
| `max_words_per_query` | int | 400 | NotebookLM truncates above this silently |
| `parallel_queries` | int | 3 | >3 destabilizes the browser automation |
| `timeout_seconds` | int | 300 | Per-query timeout |

### `models`

Routes each role to a Claude model. Defaults match the proven session.

```yaml
models:
  writer: claude-opus-4-7              # writes new chapters
  auditor: claude-opus-4-7             # raw-data + bibliography audit
  reviewer: claude-opus-4-7            # zero-context independent review
  rewriter: claude-sonnet-4-6          # shortening, language polish (needs taste)
  verifier_per_source: claude-haiku-4-5-20251001  # Ring B parallel verifiers
```

### `humanization`

| Key | Type | Default | Notes |
|---|---|---|---|
| `remove_em_dashes` | bool | true | ` — ` → `, ` (en-dashes preserved for ranges) |
| `forbidden_words` | `[str]` | (5 words) | Flagged, not auto-rewritten |
| `sentence_length_variance` | bool | true | (planned) Aim for one unusually long sentence per ~5 |
| `chevron_quotes` | bool | true | `«...»` for second-level Polish quotes |
| `fake_access_dates` | bool | false | Randomize netografia access dates |
| `fake_date_range` | `[str, str]` | `["2024-03-01", "2025-06-30"]` | Date range when fake_access_dates is true |

### `output`

| Key | Type | Default | Notes |
|---|---|---|---|
| `dir` | path | `output` | Where final docx/pdf go |
| `docx_name` | str | `Praca_licencjacka.docx` | Final filename |
| `pdf` | bool | true | Export PDF via Word COM (Windows) or LibreOffice (other) |
| `versioned` | bool | true | Keep `output/_versions/Praca_v1.docx` … |

### `pipeline`

| Key | Type | Default | Notes |
|---|---|---|---|
| `section_by_section` | bool | true | Writer pauses after every subsection |
| `verification_rings` | `[str]` | `["A","B","C"]` | Which rings to run |
| `re_verify_on_edit` | bool | true | If user edits the docx, re-run all verification |
| `reviewer_passes` | int | 1 | 3 = paranoid mode |
| `max_parallel_haiku` | int | 12 | Brief says 10-24 works; >24 hits rate limits |
| `fail_on_grade_below` | float | 4.0 | Ship refuses below this grade |

## Env vars

| Var | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Without it the writer, auditor, reviewer, and Ring B all fail at env_check |
| `PYTHONIOENCODING` | recommended | Set to `utf-8` to avoid `UnicodeEncodeError` on Polish characters |
| `CLAUDE_SKILLS_DIR` | optional | Override skill discovery (default: `~/.claude/skills`) |
