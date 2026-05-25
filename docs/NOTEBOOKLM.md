# NotebookLM setup

> **Credit:** Ring C runs on top of the [NotebookLM Claude Code Skill](https://github.com/PleasePrompto/notebooklm-skill) by **[Please Prompto!](https://github.com/PleasePrompto)** (MIT, 2025). All the browser automation, library management, persistent auth, and Gemini-grounded query plumbing is theirs — we just call their CLI as a subprocess. If this verification quality saves you from a missed citation, the credit belongs to them.

NotebookLM is the **source-grounded verification engine** of this pipeline. Without it, Ring C is disabled and the verification quality drops materially (in the proven session, Ring C caught hallucinations Ring B had marked OK on multiple citations).

## What you need

1. A Google account with access to NotebookLM (free; available at <https://notebooklm.google.com>)
2. The **notebooklm** Claude Code skill installed at `~/.claude/skills/notebooklm/`
3. A NotebookLM library that mirrors `inputs/sources_dir/` (every PDF you cite must be in the library)

## Installing the skill

```bash
# From your shell — installs into the standard Claude Code skills directory
cd ~/.claude/skills
git clone https://github.com/<...>/notebooklm.git
# (Replace with the actual skill repo once published)
```

Verify:

```bash
ls ~/.claude/skills/notebooklm/
# Should show: SKILL.md, scripts/, requirements.txt, ...
```

## Authentication (one-time)

```bash
python ~/.claude/skills/notebooklm/scripts/run.py auth_manager.py setup
```

A browser window will open. Log in to Google. The skill stores your session locally; subsequent queries reuse it.

```bash
# Verify
python ~/.claude/skills/notebooklm/scripts/run.py auth_manager.py status
# Should print: ✓ authenticated
```

Or via the CLI:

```bash
tg notebooklm auth
tg notebooklm status --project-dir my-thesis
```

### Auth refresh (every ~30 days)

The browser session expires roughly every 30 days. The skill prints a warning when its state file is more than 7 days old:

```
⚠️ Browser state is 13.1 days old, may need re-authentication
```

That warning is informational — queries usually still work until Google actually invalidates the cookie. When they start failing, re-run:

```bash
tg notebooklm auth
```

A new browser window will open; log in again. The session is then good for another ~30 days.

**Pro tip:** run `tg verify-env <project>` before any long Ring C batch — it does a live auth check and surfaces the problem before you sink 30 minutes into a failed verification run.

## Building your library

In the NotebookLM web UI:
1. Create a new notebook
2. Upload every PDF that lives in `inputs/sources_dir/` (drag-and-drop works)
3. Wait for NotebookLM to finish indexing (a few minutes)
4. Copy the URL from the address bar: `https://notebooklm.google.com/notebook/<UUID>`
5. Paste it into `thesis.yaml` under `notebooklm.library_url`

**Library must be a superset of inputs/sources_dir.** If you cite something Ring C can't find, you'll get `UNKNOWN` verdicts (still useful — flags the source as not uploaded — but not as strong as a direct verification).

## How queries work

Each verification asks one focused question, ≤ 400 words. Example (the actual format the proven session used 38 times):

```
Weryfikacja jednego cytowania z pracy licencjackiej.
Podaj VERDICT: OK / NIEŚCISŁE / BŁĘDNE + dosłowny cytat ze źródła.
Jeśli VERDICT nie jest OK, zaproponuj jednozdaniową korektę po linii KOREKTA:.

ŹRÓDŁO: Hoch 2002, Journal of Consumer Research
PARAFRAZA W PRACY: "Konsumenci ufają rekomendacjom innych konsumentów bardziej niż reklamie."
CYTOWANA STRONA: s. 137
```

NotebookLM returns Gemini's source-grounded answer over the whole library. Our adapter parses out the VERDICT, EXCERPT, and KOREKTA.

## Critical: one question at a time

NotebookLM truncates multi-part questions silently. **Never** ask "verify these 5 citations." Always one citation per query. The adapter enforces this by rejecting questions over `max_words_per_query` (default 400) and by serializing internally — `parallel_queries: 3` is the safe ceiling for the underlying browser automation.

## Latency

Expect 30 seconds to 5 minutes per query. The adapter runs verification batches in the background; `tg run` will wait for completion before moving to the next phase.

For a 50-citation thesis with `parallel_queries: 3`, expect ~30 minutes for a full Ring C pass. Plan accordingly.

## Fallback (planned — not yet implemented)

If NotebookLM is unavailable, a planned local-RAG fallback uses `pgvector` or `chromadb` over the same PDF corpus. Verification quality is lower (smaller context, no Gemini reasoning) but the pipeline still runs. See [issue #3](https://github.com/...) when published.
