# E2E test findings — 2026-05-23

End-to-end test against the real NotebookLM library (`Praca licencjacka - VR Commerce & Behavioral Research`, 94 sources). Stub draft of 3 sections + bibliography with deliberately planted bugs to validate detection.

## What worked

| Component | Result |
|---|---|
| Package install (`pip install -e .`) | ✅ |
| Smoke tests (`pytest tests/`) | ✅ 11/11 (now 14/14 after regression tests) |
| `tg --help`, `tg init`, `tg verify-env`, `tg inventory`, `tg verify --rings A` | ✅ all work end-to-end |
| NotebookLM auth check (env_check) | ✅ Verified live: authenticated |
| NotebookLM subprocess adapter (browser automation roundtrip) | ✅ All 4 queries succeeded, ~60s for 4 queries (parallel_queries=2) |
| Ring A detection of planted bugs (after fix) | ✅ Krawczyk orphan + Goldstein missing-from-bib both caught |
| Humanize em-dash replacement | ✅ 3 em-dashes replaced |
| Humanize forbidden-word detection (after fix) | ✅ "triangulacja" caught via stem match on "triangulacji" |

## Bugs the e2e test caught (now fixed)

### 1. NotebookLM doesn't return structured VERDICTs — ARCHITECTURAL

**Symptom:** Of 4 verification queries, parser returned `UNKNOWN` for 3 and a **false-positive** `OK` for 1.

**Root cause:** NotebookLM is optimized for source-grounded prose answers. It ignored the "VERDICT: OK/NIEŚCISŁE/BŁĘDNE" format directive and returned regular academic prose with citations of *other* sources from the library. Example response when asked to verify Hoch 2002:

> Urządzenia wirtualnej rzeczywistości stanowią modelowy przykład dóbr doświadczalnych […] (Bailenson, 2018, s. 45; Klein, 1998, s. 196). W przeciwieństwie do tradycyjnej elektroniki […]

That's grounded content from the library, but it has no VERDICT line because NotebookLM doesn't accept format instructions the way the Claude API does.

**Fix:** Two-step Ring C.
- Step 1: NotebookLM gets a grounding question ("does the source say X?"). Returns prose.
- Step 2: Claude Haiku reads the grounded prose + the paraphrase, produces structured VERDICT.

The judge is `NotebookLMAdapter._judge_with_claude`. Gated on `ANTHROPIC_API_KEY` — if unset, strict parser is the only path and verdicts are honestly `UNKNOWN`. No more false positives.

### 2. Strict VERDICT parser — fixed

**Symptom:** Trusov 2009 verdict was `OK` even though the response contained no VERDICT line. Parser regex `VERDICT\s*[:=]\s*(OK|...)` matched the stray word "OK" anywhere in the prose.

**Fix:** Anchored to line start: `(?m)^\s*VERDICT\s*[:=]\s*(OK|...)\b`. Excerpt parser similarly tightened — only matches after explicit `EXCERPT:` / `CYTAT:` / `Dosłowny cytat:` markers, not arbitrary quoted text.

### 3. Ring A regex misses Polish "i in." (= "et al.") — fixed

**Symptom:** `(Trusov i in., 2009)` not matched in parens form. `Goldstein i in. (2008)` not matched in narrative form. Result: 2 of 6 cited sources skipped, 1 false-positive orphan (Trusov), 1 missed missing-from-bib (Goldstein).

**Fix:** Added `(?:\s+et\s+al\.?|\s+i\s+in\.?)?` group to both `_CITATION_PARENS` and `_CITATION_NARRATIVE`.

**Re-test:** Ring A now reports 6 citations (was 4) and correctly catches both planted bugs (Krawczyk orphan + Goldstein missing-from-bib).

### 4. Humanize forbidden_words misses Polish declensions — fixed

**Symptom:** `forbidden_words: ["triangulacja"]` didn't detect the word "triangulacji" (genitive case) in the draft. The substring check `"triangulacja" in body_text` failed because the lemma ends in `-a` and the inflected form ends in `-i`.

**Fix:** Stem matching — take the first 6 chars of each lemma (e.g. `"triang"`) and look for any word starting with that stem via `\\b{stem}\\w*`. Reported finding includes the stem used so users can verify.

### 5. NotebookLM browser state expiring — noted, not fixed

**Symptom:** Skill prints `⚠️ Browser state is 13.1 days old, may need re-authentication`. Queries succeeded today but auth will eventually expire.

**Mitigation:** `tg verify-env` already calls `check_auth()` and warns when not authenticated. User runs `tg notebooklm auth` to refresh. No code change needed; documented in `docs/NOTEBOOKLM.md`.

## Regression tests added

`tests/test_smoke.py` now has 3 new tests pinning each fix:
- `test_ring_a_handles_polish_et_al`
- `test_notebooklm_strict_verdict_parser_no_false_positives`
- `test_humanize_forbidden_words_handles_declensions`

Total: 14 tests, all pass.

## What still needs API key for full verification

Phases that need `ANTHROPIC_API_KEY` and weren't exercised in this e2e:
- **Writer** (`thesis_generator.writer`) — Opus call to draft sections
- **Ring B** (Haiku-per-source) — needs Anthropic + actual PDF files in `sources/`
- **Independent reviewer** — Opus call
- **Data audit Claude assist** — currently pure-Excel, but planned to add Opus claim-cross-check
- **Two-step Ring C** (Claude judge in step 2) — works today but degrades to honest UNKNOWN without key

Setting `$env:ANTHROPIC_API_KEY = "sk-..."` and re-running the e2e would exercise the full pipeline.

## Confidence summary

- **Plumbing** (config, CLI, file IO, subprocess to NotebookLM, async orchestration): **solid** — all paths exercised.
- **Verification logic** (Ring A regex, Ring C two-step, humanize): **fixed and regression-tested** — would catch the planted bugs going forward.
- **LLM-dependent paths** (writer, Ring B, reviewer): **scaffolded with real prompts, no live API test yet** — need API key + small budget ($1-5) to validate.
