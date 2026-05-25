Use Haiku. VERY THOROUGH verification of APA citations in subsection **{{section_id}}** of a thesis. No time/token limit — check every citation sentence-by-sentence.

## Inputs
- **Section text:** `{{section_file}}`
- **Bibliography + netografia (whole thesis):** `{{bibliography_file}}`
- **Sources folder (PDFs for this section):** `{{sources_folder}}`
- **Cross-chapter sources:** all sibling folders of `{{sources_folder}}` (some citations re-reference earlier chapters)

## Tooling
- `pdftotext` (Poppler) to extract PDF text. If a PDF path has non-ASCII characters and `pdftotext` fails, copy the file to `/c/tmp/` (Git Bash) or `C:\tmp\` (PowerShell) first, then run.
- `Read` tool with `pages` parameter as a fallback.
- `WebFetch` only for netografia citations that have a URL in the bibliography and require live verification of specific numbers (subscriber counts, prices, dates).

## Procedure for EVERY APA citation (both parenthetical and narrative)

1. **Locate** the sentence in `{{section_file}}` (paragraph tag `[P0XXX]` shown alongside text). Understand the claim being attributed.
2. **Identify the source.** Match the citation key (author + year) to a file in `{{sources_folder}}` or a sibling folder. If it's a netografia entry, look it up in the bibliography file. **Do not trust filenames** — open the PDF and verify the title/year/journal/DOI on the first page or in the running header.
3. **Open the PDF.** Extract text for the relevant page range. **PDF page ≠ printed page.** Establish the offset by finding a printed page number in the header/footer of one page, then apply it consistently. Always check the page named in the citation **and the two adjacent pages** before declaring "wrong page".
4. **Verify the claim semantically.** The author's sentence is usually a paraphrase, not a direct quote — but the underlying claim must be on the cited page. Watch for: nadinterpretacja (over-interpretation), attribution to wrong author within a multi-author source, conceptual vs. empirical (e.g. "wykazali empirycznie" claimed for a conceptual paper).
5. **Verify the page number** matches where the claim actually appears. Allow ±1 page only if the claim spans a page break.
6. **Cross-check the bibliography entry** for the cited work: year, authors (no missing co-authors), edition, journal name, page range. If the file you opened differs from the bibliography entry (different journal, different edition, preprint vs published), flag 🔴 BIBLIOGRAFIA.

## Status legend (use exactly these symbols)

- ✅ **OK** — content matches + page correct
- ⚠️ **STRONA** — content is in the source, but on a different page (state which one)
- ❌ **TREŚĆ** — claim not supported by the cited fragment / over-interpretation / wrong concept
- ❓ **BRAK ŹRÓDŁA** — PDF unavailable, can't be opened, or no matching file in folders (be specific)
- 🔴 **BIBLIOGRAFIA** — citation ↔ bibliography mismatch (wrong year, missing author, wrong edition, preprint pagination vs published)

A citation may have multiple flags (e.g. ⚠️ + 🔴).

## Output format — write to `{{report_path}}`

```markdown
# Section {{section_id}} citation audit

## [P0XXX] (exact citation text as in thesis)
**Sentence:** "the sentence from the thesis, verbatim or near-verbatim"
**Source file:** `filename.pdf` (or `Bibliography Netografia entry: <line>`)
**PDF page:** N (printed s. M)
**Status:** ✅ / ⚠️ / ❌ / ❓ / 🔴
**Comment:** what you found. For errors, state what the actual page/content should be. For ✅, one-line confirmation is enough.

## [P0YYY] (next citation)
...
```

Order **sequentially** by paragraph number, then by order within the paragraph. Use **Polish** if the thesis is Polish, **English** if English. Mirror the thesis language.

## Hard rules — DO NOT VIOLATE

- **Never hallucinate.** If you cannot open a PDF, say so explicitly and mark ❓.
- **Never claim a page is correct without opening the actual PDF.** Bibliography entries alone are not enough.
- **Filenames are unreliable.** Always verify inside the PDF.
- **A citation may correctly span a page range** (e.g. "s. 14–15"); check both endpoints.
- **For figure/table sources** (e.g. "Rysunek 3. Źródło: Author, 2020, s. 16"), verify that the actual figure/table is on that page of the source — not just any content.
- **Mirror language.** Polish thesis → Polish report. English thesis → English report.
- Create the parent folder if needed (`mkdir -p` on the reports folder).
- One sub-agent owns one section. Do not edit other sections' reports.
