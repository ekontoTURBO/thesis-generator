# Contributing

Thanks for considering a contribution. This project was extracted from a real, completed thesis-writing session — every design decision has a corresponding row in `THESIS_GENERATOR_BRIEF.md`. Please read that brief before proposing changes to the verification rings or orchestration patterns.

## Development setup

```bash
git clone https://github.com/<you>/thesis-generator.git
cd thesis-generator
python -m venv .venv
.venv/Scripts/activate    # Windows; or `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"
pytest
```

## What we definitely want

- More university templates (every Polish uni has a different `Zarządzenie`; parsers welcome)
- A working `repair_docx` port of the proven session's `unwrap_outer_field.py` (Ctrl+F9 disaster auto-fix)
- A local-RAG fallback for users without NotebookLM access (pgvector or chroma)
- English-language prompt templates tested end-to-end
- Vancouver / Chicago citation style support
- A `write` CLI command that parses section specs from `thesis.yaml`
- Word COM / LibreOffice PDF export wired up

## What we probably won't accept

- A web GUI (different repo — fork it)
- Removing the verification rings to make it faster
- "AI-detection bypass" features beyond what the proven session used (em-dash removal, forbidden-word flagging). Anti-detection arms races are out of scope.
- Bundling the `notebooklm` skill (it's an independent project; we wrap it)

## Style

- Code: `ruff format` + `ruff check`
- Types: `mypy` strict mode where it doesn't fight Pydantic
- Tests: pytest, focused on regex + parsing + config validation (skip network calls in CI)
- Comments: explain WHY, not WHAT. If you write a long comment block, the code probably needs to be clearer instead.

## Adding a verification ring

If you propose a Ring D (e.g. "fact-check claims against Wikidata"), bring evidence from a real thesis run showing what it catches that A/B/C miss. Verification surface area is not free — every extra ring is more queries, more latency, more reports to read.

## Issues we'd love help on

See [`THESIS_GENERATOR_BRIEF.md` § 9](THESIS_GENERATOR_BRIEF.md) — the 7 open questions for productization are open issues by definition.
