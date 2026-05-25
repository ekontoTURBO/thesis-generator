"""Ring C — NotebookLM source-grounded cross-check.

For every citation in the draft, ask NotebookLM (over the user's whole library)
whether the paraphrase is supported. NotebookLM sees the *whole library* at once,
so it catches the case where the cited PDF exists but the claim isn't in it
(Ring B can't catch this — Ring B only opens the one PDF the author said).

Brief observation: in the proven session, Ring C caught:
- "Heilman 2000 is NOT about sampling — title in bibliography is wrong"
- "Rosario does NOT claim experience-component thesis"
- "Leung is original empirical study, not meta-analysis"

Per the proven pattern: one question per citation, ≤ 400 words, never multi-part.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path

from thesis_generator.config import ThesisProject
from thesis_generator.notebooklm import (
    NotebookLMAdapter,
    NotebookLMError,
    VerificationResult,
    VerificationVerdict,
)


@dataclass(slots=True)
class RingCResult:
    results: list[VerificationResult]
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.verdict == VerificationVerdict.OK for r in self.results)

    def disagreements_with(self, ring_b: "list[CitationVerdictB]" | None) -> list[str]:  # type: ignore[name-defined]
        """The valuable case: Ring B says OK, Ring C says BŁĘDNE (or vice versa)."""
        if not ring_b:
            return []
        b_by_key = {f"{v.citation[0]}_{v.citation[1]}": v.verdict for v in ring_b}
        disagree = []
        for r in self.results:
            b = b_by_key.get(r.citation_key)
            if b and b != r.verdict.value:
                disagree.append(f"{r.citation_key}: Ring B={b}, Ring C={r.verdict.value}")
        return disagree

    def to_report(self) -> str:
        ok = sum(1 for r in self.results if r.verdict == VerificationVerdict.OK)
        wrong = sum(1 for r in self.results if r.verdict == VerificationVerdict.WRONG)
        inaccurate = sum(1 for r in self.results if r.verdict == VerificationVerdict.INACCURATE)
        unknown = sum(1 for r in self.results if r.verdict == VerificationVerdict.UNKNOWN)

        lines = ["# Ring C — NotebookLM source-grounded verification\n"]
        lines.append(f"OK: {ok} | NIEŚCISŁE: {inaccurate} | BŁĘDNE: {wrong} | UNKNOWN: {unknown}\n")
        lines.append("\n| Citation | Verdict | Excerpt |")
        lines.append("|---|---|---|")
        for r in self.results:
            excerpt = r.excerpt.replace("|", "\\|")[:80]
            lines.append(f"| {r.citation_key} | {r.verdict.value} | {excerpt} |")
        problems = [r for r in self.results if r.verdict != VerificationVerdict.OK]
        if problems:
            lines.append("\n## Detailed claims that need attention\n")
            for r in problems:
                lines.append(f"### {r.citation_key} — `{r.verdict.value}`")
                lines.append(f"\n> Paraphrase: _{r.paraphrase}_\n")
                if r.excerpt:
                    lines.append(f"NotebookLM excerpt: «{r.excerpt}»\n")
                if r.correction:
                    lines.append(f"**Proposed correction:** {r.correction}\n")
                # Full raw answer for debugging — NotebookLM often replies in
                # free-form prose without the requested VERDICT structure.
                if r.raw_answer:
                    snippet = r.raw_answer[:1500].replace("\n", "\n> ")
                    lines.append(f"\n<details><summary>Raw NotebookLM response</summary>\n\n> {snippet}\n\n</details>\n")
        if self.notes:
            lines.append("\n## Notes\n")
            lines.extend(f"- {n}" for n in self.notes)
        return "\n".join(lines)


async def run_ring_c(
    project: ThesisProject,
    paraphrases: dict[tuple[str, str], dict[str, str | None]],
) -> RingCResult:
    """Cross-check every citation against the NotebookLM library.

    `paraphrases` is the same dict shape used in Ring B — one entry per citation
    with `paraphrase` and optional `cited_page`.
    """
    if project.notebooklm is None:
        return RingCResult(
            results=[],
            notes=["Ring C skipped: no NotebookLM configured in thesis.yaml."],
        )

    try:
        adapter = NotebookLMAdapter(
            library_url=project.notebooklm.library_url,
            library_name=project.notebooklm.library_name,
            max_words_per_query=project.notebooklm.max_words_per_query,
            parallel_queries=project.notebooklm.parallel_queries,
            timeout_seconds=project.notebooklm.timeout_seconds,
        )
    except NotebookLMError as e:
        return RingCResult(results=[], notes=[f"Adapter init failed: {e}"])

    if not adapter.check_auth():
        return RingCResult(
            results=[],
            notes=[
                "NotebookLM not authenticated. Run: "
                "`python ~/.claude/skills/notebooklm/scripts/run.py auth_manager.py setup`"
            ],
        )

    citations = [
        {
            "key": f"{c[0]}_{c[1]}",
            "paraphrase": meta.get("paraphrase") or "",
            "cited_page": meta.get("cited_page"),
            "source_author_year": f"{c[0]} {c[1]}",
        }
        for c, meta in paraphrases.items()
    ]
    results = await adapter.verify_batch(citations)
    return RingCResult(results=results)


def save_report(result: RingCResult, project: ThesisProject) -> Path:
    out = project.reports_dir() / "ring_c_notebooklm.md"
    out.write_text(result.to_report(), encoding="utf-8")
    return out
