# Sample project layout

This folder is the **template** for what a real thesis project looks like on disk. To actually run anything, you need to drop real input files into `inputs/`:

```
sample_project/
├── thesis.yaml                     # already provided — edit it
├── inputs/                         # YOU populate this
│   ├── draft.docx                  # your existing partial thesis
│   ├── sources/*.pdf               # source PDFs you cite
│   └── survey_responses.xlsx       # raw research data
├── _state/                         # auto-created by the tool
├── _reports/                       # auto-created by the tool
└── output/                         # auto-created at ship time
```

## Try it

```bash
# 1. Install the package (from the repo root)
cd ../..
pip install -e .

# 2. Verify your environment
tg verify-env examples/sample_project

# Expected at this point: it will complain that inputs/draft.docx is missing.
# That's correct — you need to add your real files first.

# 3. Once inputs are in place:
tg inventory examples/sample_project
tg verify examples/sample_project --rings A
tg review examples/sample_project
tg run examples/sample_project
```

## Where to get inputs for an end-to-end test

1. **draft.docx** — any partial Word document with at least one `(Author, year, s. X)` citation and a `BIBLIOGRAFIA` section
2. **sources/** — name files like `Author_Year_Title.pdf` (the inventory uses the filename as a heuristic for author/year matching)
3. **survey_responses.xlsx** — any spreadsheet with numeric data; the audit will match numbers in your draft against cells here
