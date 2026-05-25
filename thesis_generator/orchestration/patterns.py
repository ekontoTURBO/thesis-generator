"""The five subagent orchestration patterns (brief section 5).

These are the orchestration topologies that survived contact with reality in
the proven session. Each is parameterized so verifiers, writers, and rewriters
can be assembled from these building blocks instead of bespoke flows.

NOTE: this module gives the *interface* and the *prompt scaffolds*. The actual
Anthropic API calls happen inside the verify/* modules and writer.py. These
functions are the orchestration layer that owns concurrency + result merging.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Sequence


# ------------------------------------------------------------------
# Pattern 1: independent reviewer (zero-context)
# ------------------------------------------------------------------

async def independent_reviewer_dispatch(
    *,
    review_fn: Callable[[str], Awaitable[Any]],
    thesis_text: str,
) -> Any:
    """Pattern: a single subagent with ZERO context other than the thesis text.

    The proven session ran this 3 times (after v5, v9, v12). The fresh-eyes
    constraint is the entire value — the reviewer must NOT see verification
    reports, session history, or prior reviews.
    """
    return await review_fn(thesis_text)


# ------------------------------------------------------------------
# Pattern 2: one-source-per-Haiku (max parallel atomicity)
# ------------------------------------------------------------------

async def one_per_source(
    *,
    verify_fn: Callable[[dict], Awaitable[Any]],
    citations: Sequence[dict],
    max_parallel: int = 12,
) -> list[Any]:
    """Pattern: N parallel Haikus, one per (source, citation) pair.

    Each Haiku gets only its one citation. No cross-pollution between verifiers
    (which would let one bad verdict bias the others).
    """
    sem = asyncio.Semaphore(max_parallel)

    async def one(c: dict) -> Any:
        async with sem:
            return await verify_fn(c)

    return list(await asyncio.gather(*(one(c) for c in citations)))


# ------------------------------------------------------------------
# Pattern 3: Sonnet rewriter swarm (taste, not lookup)
# ------------------------------------------------------------------

async def sonnet_rewriter_swarm(
    *,
    rewrite_fn: Callable[[dict], Awaitable[dict]],
    sections: Sequence[dict],
    constraints: list[str],
    max_parallel: int = 8,
) -> list[dict]:
    """Pattern: Sonnet (not Haiku) for content rewrites because the task needs taste.

    Used 17 times in the proven session for the "shorten by 50%" pass. Each
    agent gets the same hard constraints (preserve every citation, every number,
    every transition sentence; cut repetitions, digressions, obvious filler).

    Each agent returns a JSON decision file (NOT a docx edit). The main session
    merges them via `docx_ops.apply_edits.apply_edits_from_json`.
    """
    sem = asyncio.Semaphore(max_parallel)

    async def one(s: dict) -> dict:
        async with sem:
            payload = {**s, "constraints": constraints}
            return await rewrite_fn(payload)

    return list(await asyncio.gather(*(one(s) for s in sections)))


# ------------------------------------------------------------------
# Pattern 4: analyst-then-builder (decide-then-apply)
# ------------------------------------------------------------------

@dataclass(slots=True)
class AnalystReport:
    name: str
    findings: list[dict]


async def analyst_then_builder(
    *,
    analyst_fns: list[Callable[[], Awaitable[AnalystReport]]],
    builder_fn: Callable[[list[AnalystReport]], Awaitable[Any]],
) -> Any:
    """Pattern: 3 analyst agents in parallel → 1 builder agent applies all fixes.

    Used for v12 finalization. Three parallel analysts (content integrity,
    figures/tables, citations) produce reports → one builder agent receives ALL
    three reports + the source file + the regulation → applies fixes atomically.

    This separates "decide what's wrong" from "write the fix" — and prevents
    the partial-application drift that bit the session when one agent tried
    to do both jobs.
    """
    reports = await asyncio.gather(*(fn() for fn in analyst_fns))
    return await builder_fn(list(reports))


# ------------------------------------------------------------------
# Pattern 5: JSON decision file (string-escape disaster prevention)
# ------------------------------------------------------------------

def assert_well_formed_decision_file(path: str) -> None:
    """Validate a subagent's JSON output before applying it.

    Gotcha #8: 7 of 17 shortening agents wrote malformed JSON (ASCII quotes
    inside string values, f-string concatenation). Always have the subagent
    use `json.dump()` AND validate before consuming.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)  # raises JSONDecodeError if malformed
    if "edits" not in data:
        raise ValueError(f"{path}: missing 'edits' key")
    for i, e in enumerate(data["edits"]):
        for k in ("para", "old", "new"):
            if k not in e:
                raise ValueError(f"{path}: edit[{i}] missing '{k}'")
        if not isinstance(e["para"], int):
            raise TypeError(f"{path}: edit[{i}].para must be int, got {type(e['para']).__name__}")
