---
name: engineering
description: Use when a non-trivial software task needs setup, planning, implementation, debugging, review, verification, impact assessment, completion, or engineering maintenance.
---

# Engineering

## What Engineering does

Engineering makes non-trivial changes verifiable from request through
completion, across instructions, contracts, tests, and approval boundaries.

The orchestrator independently accepts the exact artifact. Engineering preserves
native Codex and Claude semantics, tools, permissions, autonomy, concurrency,
and one writer per shared resource.

Treat feedback as seed evidence. Before dispatch, reconstruct the decision
ledger, approved intent, dependencies, sibling flows, and bounded workspace.
For material redesign, replacement, deletion, or simplification, map every
baseline outcome as INCLUDED, REPLACED, DEFERRED, or EXCLUDED. Replacement
needs independent equivalence; deferral/exclusion needs exact owner authority.
Unknown traceability permits advisory analysis, never accepted readiness.
Intent-impacting work needs external owner intent, a controller-injected
baseline, and an independently accepted exact-artifact token before separate
native approval. New owner approvals, exceptions, audits, equivalence, and
traceability host attestations use a signed canonical-default-branch anchor,
not a candidate signer file; auditor/reviewer principal equals declared role.
Legacy traceability attestations remain readable but cannot establish current
trust. Impact derives from graph context plus authorized, approved, and changed
paths; completion checks rename endpoints. An install token binds the accepted
clean source bundle and is rechecked before/after staging; it never replaces
native install approval. Reject narrow handoffs and proxy-only results.

Model selection stays native; delivery records requested, actual, and fallback
facts. Research separates facts, assumptions, citations, and Unknowns.

Engineering completion runs automatically before claiming non-trivial work is ready;
controller commands are diagnostics and CI interfaces.
Use `engineering map`; see `references/controller-contract.md` for protocols.

## Graph and context

Engineering is local-first. Graphify supplies the base graph and a deterministic
overlay supplies verified links, decisions, and checks. Claims use the canonical default-branch checkpoint; missing/incompatible Graphify blocks graph claims.
Same-machine worktrees share Git-common checkpoints; other machines recreate
evidence. A cold start builds, an incremental change updates, and a cache hit
reuses validated evidence.

## Setup and autonomy

For an unmanaged project, work is advisory and writes nothing. Setup previews
first, needs explicit authority, and preserves instructions/hooks. Graphify
installation or upgrade is separately approved; the first eligible commit
establishes the canonical checkpoint.

Autonomy is Guided, Collaborative (default), or Steward. Guided asks before
project changes; Collaborative handles routine in-scope work; Steward may also
process safe queued work once. None schedules or authorizes consequential work;
a one-off run does not change the saved autonomy level.

## What always needs approval

Treat approval presence and a decision to request approval again as separate. Exact
authority persists across unchanged turns, retries, callbacks, and bounded
repair epochs. Re-request only when it is missing, revoked, consumed, expired,
or its project, target, action, scope, safeguards, or epoch changes. Full Access
is technical permission, never business authority. Native destructive and
connector approvals remain mandatory. Setup, Graphify, architecture,
publication, merge, deployment, release, production, security, privacy,
credentials, finance, persisted contracts, and ambiguity stay gated. Exhausted
workers freeze as `PAUSED_AWAITING_CENTRAL_ADJUDICATION`; they do not re-ask or
retire automatically.

`engineering retrospect` is bounded and read-only; host reconciliation stays
advisory until recorded.

## Completion and maintenance

Missing, stale, conflicting, or role-incomplete evidence stays Unknown; tests
do not erase incidents. Completion compares impact and records checks.

Maintenance is one foreground pass over a local queue and does not run in the
background; it repairs only mechanically verified work. Historical/advisory traceability debt remains
visible without blocking unrelated work. An orchestrator may dispatch
disjoint maintenance lanes in parallel, while each shared-ledger mutation and
overlapping writer serializes under the existing lock. Preparation blocks
for checkpoint identity/integrity, required current-contract evidence, or
dependent graph/release acceptance.

Reusable learning starts project-local; promotion needs a second project and
explicit approval. Promote means apply. User recommendations never silently modify upstream skill. Installation at
`~/.agents/skills/engineering/` is atomic, preserves overlays and one known-good
rollback, never rewrites itself, and never copies project evidence. No LangGraph runtime is added without a
demonstrated native-task gap.

Default handoff is compact:

```text
Outcome: one sentence.
Now: the immediate action or decision.
Next: the smallest sensible follow-up.
Blocked: only when genuinely blocked.
```

Put receipts, readiness, impact, and technical caveats under optional Details.
