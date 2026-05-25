"""NotebookLM CLI skill adapter.

Subprocess-based wrapper around the `notebooklm` Claude Code skill. Each query
spawns a fresh `python scripts/run.py ask_question.py ...` invocation, which
handles its own venv, browser session, and auth. We never speak the browser
protocol directly.

Why subprocess and not HTTP: NotebookLM has no public API. The skill does
browser automation. Subprocess isolation means a crashed browser session can't
take down our orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

from tenacity import retry, stop_after_attempt, wait_exponential


class NotebookLMError(RuntimeError):
    """Raised when the NotebookLM skill is unavailable, unauthenticated, or rejects a query."""


class VerificationVerdict(str, Enum):
    """Trinary verdict format the proven session used in every verification prompt."""

    OK = "OK"
    INACCURATE = "NIEŚCISŁE"
    WRONG = "BŁĘDNE"
    UNKNOWN = "UNKNOWN"
    """Used when NotebookLM returns 'I don't see that in the sources' — usually
    means the cited PDF wasn't actually uploaded to the library."""


@dataclass(slots=True)
class VerificationResult:
    """One citation's verification outcome."""

    citation_key: str  # e.g. "Hoch_2002"
    paraphrase: str  # the verbatim sentence from the draft being verified
    cited_page: str | None
    verdict: VerificationVerdict
    excerpt: str  # literal quote from the source as returned by NotebookLM
    raw_answer: str  # full Gemini answer for the audit trail
    correction: str | None = None  # suggested rewrite if NIEŚCISŁE/BŁĘDNE


def _default_skill_dir() -> Path:
    """Locate the notebooklm skill in the user's Claude config."""
    candidates = [
        Path.home() / ".claude" / "skills" / "notebooklm",
        Path(os.environ.get("CLAUDE_SKILLS_DIR", "")) / "notebooklm"
        if os.environ.get("CLAUDE_SKILLS_DIR")
        else None,
    ]
    for c in candidates:
        if c and c.exists():
            return c
    raise NotebookLMError(
        "NotebookLM skill not found. Install it into `~/.claude/skills/notebooklm/` "
        "or set CLAUDE_SKILLS_DIR. See docs/NOTEBOOKLM.md."
    )


class NotebookLMAdapter:
    """Thin subprocess wrapper.

    Usage:
        adapter = NotebookLMAdapter(library_url="https://notebooklm.google.com/notebook/...")
        adapter.check_auth()
        results = await adapter.verify_batch([
            {"key": "Hoch_2002", "paraphrase": "...", "cited_page": "s. 137"},
            ...
        ])
    """

    def __init__(
        self,
        library_url: str,
        library_name: str = "",
        skill_dir: Path | None = None,
        max_words_per_query: int = 400,
        parallel_queries: int = 3,
        timeout_seconds: int = 300,
    ) -> None:
        self.library_url = library_url
        self.library_name = library_name
        self.skill_dir = skill_dir or _default_skill_dir()
        self.max_words_per_query = max_words_per_query
        self.parallel_queries = parallel_queries
        self.timeout_seconds = timeout_seconds
        self._python = shutil.which("python") or shutil.which("python3")
        if not self._python:
            raise NotebookLMError("No `python` on PATH.")

    # ------------------------------------------------------------------ Auth

    def check_auth(self) -> bool:
        """Return True if the NotebookLM skill is authenticated.

        Runs `python scripts/run.py auth_manager.py status`. If unauthenticated,
        the caller should prompt the user to run `python scripts/run.py
        auth_manager.py setup` interactively (browser-visible flow).
        """
        proc = self._run_skill(["auth_manager.py", "status"], timeout=60)
        return "authenticated" in proc.stdout.lower() or proc.returncode == 0

    # ------------------------------------------------------------------ Single query

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=10, max=60),
        reraise=True,
    )
    def ask(self, question: str) -> str:
        """One-shot question against the configured library. Returns Gemini's raw answer."""
        if len(question.split()) > self.max_words_per_query:
            raise NotebookLMError(
                f"Question exceeds {self.max_words_per_query} words. NotebookLM truncates silently — split it up."
            )
        proc = self._run_skill(
            [
                "ask_question.py",
                "--question",
                question,
                "--notebook-url",
                self.library_url,
            ],
            timeout=self.timeout_seconds,
        )
        if proc.returncode != 0:
            raise NotebookLMError(f"ask_question.py failed: {proc.stderr[:1000]}")
        return proc.stdout.strip()

    # ------------------------------------------------------------------ Verification batch

    async def verify_batch(
        self, citations: Sequence[dict[str, str]]
    ) -> list[VerificationResult]:
        """Verify many citations in parallel (bounded by `parallel_queries`).

        Each citation dict needs keys: `key`, `paraphrase`, `cited_page` (optional),
        `source_author_year` (optional but recommended).
        """
        sem = asyncio.Semaphore(self.parallel_queries)

        async def one(c: dict[str, str]) -> VerificationResult:
            async with sem:
                return await asyncio.to_thread(self._verify_one, c)

        return await asyncio.gather(*(one(c) for c in citations))

    def _verify_one(self, citation: dict[str, str]) -> VerificationResult:
        """Two-step verification:
            Step 1: NotebookLM grounds the claim (browser, source-aware).
            Step 2: Claude API extracts a structured VERDICT from the grounded
                    content (fast, deterministic format).

        The two-step design exists because e2e testing revealed that NotebookLM
        ignores VERDICT-format instructions and returns free-form academic prose
        with citations. Parsing that prose for verdicts is unreliable. So we
        let NotebookLM do what it's good at (grounding) and Claude do what it's
        good at (structured output).

        If `ANTHROPIC_API_KEY` is not set, step 2 is skipped and the verdict is
        whatever the strict parser can extract directly (usually UNKNOWN).
        """
        key = citation["key"]
        paraphrase = citation["paraphrase"]
        cited_page = citation.get("cited_page")
        source_ref = citation.get("source_author_year", key.replace("_", " "))

        # Step 1: NotebookLM grounding query
        question = self._build_grounding_question(source_ref, paraphrase, cited_page)
        try:
            raw = self.ask(question)
        except NotebookLMError as e:
            return VerificationResult(
                citation_key=key,
                paraphrase=paraphrase,
                cited_page=cited_page,
                verdict=VerificationVerdict.UNKNOWN,
                excerpt="",
                raw_answer=f"[NotebookLMError] {e}",
            )

        # Step 2: try strict parser first (cheap)
        verdict = self._parse_verdict(raw)
        excerpt = self._parse_excerpt(raw)
        correction = None

        # Step 2b: if parser couldn't extract a verdict, delegate to Claude.
        if verdict == VerificationVerdict.UNKNOWN and self._claude_judge_available():
            verdict, excerpt, correction = self._judge_with_claude(paraphrase, source_ref, raw)

        if verdict != VerificationVerdict.OK and correction is None:
            correction = self._parse_correction(raw)

        return VerificationResult(
            citation_key=key,
            paraphrase=paraphrase,
            cited_page=cited_page,
            verdict=verdict,
            excerpt=excerpt,
            raw_answer=raw,
            correction=correction,
        )

    # ---- Step 2 helpers: Claude judge (via `claude -p`) ----

    @staticmethod
    def _claude_judge_available() -> bool:
        """True iff the `claude` CLI is on PATH (default LLM backend).

        Falls back to True if ANTHROPIC_API_KEY is set, since the legacy SDK
        path also still works inside `_judge_with_claude`.
        """
        return bool(shutil.which("claude")) or bool(os.environ.get("ANTHROPIC_API_KEY"))

    @staticmethod
    def _judge_with_claude(
        paraphrase: str, source_ref: str, grounded_content: str
    ) -> tuple[VerificationVerdict, str, str | None]:
        """Ask Claude Haiku (via `claude -p`) to judge OK/NIEŚCISŁE/BŁĘDNE.

        Uses the user's Claude Code subscription (no API key needed). Returns
        (verdict, excerpt, correction_or_None). On any failure returns UNKNOWN
        so the caller can still produce an honest report.
        """
        try:
            from thesis_generator.llm import ClaudeCLI, ClaudeCLIError
        except ImportError:
            return VerificationVerdict.UNKNOWN, "", None

        prompt = (
            f"Sędziujesz cytowanie w pracy licencjackiej na bazie source-grounded content z NotebookLM.\n\n"
            f"ŹRÓDŁO: {source_ref}\n"
            f'PARAFRAZA W PRACY: "{paraphrase}"\n\n'
            f"GROUNDED CONTENT (z NotebookLM, oparte o całą bibliotekę):\n"
            f"---\n{grounded_content[:6000]}\n---\n\n"
            f"Twoja praca: na podstawie grounded content oceń czy parafraza:\n"
            f"  • OK — wiernie oddaje treść źródła\n"
            f"  • NIEŚCISŁE — wymaga uściślenia, ale ogólny sens się zgadza\n"
            f"  • BŁĘDNE — przypisuje źródłu coś czego ono nie mówi\n\n"
            f"ODPOWIEDZ DOKŁADNIE W TYM FORMACIE (każda linia od nowej linii):\n"
            f"VERDICT: <OK|NIEŚCISŁE|BŁĘDNE>\n"
            f'EXCERPT: "<dosłowny cytat z grounded content który najlepiej uzasadnia werdykt, max 300 znaków>"\n'
            f"KOREKTA: <jeśli VERDICT != OK, jednozdaniowa poprawka parafrazy>"
        )
        try:
            cli = ClaudeCLI()
            resp = cli.complete_sync(model="haiku", user=prompt, timeout=120)
            text = resp.text
        except ClaudeCLIError:
            return VerificationVerdict.UNKNOWN, "", None
        verdict = NotebookLMAdapter._parse_verdict(text)
        excerpt = NotebookLMAdapter._parse_excerpt(text)
        correction = NotebookLMAdapter._parse_correction(text) if verdict != VerificationVerdict.OK else None
        return verdict, excerpt, correction

    # ---- prompt templating ----

    @staticmethod
    def _build_verification_question(source_ref: str, paraphrase: str, cited_page: str | None) -> str:
        """Legacy single-step verification prompt (kept for callers that want it).

        Verdict reliability is low because NotebookLM tends to ignore the
        VERDICT-format directive. Prefer the two-step path via `_verify_one`
        (grounding here → Claude judge in `_judge_with_claude`).
        """
        page_line = f"CYTOWANA STRONA: {cited_page}\n" if cited_page else ""
        return (
            "Weryfikacja jednego cytowania z pracy licencjackiej.\n"
            "Podaj VERDICT: OK / NIEŚCISŁE / BŁĘDNE + dosłowny cytat ze źródła.\n"
            "Jeśli VERDICT nie jest OK, zaproponuj jednozdaniową korektę po linii KOREKTA:.\n\n"
            f"ŹRÓDŁO: {source_ref}\n"
            f'PARAFRAZA W PRACY: "{paraphrase}"\n'
            f"{page_line}"
        )

    @staticmethod
    def _build_grounding_question(source_ref: str, paraphrase: str, cited_page: str | None) -> str:
        """Step-1 prompt: ask NotebookLM what the *named source specifically* says.

        Designed for NotebookLM's strength — source-grounded prose answers. The
        critical refinement (after e2e: Trusov/Berger were UNKNOWN because the
        previous prompt let NotebookLM ramble about adjacent topics) is to
        FORCE the answer to come from the ONE named source, not the whole library.

        The Claude judge in step 2 produces the structured VERDICT from this
        grounded content.
        """
        page_hint = f" (cytowana strona: {cited_page})" if cited_page else ""
        return (
            f"Odpowiadaj WYŁĄCZNIE na podstawie źródła: **{source_ref}**{page_hint}.\n"
            f"NIE używaj żadnych innych źródeł z biblioteki, nawet jeśli są tematycznie pokrewne.\n\n"
            f"Sprawdzana parafraza z pracy licencjackiej:\n"
            f'"{paraphrase}"\n\n'
            f"Wykonaj kolejno:\n"
            f"1. Znajdź w **{source_ref}** najbliższy fragment dotyczący tej tezy.\n"
            f'2. Zacytuj go dosłownie w cudzysłowie (max 300 znaków).\n'
            f"3. Krótko wyjaśnij, czy parafraza wiernie oddaje treść źródła.\n\n"
            f"Jeśli {source_ref} NIE zawiera niczego na ten temat — napisz wprost: "
            f"„Źródło nie zawiera tej tezy.\" Nie podawaj cytatów z innych źródeł."
        )

    @staticmethod
    def _parse_verdict(raw: str) -> VerificationVerdict:
        """Strict: require `VERDICT:` at line start to avoid false positives.

        Architectural note: NotebookLM tends to return free-form academic answers
        with citations, NOT structured VERDICT lines. For reliable verdicts, the
        correct pipeline is two-step: NotebookLM grounds → Claude API extracts
        verdict from the grounded content. See `judge_with_claude` for that path.
        """
        # Only accept VERDICT at the start of a line (with optional whitespace).
        m = re.search(r"(?m)^\s*VERDICT\s*[:=]\s*(OK|NIEŚCISŁE|NIESCISLE|BŁĘDNE|BLEDNE)\b",
                      raw, re.IGNORECASE)
        if not m:
            return VerificationVerdict.UNKNOWN
        v = m.group(1).upper().replace("NIESCISLE", "NIEŚCISŁE").replace("BLEDNE", "BŁĘDNE")
        return VerificationVerdict(v)

    @staticmethod
    def _parse_excerpt(raw: str) -> str:
        """Extract EXCERPT field — must be marked explicitly to avoid false positives.

        Looks for `EXCERPT: "..."` or `CYTAT: "..."` or `Cytat:` — only after the
        marker. Doesn't grab arbitrary quoted strings (which often turn out to be
        the question echoed back).
        """
        m = re.search(r'(?:EXCERPT|CYTAT|Dosłowny cytat)\s*[:=]\s*[„"«]([^"„»]{20,500})["»"]?',
                      raw, re.IGNORECASE)
        return m.group(1) if m else ""

    @staticmethod
    def _parse_correction(raw: str) -> str | None:
        m = re.search(r"KOREKTA\s*[:=]\s*(.+?)(?:\n\n|\Z)", raw, re.DOTALL | re.IGNORECASE)
        return m.group(1).strip() if m else None

    # ------------------------------------------------------------------ Library management

    def list_libraries(self) -> list[dict]:
        """List configured NotebookLM libraries (for `tg notebooklm list`)."""
        proc = self._run_skill(["notebook_manager.py", "list"], timeout=60)
        if proc.returncode != 0:
            raise NotebookLMError(proc.stderr)
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return [{"raw": proc.stdout}]

    # ------------------------------------------------------------------ Internal subprocess

    def _run_skill(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        """Run `python scripts/run.py <script> <args...>` inside the skill dir."""
        cmd = [self._python, "scripts/run.py", *args]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            cmd,
            cwd=str(self.skill_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
