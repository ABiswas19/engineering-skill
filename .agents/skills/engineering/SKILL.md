---
name: engineering
description: Use when a non-trivial software task needs setup, planning, implementation, debugging, review, verification, impact assessment, completion, or engineering maintenance.
---

# Engineering

## What Engineering does

Engineering makes an engineering change understandable and verifiable from the
request through completion. It adapts to the project that exists: its
instructions, decisions, contracts, toolchain, tests, and approval boundaries.
It applies to setup, mid-flight work, implementation, debugging, review,
verification, impact analysis, and maintenance. Skip it for conversation,
translation, formatting, or simple inspection.

It prepares applicable work and completes its evidence automatically.
Engineering completion runs automatically before claiming non-trivial work is
ready. The controller commands are diagnostics and CI interfaces, not normal
user steps. Use `engineering map`; installation publishes it through a managed
launcher directory (open a new terminal after installation).
See
`references/controller-contract.md` for exact commands and stored receipts.

## Graph and context

Engineering is local-first. Graphify supplies the base graph and the
deterministic Engineering overlay supplies verified links, decisions, and
checks. Before a graph-derived claim, it assesses the repository and the
canonical default-branch checkpoint. Installation alone does not create a
graph.

A managed repository with missing or stale evidence builds the pinned Graphify
graph and overlay together at one exact default-branch commit, then validates
them. Missing or incompatible Graphify is a blocker; Engineering never invents
another generator. An active feature keeps isolated local evidence. A merged,
deleted, orphaned, or corrupt feature record is historical, archived, or
Unknown; it is never silently merged into the canonical graph or deleted.

Same-machine worktrees share the Git-common local checkpoint catalogue.
Separate machines recreate their own evidence. A cold start builds, an
incremental change updates affected material, and an exact cache hit reuses the
validated checkpoint. Enterprise graph sharing is an inactive opt-in, never an
automatic network mode.

Engineering passes a governed worker only a bounded execution-context bundle:
the permitted scope, exact identity, relevant stable IDs, and redacted
assertions. It excludes raw source bodies, credentials, forbidden, and
irrelevant context. If the runner cannot enforce that boundary, the bundle is
advisory rather than falsely isolated.

## Setup and autonomy

For an unmanaged project, ordinary work remains advisory with traceability
Unknown; Engineering recommends the smallest adoption action and writes
nothing. Setup is always a preview first. It may add project controls and
preserve existing instructions and hooks only after explicit setup authority.
Installing or upgrading Graphify is a separate approval. A first eligible
commit establishes the canonical checkpoint; a greenfield project otherwise
waits for that commit.

Autonomy is Guided, Collaborative (default), or Steward. Guided asks before
project changes. Collaborative handles routine in-scope work and queues
unrelated maintenance. Steward can process safe queued work once in a
foreground run. None is a scheduler or permission to make consequential
changes. A one-off maintenance run does not change the saved autonomy level.

## What always needs approval

Approval is still required for setup/project controls, Graphify installation,
dependency or architecture changes, publication, merge, deployment, release,
production or destructive actions, security/privacy/credential/financial
decisions, public or persisted contract changes, and ambiguous authority.
An explicitly authorized task may run only its unchanged, declared, local,
deterministic, shell-free, credential-reduced checks without a second ceremony.
Changed, inline, networked, connector, live, or consequential checks remain
separately gated.

## Completion and maintenance

Capability status is evidence-based: missing, stale, conflicting, or
role-incomplete evidence remains Unknown. A passing test does not erase a
material incident. Completion compares predicted and actual impact, records
required check evidence, and offers at most a bounded reusable learning.

Maintenance is one foreground pass over a local queue. It repairs only what
can be mechanically verified and leaves consequential or ambiguous items for
review. It does not run in the background.

Reusable learning starts project-local and quarantined. It becomes shared only
after evidence from a second project and explicit approval to `Promote and apply`. The
skill is loaded by Codex and Claude; installation never copies
project evidence or changes projects. Its location is
`~/.agents/skills/engineering/`.
Installation is atomic and retains one known-good rollback.
Promote means apply; the installed base skill never rewrites itself.

Default handoff is compact:

```text
Outcome: one sentence.
Now: the immediate action or decision.
Next: the smallest sensible follow-up.
Blocked: only when genuinely blocked.
```

Put receipts, readiness, impact, and technical caveats under optional Details.
