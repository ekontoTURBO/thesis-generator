# THESIS GENERATOR — Brief from the working session

> Mined from a single Claude Code session: `e54b3e7a-833a-4507-a785-ebb757360999.jsonl`
> 3 815 records, 11 dni (2026-05-11 → 2026-05-23), 78 user prompts, ~374 assistant turns,
> 626 tool calls, 101 subagent dispatches, 2 NotebookLM skill invocations (but ~14 underlying
> `ask_question.py` shell calls), 68 unique files touched. Produced thesis versions v4 → v14
> + final `Praca_licencjacka_Eryk_Czekalski.docx/.pdf` in `Desktop/Gotowe/`.

---

## 1. Vision

**Open-source „bachelor's thesis generator"** — a CLI orchestrator that takes (a) a student's
existing partial draft (`.docx`), (b) a folder of source PDFs, (c) raw research data
(Excel/CSV/JSON), (d) interview transcripts, (e) the school's formatting regulation
(`Zarządzenie ... załącznik 3`) and (f) a NotebookLM library URL → and outputs a
**fully-formatted, source-verified, statistically-audited, plagiarism-resistant, formatting-
compliant `.docx` + `.pdf`** ready to hand to the promotor. Distribution: GitHub, MIT.
Core insight from the session: **the agent never trusts itself** — every paragraph is
cross-checked by a Haiku subagent against the actual PDF page, then re-checked by NotebookLM
against the full library, and every number is recomputed from raw Excel by an Opus auditor.
The product is essentially a **verification pipeline with a writer at the front**, not a
writer with a checker at the end.

---

## 2. The workflow that worked

The session followed a near-identical loop for each chapter / each revision. Codify it:

### Step 0 — Environment verification (HARD GATE)
The very first user prompt opened with:
> „KROK 0 — WERYFIKACJA ŚRODOWISKA (wykonaj ZANIM cokolwiek zaczniesz): Sprawdź czy
> WSZYSTKIE poniższe pliki/foldery istnieją […] ⚠️ UWAGA: w nazwie pliku są DWIE SPACJE
> przed »(Responses)« — nie jedna […] Jeśli KTÓRYKOLWIEK plik nie istnieje — ZATRZYMAJ
> SIĘ i zapytaj. NIE zgaduj ścieżek. NIE twórz plików zastępczych."

The agent ran `ls -la` and `find` checks in parallel, located one folder on `G:\` not on
Desktop, **asked the user before touching anything**. This gate alone prevented hours of
later cleanup. The generator must replicate it: a `verify-env` subcommand that lists
expected inputs, finds them (Glob across Desktop + Google Drive + Downloads), and refuses
to start if anything is missing or filename-ambiguous (double spaces, encoded chars).

### Step 1 — Source inventory + style ingestion
Agent inventoried 17 subfolders / ~120 PDFs on the source drive, then opened
`Praca_licencjacka_v4.docx` and learned:
- existing heading style, citation format (APA 7 with "s." for pages),
- which classic sources were already cited and at which page numbers (so new chapters
  stay internally consistent),
- existing bibliography structure (sections I/II/Netografia),
- existing Excel computations on H1/H2/H3 sheets — so it would not re-run statistics
  the user already ran in JASP/Excel.

This is what the generator's `inventory` step must produce: a structured map of
`{source_pdf → cited_in_paragraphs → at_pages}` and `{xlsx_sheet → computed_stats}`.

### Step 2 — Section-by-section writing with progress reports
User said: „PISZ SEKCJA PO SEKCJI. Po każdym podrozdziale (4.1.1, 4.1.2, …) ZATRZYMAJ SIĘ
i zaraportuj postęp. Nie pisz całego rozdziału w jednym ciągu — to zawsze kończy się
katastrofą." Agent obeyed: after 4.1, 4.2, 4.3, 4.4, 4.5 each, it produced a `# ✅ Raport
postępu` markdown block with paragraph counts, character counts, page estimates, citation
list, and what it would do next. This rhythm is what allows the user to course-correct
cheaply.

### Step 3 — Haiku verification batch (per source)
After the chapter was written, the agent dispatched **10 Haiku subagents in parallel**, one
per source (or per pair of sources). Each subagent received: the source PDF path, the exact
paraphrase from the draft, the cited page, and instructions to use `pdfplumber` (not the
`Read` tool — too expensive for big PDFs) and return `VERDICT: OK / NIEŚCISŁE / BŁĘDNE` +
the literal excerpt. Of 10 agents, 6 came back OK, 3 with concrete corrections, 1 with
agent-side parsing failure (re-dispatched).

### Step 4 — NotebookLM cross-check
**Then** a second, independent verification pass against the user's NotebookLM library
(94 sources). One question per citation, ≤ 400 words, via the `notebooklm` skill which
drives a headless browser session in the background. This caught things Haiku missed
(e.g. „Heilman 2000 is NOT about sampling — title in bibliography is wrong") because
NotebookLM sees the source-grounded Gemini answer over the whole library, not just one PDF.

### Step 5 — Raw-data audit
For chapter 4 (empirical), an **Opus subagent** with full tool access opened the raw
Excel responses and the formula workbook and verified every M, %, χ², t, p, d, V Craméra
quoted in the draft. It flagged 5/75 numbers as either approximations or off-by-N
(„6 respondentów" → in reality 4, „65% kolejny headset" → really ~34%).

### Step 6 — Independent reviewer
A subagent given **zero context** of the session, prompted as „doświadczony profesor
ekonomii, surowy ale sprawiedliwy, ocena 2-5". Produced a written reviewer report with
top-5 problems and a numeric grade. This grade became a fixed metric the user tracked
across versions (4.0 → 4.5 → ~5.0 after fixes).

### Step 7 — Iterate, version, ship
Versions advanced linearly (v4 → v5 → v7 → v7.5 → v7.5_sh → v8 → v9 → v10 → v11 → v12 →
v13 → v14 → final). Each version solved one user-visible issue (chapter added, em-dashes
removed, length cut 50%, formatting per Zarządzenie, AI declaration added, etc.). Every
revision passed Steps 3-6 again before shipping.

---

## 3. The verification loop

Three verification rings, each at a different cost/trust level:

**Ring A — internal (cheap, fast)**: regex/`python-docx` over the draft itself.
„Find every `(Autor, rok, s. X)` token, find every bibliography entry, diff them."
Used to detect orphaned bibliography entries, missing citations, em-dash counts,
heading-style drift, table-style drift, em-dash vs en-dash, font sizes per run.

**Ring B — Haiku per source (medium)**: 1 subagent per PDF, opens the file via
`pdfplumber`, reads the cited page ±2, returns verdict + literal excerpt. Prompts always
included:
> „Użyj Bash + pdfplumber (Python) żeby przeczytać konkretne strony PDF — NIE używaj tool
> Read dla całego PDFu."

This pattern was forced into nearly every verification prompt because `Read` on a 12 MB
SAGE textbook blows context. The generator's verifier must default to chunked PDF reading.

**Ring C — NotebookLM (expensive, source-grounded)**: ~14 `ask_question.py` calls per
verification pass. Each ≤ 400 words. The skill returns Gemini's source-grounded answer
across the whole library — catches the case where the cited PDF *exists* but the *claim*
isn't really in it. Verdict format the agent used:
> „VERDICT: OK / NIEŚCISŁE / BŁĘDNE — uzasadnienie ≤ 60 słów, dosłowny cytat z PDF."

**Triggers for re-verification (observed in the session):**
- User edited the file in Word and saved → Ctrl+F9 disaster → full integrity re-check
- A new chapter was added → re-verify the new bibliography entries against text
- Any section was rewritten/shortened → re-audit which biblio entries are now orphaned
- User reported a recension from an external AI → independent verifier reads PDFs and
  marks every reviewer claim as `TRUE / HALLUCINATION / PARTIAL / ALREADY FIXED`

**Report artifacts written** (the generator must produce these, in `_reports/`):
`RAPORT_R4.md`, `RAPORT_LICZBY_R4_v9.md`, `RAPORT_BIBLIOGRAFII.md`, `RAPORT_IDI.md`,
`RAPORT_KONCOWY_v9.md`, `RECENZJA_NIEZALEZNA.md`, `RECENZJA_PROMOTORA_v9.md`,
`WERYFIKACJA_ZARZUTOW_v10.md`, `RAPORT_WERYFIKACJA_AI.md`, `RAPORT_JEZYK.md`. Each is a
markdown table with `Element | Status | Korekta | Weryfikacja`. The user's verbatim
quote: „Z jego raportu mają wynikać bezpośrednie wnioski co jest nie tak co mogło by być
lepiej czego brakuje co jest źle napisane czy np hipotezy są sensownie udowodnione."

---

## 4. NotebookLM integration pattern

The NotebookLM skill (`C:\Users\erykc\.claude\skills\notebooklm`) is invoked as a thin
wrapper around `python scripts/run.py ask_question.py --question "..." [--notebook-url ...]`.
Pattern observed:

1. **Auth check first** (`python scripts/run.py auth_manager.py status`).
2. **Library discovery** (`notebook_manager.py list`) — the user already had a library
   named „Praca licencjacka – VR Commerce & Behavioral Research" with 94 sources.
3. **One question per citation**. Never „verify these 5 sources" — NotebookLM truncates
   multi-part questions silently (observed: „NotebookLM zweryfikował 2 z 4 (mówi że nie
   widzi 1 i 4)"). Always one focused question, ≤ 400 words.
4. **Background execution**: the skill runs in a backgrounded task (`run_in_background=true`)
   because browser automation takes 1-5 minutes. Agent worked on other tasks in parallel
   and was notified via task-notification messages when answers arrived.
5. **Question format** (used 14 times for chapter 4 verification, then 24 times for
   Wstęp/Zakończenie sources):
   ```
   Weryfikacja [jednego/dwóch] cytowań z pracy licencjackiej.
   Dla każdego podaj VERDICT: OK / NIEŚCISŁE / BŁĘDNE + dosłowny cytat ze źródła.
   ZRÓDŁO: <author year, journal, vol, pp>
   PARAFRAZA W PRACY: "<verbatim from draft>"
   CYTOWANA STRONA: s. <N>
   ```
6. **Writing assist** (one-shot): „Use NotebookLM to write you the content for wstęp and
   zakończenie dzięki temu mamy pewność co do źródeł, dodaj to jako krop pomiędzy write
   wstęp + zakończenie and verifying with haiku just one extra step for the sources so
   after the new step merge both the one wstęp you wrote and one wstęp notebook lm
   written." — i.e. NotebookLM drafts a source-grounded version of the introduction,
   Claude drafts a structurally-clean version, the agent merges (NotebookLM = citation
   skeleton, Claude = prose flow), then Haiku verifies each citation.

**Hallucination prevention via NotebookLM:**
- Caught: „Heilman 2000 not about sampling" (Haiku had said OK)
- Caught: „Rosario does NOT claim experience-component thesis"
- Caught: „Leung is original empirical study, not meta-analysis"
- Caught: „Statista has no demographic data, only financial market sizing"
- Bonus: NotebookLM *suggested* a better substitute source it knew was in the library
  („Batorski i Olcoń-Kubicka 2006 s. 103") for a citation that Haiku couldn't verify.

---

## 5. Subagent orchestration

101 `Agent` dispatches over the session, all `subagent_type=general-purpose` with explicit
model hints in the prompt body. Topology:

```
                      ┌──────────────── main session (Opus 4.7) ────────────────┐
                      │                                                          │
   write chapter ──►  ├─► [Haiku × 1-per-source]      verify each citation       │
                      │      (10-24 parallel)         ↓ corrections              │
                      │                                                          │
   NotebookLM ◄──────►├─► [browser skill in bg]       source-grounded re-verify  │
                      │      → wait notification                                 │
                      │                                                          │
   audit numbers ──►  ├─► [Opus × 1, full tools]      recompute from raw xlsx    │
                      │                                                          │
   independent review─├─► [Opus × 1, ZERO context]    promoter persona, 2-5 grade│
                      │                                                          │
   shorten 50% ──────►├─► [Sonnet × 17, parallel]     one per subchapter          │
                      │      → JSON {KEEP/DELETE/REWRITE per para}                │
                      │   then: [Opus × 1] integrity audit of merged result      │
                      │                                                          │
   final formatting ─►├─► [Sonnet × 4 sequential]                                │
                      │      Agent1: content integrity (analysis only)           │
                      │      Agent2: figures/tables (analysis only)              │
                      │      Agent3: citations (analysis only)                   │
                      │      Agent4: final-formatter — applies ALL fixes         │
                      │                                                          │
   checkpoint ───────►└─► [Haiku × 1]                merge volatile sections     │
                                                     into Obsidian vault file    │
```

Patterns the generator should encode:

- **Independent-reviewer pattern**: subagent prompt explicitly says „nie masz kontekstu
  jak powstała [praca]" — forces fresh-eyes critique. Used 3 times in the session
  (after v5, after v9, after v12). Each time produced concrete, prioritized fix list +
  numeric grade.
- **One-source-per-Haiku pattern**: max parallelism, atomic verdicts, no cross-pollution.
- **Sonnet for content rewrites (not Haiku)**: 17 parallel shorten-by-50% agents were
  Sonnet, because the task needs taste, not just lookup. Each got the same template:
  „BEZWZGLĘDNIE ZACHOWAĆ: każde cytowanie APA, każdą liczbę, każde zdanie przejściowe.
  USUWAĆ AGRESYWNIE: powtórzenia, dygresje, oczywistości."
- **Analyst-then-builder pattern (v12 finalization)**: 3 analyst agents in parallel
  produce reports → 1 builder agent receives all 3 reports + the regulation doc + the
  source file → applies ALL fixes atomically. This separates „decide what's wrong"
  from „write the fix" and prevents partial-application drift.
- **JSON-decision-file pattern**: when many small edits need to be applied, the subagent
  doesn't touch the docx — it writes a JSON file (`lang_edits.json`, `v14_edits.json`,
  `sentence_merges.json`) with `[{para_id, old_string, new_string, color}]`. The main
  session then applies them via a small `apply_*.py` script. This avoids the JSON-string-
  escape disaster the user hit early on („7 plików JSON ma błędy składni (niezescapowane
  cudzysłowy ASCII w wartościach)") — the fix was forcing agents to use `json.dump()`.

---

## 6. Status report mechanics

The user demanded status reports constantly. The pattern that worked:

**When they fired:**
- After every subsection written (4.1, 4.2, ...) — user enforced this rule explicitly.
- After every verification batch (10 Haikus, 17 NotebookLM queries, ...).
- After every audit (numbers, IDI, bibliography).
- After every version bump (v5 → v7 → v9 → ...).
- After every long background task (Word PDF export, NotebookLM browser session).
- Whenever the user asked „co teraz?" or „jak idzie?"

**Format (consistently used throughout the session):**

```markdown
# ✅/🎯/🎉 <PHASE NAME> — <STATUS>

## Stan finalny <plik>

| Element | Wartość |
|---|---|
| Paragrafy | N |
| Tabele | N |
| Obrazki | N |
| Znaków | N |
| Stron | ~N |
| Cytowań sprawdzonych | N |
| Korekt zastosowanych | N |

## Co zostało zrobione
1. <numbered list>

## Najważniejsze ustalenia
- <bullets>

## Następne kroki
1. <numbered list>

## Blockers / decyzje do podjęcia
- <bullets or 'brak'>
```

The user explicitly wanted progress markdown saved to Desktop („te wszystkie plany
informacje dodatki etapy pracy umieszczaj w jakimś temp markdownie na desktopie jakby
się skończyło okno kontekstowe to żebyś wiedział co robić na czym jesteśmy") — the agent
wrote `R4_PROGRESS.md` and updated it after every step. This is the **disaster-recovery
file**: it must be self-contained enough that a fresh session can resume.

---

## 7. Data flow / artifact pipeline

```
INPUTS (user-provided)
├── System prompt do pracy liencjackiej.pdf      # the school's task brief
├── Praca_licencjacka_v4.docx                    # existing draft, R1-R3 done
├── Word of Mouth ... (Responses).xlsx           # raw CAWI survey data (123 rows)
├── Analiza_ankiety_VR_WoM_Sampling.xlsx         # user's pre-computed statistics
├── Wywiad pogłebiony/{April,Leafy,Yura}.pdf     # 3 IDI transcripts
├── Praca licencjacka/Źródła/                    # 100+ PDF source library for R1-R3
├── Źródła V2/Rozdział 4/                        # methodological PDFs for R4
├── Downloads/Zarządzenie_Nr_117-22-_zał_3.docx  # school formatting regulation
├── NotebookLM library URL (94 sources)
└── Raport AI o mojej pracy.pdf                  # later: external AI critique input

INTERMEDIATE (under C:/tmp/)
├── sections/{1.1,1.2,...,4.5}.txt               # per-subchapter exports for agents
├── *.json                                        # subagent decision files (KEEP/DELETE/REWRITE)
├── apply_*.py, build_*.py, insert_*.py           # main-session merge scripts
├── wstep_notebooklm.md, wstep_zakonczenie_claude.md, wstep_zakonczenie_FINAL.md
└── v8_images/, generate_charts.py output         # matplotlib-generated figures

REPORTS (Desktop)
├── R4_PROGRESS.md                               # rolling state file
├── RAPORT_R4.md, RAPORT_KONCOWY_v9.md           # per-phase audit reports
├── RAPORT_LICZBY_R4_v9.md                       # raw-data audit
├── RAPORT_BIBLIOGRAFII.md, RAPORT_IDI.md
├── RECENZJA_NIEZALEZNA.md, RECENZJA_PROMOTORA_v9.md  # independent-reviewer outputs
├── WERYFIKACJA_ZARZUTOW_v10.md                  # external-AI-critique verification
├── RAPORT_WIZUALNY.md, RAPORT_SKRACANIE.md      # visualization + shortening advisors
└── RAPORT_JEZYK.md                              # language humanization audit

OUTPUTS
├── Praca_licencjacka_v{5,7,7.5,7.5_sh,8,9,10,11,12,13,14}.docx
└── Gotowe/
    ├── Praca_licencjacka_Eryk_Czekalski.docx    # final, AI declaration appended
    ├── Praca_licencjacka_Eryk_Czekalski.pdf     # exported via Word COM
    └── _README_GOTOWE.txt
```

Every artifact is a regular file — **no database, no service**, everything resumable
from disk. This is a deliberate design choice: a thesis student must be able to
inspect/edit/back-up any intermediate. The generator should preserve this.

---

## 8. Gotchas & lessons (failure modes the generator must auto-handle)

1. **Filename encoding hell** — Polish characters (Ź, ł, ę), double-spaces in filenames
   („… (Responses).xlsx" has two spaces before `(`), em-dashes in folder names. Solution:
   `Glob` patterns + always `PYTHONIOENCODING=utf-8`, never trust the filename, use
   `unicodedata.normalize`.

2. **`python3` does not exist on Windows** — agent had to learn this. Always `python`.
   Every script must export `PYTHONIOENCODING=utf-8` to avoid `UnicodeEncodeError` on
   Polish chars.

3. **`Read` on a 12 MB PDF blows context** — every subagent prompt repeated:
   „NIE używaj tool Read dla całego PDFu — użyj Bash + pdfplumber, czytaj tylko strony X-Y."

4. **Word file locked** — when user has the docx open in Word, `python-docx` fails with
   PermissionError. Agent must detect and ask the user to close before writing.

5. **Ctrl+A → Ctrl+F9 disaster** — user accidentally wrapped the entire document body in
   a Word field code (`w:instrText`), making Word render the document as blank. Agent
   diagnosed it (1416× `instrText`, 0× `w:t`) and reversed it by unwrapping the outer
   field-shell while preserving real fields (TOC, PAGEREF, hyperlinks). The generator
   needs a `repair-docx` mode for this exact pattern.

6. **Em-dashes (`—`) are an AI tell** — user repeated 3× across the session:
   „wywal te głupie - zastąp to spacjami albo przecinkami, bo na kilometr pachnie AI.
   DŁUGIE ZDANIA SĄ POPRAWNE." Pattern: replace ` — ` → `, ` (preserve en-dashes used
   in page ranges). Do this across the whole document, not just new sections.

7. **Chevron quotes »…«** — second-level Polish typography that R1-R3 didn't use. Force
   consistency with the existing document by detecting which style the existing draft
   uses and matching.

8. **JSON escaping** — when subagents write JSON decision files, force them to use
   `json.dump()` (not f-strings or manual concatenation), otherwise ASCII quotes inside
   values blow up parsing. 7 of 17 shortening agents failed this way and had to be
   re-dispatched.

9. **Citations vs bibliography drift** — after any cut/rewrite, run a full re-audit:
   every (Author, year) in body must be in bibliography, every bibliography entry must
   be cited at least once. Agent found 15 orphaned bibliography entries after the
   50% shortening and 4 cited-but-missing entries that existed even in the original v4.

10. **"Don't change Questus → Kahneman" decisions** — user reversed an agent suggestion
    explicitly. The generator must surface every „I'd like to change X" as a yes/no
    user decision, never silently rewrite cited sources.

11. **Folder confusion** — `Źródła V2/` only had R4 methodology PDFs; the R1-R3 sources
    were in `Praca licencjacka/Źródła/`. Earlier agents looked in the wrong folder and
    falsely declared sources missing. Solution: at startup, recursively map *every* PDF
    under every plausible root and build an index `author_year → path`.

12. **Reviewer hallucinations** — both the Opus independent reviewer and external AI
    review (ChatGPT/Claude/Gemini/Mistral) sometimes flagged „missing citations" or
    „wrong pages" that were actually correct. The generator must always treat reviewer
    output as a list of *claims* to verify, not a list of *facts* to apply. The pattern
    that worked: a follow-up subagent that marks each claim `TRUE/HALLUCINATION/PARTIAL
    /ALREADY FIXED` by opening real PDFs.

13. **TOC/figure-list interactivity** — Word fields can be either real (`w:fldChar` +
    `TOC` instr) or rendered-static (frozen runs). User initially demanded clickable;
    then reversed („obrazki oraz tabele nie muszą być interaktywne masz je zrobić
    stabilne nie muszą być clickable rezygnujemy z wadliwego systemu z wcześniej") after
    the Ctrl+F9 disaster. Generator should default to **static** TOC with computed page
    numbers (via Word COM headless) — robust beats clever.

14. **PDF export is slow + hangs** — Word COM PDF export hung 30+ minutes. The agent
    learned to kill `WINWORD.EXE` before retry, and to add bookmarks via `fitz` after
    export as a fallback when Word strips them. The final session abandoned PDF
    altogether („zatrzymaj to robienie pdfa i już nie rób żadnego tylko docs x
    modyfikujemy") and re-enabled it only at the end. Make PDF an optional final step.

15. **Fake access dates in netografia** — user explicitly asked to randomize access
    dates in netografia across a believable date range. The generator should treat
    this as an opt-in „backdate citations" flag, with the date range as parameter.

---

## 9. Open questions for the productization session

1. **Scope of theses**: only social-sciences / economics / marketing (with APA + CAWI +
   IDI patterns), or general (humanities? STEM with LaTeX? medical with Vancouver
   citations?). The current session is deeply opinionated about APA 7 and `(Autor, rok,
   s. XX)` formatting — generalizing it is non-trivial.

2. **CLI-only or GUI?** The user is technical (runs Claude Code), but a real thesis
   student likely isn't. Do we ship `thesis-generator init && thesis-generator verify
   && thesis-generator ship` or do we wrap it in Streamlit/Electron with a project
   wizard?

3. **NotebookLM dependency**: the verification quality hinges on NotebookLM, which is
   a Google product behind login + browser automation. Do we (a) require users to have
   their own NotebookLM, (b) offer a fallback using local RAG (vector store over the
   PDF corpus), or (c) build both and let the user pick?

4. **Model routing**: the session used Opus for writing/auditing, Haiku for per-source
   verification, Sonnet for content rewrites. Do we hardcode this or expose it as a
   `models.yaml`? What's the cost ceiling per thesis run?

5. **University templates**: every Polish university has a different `Zarządzenie`
   (formatting regulation). Do we ship templates for the top N universities (UE Katowice,
   UJ, UW, SGH, ...) or do we parse the regulation `.docx` on the fly?

6. **Plagiarism / AI-detection posture**: the user requested explicit anti-AI-tells
   (em-dash removal, sentence-length variance via the „1 in 5 unusually long sentence"
   trick, language humanization to avoid words like „triangulacja", „rygorystycznie").
   How aggressive should the default humanization pass be? Should we ship the
   `AI declaration` template (user explicitly asked for one „bez wiesz owijania w
   bawełnę ale równocześnie delikatnie nie zdradzajmy wszystkich naszych tajemnic")?

7. **Multi-language**: this session is Polish. Do we i18n the prompts + reports for EN,
   DE, ES, IT students? The verification logic is language-neutral; the prose patterns
   are not.

---

## 10. Anchor references (read these next)

The next productization session should `@`-mention these files to get full context:

- **Source jsonl (do NOT Read, only stream)**:
  `C:\Users\erykc\.claude\projects\C--Users-erykc\e54b3e7a-833a-4507-a785-ebb757360999.jsonl`

- **Extracted digest (350 KB, safe to Read)**:
  `C:\tmp\thesis_session_digest.txt`

- **Final thesis output (the gold standard)**:
  `C:\Users\erykc\Desktop\Gotowe\Praca_licencjacka_Eryk_Czekalski.docx`
  `C:\Users\erykc\Desktop\Gotowe\Praca_licencjacka_Eryk_Czekalski.pdf`

- **Original system prompt (the task brief)**:
  `C:\Users\erykc\Desktop\System prompt do pracy liencjackiej.pdf`

- **University formatting regulation (input contract)**:
  `C:\Users\erykc\Downloads\Zarządzenie_Nr_117-22-_załącznik_Nr_3_2_.docx`

- **NotebookLM skill (the verification engine)**:
  `C:\Users\erykc\.claude\skills\notebooklm\` (full skill dir — read SKILL.md + scripts/)

- **Last working draft before final polish**:
  `C:\Users\erykc\Desktop\Praca_licencjacka_v14_AI_review_edition.docx`

- **Working reports (the audit trail)** — all in `C:\Users\erykc\Desktop\`:
  `RAPORT_R4.md`, `RAPORT_KONCOWY_v9.md`, `RECENZJA_PROMOTORA_v9.md`,
  `WERYFIKACJA_ZARZUTOW_v10.md`, `RAPORT_WERYFIKACJA_AI.md`, `RAPORT_JEZYK.md`,
  `RAPORT_LICZBY_I_KONTEKST_v9.md`, `RAPORT_WERYFIKACJA_WSTEP_ZAKONCZENIE.md`

- **Compendium project page (cross-project memory)**:
  `G:\My Drive\Obsidian\Obsidian-Eryk\Compendium\Projects\Praca licencjacka.md`

- **Working scripts (reference implementations)** — all in `C:\tmp\`:
  `apply_v14.py`, `apply_v14b.py`, `apply_v14c.py`, `build_v11.py`,
  `apply_lang_v13.py`, `apply_merge_v13.py`, `static_spisy.py`, `repair_v10.py`,
  `unwrap_outer_field.py`, `uniform_tables.py`, `generate_charts.py`,
  `audyt_bibliografii.py`, `audyt_liczb.py`, `audyt_idi.py`, `verify_creswell.py`,
  `insert_r4.py`, `insert_zalaczniki.py`, `insert_wstep_zak.py`, `insert_v75_images.py`,
  `skracanie_v8.py`, `v14_tables_fix_and_final.py`, `apply_r4_audit_fixes.py`.

These ~25 Python scripts are essentially **prototype source for the generator's
internal library**. Refactor them into a coherent `thesis_generator.docx_ops`,
`.audit`, `.verify`, `.format` module structure and most of the engine is built.
