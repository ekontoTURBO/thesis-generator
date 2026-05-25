"""LLM backend — subprocess adapter for `claude -p` (Claude Code CLI).

Uses the user's Claude Code subscription via OAuth/keychain instead of a raw
Anthropic API key. Zero billing setup required; the same auth that powers
their interactive Claude Code sessions powers the thesis generator's writer,
verifiers, and reviewer.
"""

from thesis_generator.llm.claude_cli import ClaudeCLI, ClaudeCLIError, ClaudeResponse

__all__ = ["ClaudeCLI", "ClaudeCLIError", "ClaudeResponse"]
