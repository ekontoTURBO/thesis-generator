"""Subprocess adapter for `claude -p` (Claude Code CLI in headless mode).

Why this exists: the original architecture used the Anthropic SDK with raw
`ANTHROPIC_API_KEY`, which made the thesis-generator hard to adopt — every
user needed to sign up for API access and configure billing. Since most users
of this tool already use Claude Code interactively, we shell out to the same
CLI in print mode and reuse their existing subscription / OAuth auth.

Trade-offs vs the SDK:
+ No API key, no billing setup, runs anywhere Claude Code is installed
+ Same model access (Opus / Sonnet / Haiku) via `--model`
+ Tool use works (`--allowedTools "Bash"` for Ring B reading PDFs)
+ Structured output supported (`--json-schema`)
+ Concurrent calls = N separate processes (no shared client state to leak)
- Per-call startup overhead (~2-5s) — fine for our minutes-long pipeline
- Output parsing happens via stdout (we strip noise like login banners)
- Streaming token-by-token is possible but we don't need it

Each call is a one-shot: spawn `claude -p ...`, capture stdout, exit.
Concurrency is via asyncio.subprocess_exec with a Semaphore bound.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


class ClaudeCLIError(RuntimeError):
    """Raised when the `claude` CLI is missing, unauthenticated, or returns non-zero."""


@dataclass(slots=True)
class ClaudeResponse:
    """One CLI invocation's output."""

    text: str
    """Plain-text response (stdout, trimmed)."""
    json_payload: dict | None = None
    """If `output_format=json` was used, the parsed JSON message envelope."""
    extracted_json: dict | None = None
    """If `extract_json=True` was used, the first {...} block found in `text`."""
    duration_seconds: float = 0.0
    returncode: int = 0
    stderr_tail: str = ""


# Common alias → full model ID mapping. Aliases work in `claude --model`, but
# we accept the full IDs from `thesis.yaml` for explicitness and pass them
# through unchanged.
MODEL_ALIASES = {
    "opus": "opus",
    "sonnet": "sonnet",
    "haiku": "haiku",
}


class ClaudeCLI:
    """Subprocess-based LLM client. Honors the user's Claude Code auth.

    Usage:
        cli = ClaudeCLI()
        resp = await cli.complete(model="haiku", system="Be brief.", user="Hi")
        print(resp.text)

    For tool-using calls (Ring B verification of PDFs via Bash):
        resp = await cli.complete(
            model="haiku",
            system="You verify citations.",
            user="<verify prompt>",
            allowed_tools=["Bash"],
            max_budget_usd=0.50,
        )
    """

    def __init__(
        self,
        *,
        claude_bin: str | None = None,
        default_cwd: Path | None = None,
        max_concurrent: int = 4,
    ) -> None:
        self.claude_bin = claude_bin or shutil.which("claude")
        if not self.claude_bin:
            raise ClaudeCLIError(
                "`claude` CLI not found on PATH. Install Claude Code from "
                "https://claude.com/code, then restart your shell."
            )
        # Default cwd is a fresh temp dir each instance — avoids picking up
        # the user's CLAUDE.md, .claude/agents, or stray memory from the
        # current working directory.
        self.default_cwd = default_cwd or Path(tempfile.mkdtemp(prefix="tg_claude_"))
        self._sem = asyncio.Semaphore(max_concurrent)

    # ------------------------------------------------------------------ Auth

    def check_auth(self) -> tuple[bool, str]:
        """Return (ok, message). Runs a trivial query to confirm OAuth works."""
        try:
            proc = subprocess.run(
                [
                    self.claude_bin,
                    "--print",
                    "--model",
                    "haiku",
                    "--no-session-persistence",
                    "--permission-mode",
                    "bypassPermissions",
                    "--tools",
                    "",
                    "--system-prompt",
                    "Reply with exactly one word: ok",
                    "auth check",
                ],
                cwd=str(self.default_cwd),
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "auth check timed out (60s)"
        out = (proc.stdout or "").strip().lower()
        if "not logged in" in out or "/login" in out:
            return False, "Not logged in. Run `claude /login` interactively."
        if proc.returncode != 0:
            return False, f"claude CLI returned {proc.returncode}: {(proc.stderr or '')[:200]}"
        return True, f"authenticated (test reply: {out[:60]!r})"

    # ------------------------------------------------------------------ Sync

    def complete_sync(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        allowed_tools: Sequence[str] | None = None,
        json_schema: dict | None = None,
        max_budget_usd: float | None = None,
        timeout: int = 600,
        extract_json: bool = False,
    ) -> ClaudeResponse:
        """Synchronous one-shot. For background workers prefer `complete()` (async)."""
        cmd, env = self._build_cmd(
            model=model,
            system=system,
            allowed_tools=allowed_tools,
            json_schema=json_schema,
            max_budget_usd=max_budget_usd,
        )
        proc = subprocess.run(
            cmd,
            input=user,
            cwd=str(self.default_cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return self._build_response(proc.stdout, proc.stderr, proc.returncode, extract_json=extract_json)

    # ------------------------------------------------------------------ Async

    async def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        allowed_tools: Sequence[str] | None = None,
        json_schema: dict | None = None,
        max_budget_usd: float | None = None,
        timeout: int = 600,
        extract_json: bool = False,
    ) -> ClaudeResponse:
        async with self._sem:
            return await asyncio.to_thread(
                self.complete_sync,
                model=model,
                user=user,
                system=system,
                allowed_tools=allowed_tools,
                json_schema=json_schema,
                max_budget_usd=max_budget_usd,
                timeout=timeout,
                extract_json=extract_json,
            )

    async def complete_many(self, requests: Sequence[dict]) -> list[ClaudeResponse]:
        """Run many completions in parallel (bounded by max_concurrent)."""
        return list(await asyncio.gather(*(self.complete(**r) for r in requests)))

    # ------------------------------------------------------------------ Internal

    def _build_cmd(
        self,
        *,
        model: str,
        system: str | None,
        allowed_tools: Sequence[str] | None,
        json_schema: dict | None,
        max_budget_usd: float | None,
    ) -> tuple[list[str], dict[str, str]]:
        # Map our full model IDs to CLI aliases when possible (CLI's --model
        # accepts both, but aliases are forward-compatible).
        cli_model = MODEL_ALIASES.get(model, model)

        cmd: list[str] = [
            self.claude_bin,
            "--print",
            "--model", cli_model,
            "--no-session-persistence",
            "--permission-mode", "bypassPermissions",
            "--exclude-dynamic-system-prompt-sections",
        ]

        # Tools — default to none. Pass an empty string to fully disable,
        # OR a space-separated list when allowed_tools is set.
        if allowed_tools:
            cmd += ["--allowedTools", " ".join(allowed_tools)]
        else:
            cmd += ["--tools", ""]

        if system:
            # Use --system-prompt (full override) so the writer's voice isn't
            # diluted by Claude Code's default coding-assistant identity.
            cmd += ["--system-prompt", system]

        # NOTE: We intentionally do NOT pass `--json-schema` here.
        # The CLI's schema validation only takes effect when combined with
        # `--output-format json`, which wraps the response in a result envelope
        # (`{type, structured_output: {text: "<schema-validated JSON string>"}, ...}`).
        # That envelope is harder to handle than a plain stdout, and passing
        # `--json-schema` alone silently swallows the output.
        # Until we add envelope support, callers should set `extract_json=True`
        # and instruct the model in the prompt to emit a JSON block.
        if json_schema is not None:
            # Make this visible in stderr_tail without spamming stdout.
            import warnings

            warnings.warn(
                "json_schema is currently a no-op; rely on extract_json + prompt for JSON output.",
                stacklevel=2,
            )

        if max_budget_usd is not None:
            cmd += ["--max-budget-usd", str(max_budget_usd)]

        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return cmd, env

    @staticmethod
    def _build_response(
        stdout: str | None, stderr: str | None, returncode: int, *, extract_json: bool
    ) -> ClaudeResponse:
        stdout = stdout or ""
        stderr = stderr or ""
        text = stdout.strip()

        if "Not logged in" in text or "Please run /login" in text:
            raise ClaudeCLIError(
                "Claude Code is not authenticated. Run `claude /login` once, then retry."
            )

        if returncode != 0:
            raise ClaudeCLIError(
                f"claude --print failed (exit {returncode}): {stderr[:500]}"
            )

        extracted = None
        if extract_json:
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if m:
                try:
                    extracted = json.loads(m.group(0))
                except json.JSONDecodeError:
                    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", m.group(0).strip(), flags=re.MULTILINE)
                    try:
                        extracted = json.loads(cleaned)
                    except json.JSONDecodeError:
                        extracted = None

        return ClaudeResponse(
            text=text,
            extracted_json=extracted,
            returncode=returncode,
            stderr_tail=stderr[-500:],
        )
