# Pipeline phases

The pipeline runs phases in the order below. Any phase can be skipped via `tg run --skip phase1,phase2`.

## 0. `env_check` (hard gate)

Verifies every input declared in `thesis.yaml`:
- Required files exist (draft, sources_dir, raw_data)
- Optional files (regulation, interviews) are absent OR present-and-valid
- `ANTHROPIC_API_KEY` env var is set
- If Ring C is configured, NotebookLM skill is authenticated

Also catches the **double-space filename bug** (gotcha #1) and reports Word lock files (`~$*.docx`, gotcha #4) before anything tries to open them.

Output: `_reports/env_check.md`. **If this fails, the pipeline aborts.**

## 1. `inventory`

Two indexes built into `_state/inventory.json`:
- `author_year → pdf_path` for every PDF under `inputs/sources_dir/` and `inputs/interviews_dir/`
- Style fingerprint of the existing draft: heading styles, citation patterns, em-dash count, chevron quote count, bibliography section structure, list of already-cited (author, year) pairs

The writer in phase 2 uses both indexes to (a) not invent new citation styles and (b) avoid duplicating sources the existing chapters already cite.

## 2. `write` (optional — only if you supply section specs)

Sequential per-section drafting. Each section:
1. Opus call with the style fingerprint as system prompt
2. Output parsed as JSON: `{text, used_citations, notes}`
3. Persisted to `_state/section_<id>.txt`
4. Progress report updated

The writer never modifies the docx directly. Output goes through an inserter (planned: `docx_ops.insert_section`) so the user can review section text before it lands in the master file.

## 3. `verify_a` — Ring A: internal

Pure regex + `python-docx` over the draft. Catches:
- **Orphaned bibliography entries** (in biblio but never cited in body)
- **Missing bibliography entries** (cited in body but not in biblio)
- **Alphabetization breaks** in primary literature section
- **Em-dash count** (> 0 = AI tell, fails the ring)

Fast (< 1s), free, no API calls. Always runs first because if Ring A fails, B and C will be running on a fundamentally broken document.

## 4. `verify_b` — Ring B: Haiku per source

One Haiku subagent per cited PDF, in parallel (bounded at `pipeline.max_parallel_haiku`). Each subagent:
1. Opens its assigned PDF via `pdfplumber` for the cited page ±2 (NEVER via `Read` — gotcha #3)
2. Locates the fragment closest to the paraphrase
3. Returns `VERDICT: OK | NIEŚCISŁE | BŁĘDNE` + literal excerpt + suggested correction

Brief evidence: 10-12 parallel Haikus survived. >24 hits rate limits.

## 5. `verify_c` — Ring C: NotebookLM

One question per citation, ≤ 400 words, against the user's NotebookLM library. NotebookLM sees the *whole library* at once, so it catches the case Ring B can't: cited PDF exists, but the claim isn't in it.

In the proven session this caught 4 hallucinations Ring B had marked OK (Heilman/Rosario/Leung/Statista — all real PDFs with mis-attributed claims).

Verdict format matches Ring B for direct comparison. Disagreements between B and C are the most valuable signal — they're the calls that need human eyes.

## 6. `data_audit`

For every numeric claim in the draft (`65%`, `M = 4.21`, `χ² = 12.3`, `N = 75`), tries to match against a value in the raw Excel sheets. Mismatches are flagged with magnitude (`draft says 6, excel has 4 (Δ=2)`).

This is the audit that caught the "6 respondentów → really 4" and "65% kolejny headset → really ~34%" in the proven session.

Output is HEURISTIC — flags for human review, never auto-fixes.

## 7. `independent_review`

A single Opus call with **zero context** of how the thesis was produced. System prompt: "strict but fair professor, grade 2.0–5.0." Output:
- Numeric grade with justification
- Top 5 problems (PILNY / WYSOKI / ŚREDNI) with quote + why + fix
- 3 strengths

The grade becomes the metric tracked across versions. The proven session went 4.0 → 4.5 → ~5.0 across iterations.

**Reviewer claims are CLAIMS, not facts** (gotcha #12). For paranoid mode, add a follow-up phase that verifies each claim against real PDFs and marks it TRUE / HALLUCINATION / PARTIAL / ALREADY FIXED.

## 8. `humanize`

Strips obvious AI tells:
- Replaces ` — ` (em-dash) with `, `
- Flags forbidden buzzwords (triangulacja, rygorystycznie, holistycznie, …)
- Reports for manual review — does NOT auto-rewrite, because rewrite could change the meaning

User in the proven session said this 3 times: long sentences are OK; em-dashes are not.

## 9. `ship`

Final assembly:
- Copies the final docx into `output/Praca.docx`
- If `output.pdf` is true and Word COM is available: exports a PDF
- Increments `output/_versions/Praca_vN.docx`

**Refuses to ship if `independent_review.grade < pipeline.fail_on_grade_below`** (default 4.0).
