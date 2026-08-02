---
name: engineering
description: Use when a non-trivial software task needs setup, planning, implementation, debugging, review, verification, impact assessment, completion, or engineering maintenance.
---

# Engineering

## What Engineering does

Engineering keeps a software change understandable and verifiable from the
request through completion. It adapts to the project already present: it
discovers the existing instructions, decisions, contracts, tools, and tests
instead of replacing them with a preferred stack.

For substantial engineering work, Engineering prepares the work automatically,
then completes the evidence and checks automatically after the authorized work
is done. A user does not need to run preparation or completion commands in the
normal flow.

Engineering is for new-project setup, mid-flight reconstruction, planning,
implementation, debugging, review, verification, impact, and maintenance. It
does not run for conversation, translation, sentence formatting, or other work
with no engineering impact.

For an explanation request, use plain language and cover what changes
automatically, the three autonomy levels, the evidence retained, and the
safeguards that still require approval. Do not expose prompt jargon or
project-specific private data.

## Local-first operation

Engineering is local-first and suited to one developer. Graphify normally
provides the base graph; approved deterministic-only work may proceed when
exact context and impact evidence is sufficient. The deterministic Engineering
overlay records the verified links, decisions, and checks that make a change
reviewable.

Each developer recreates or reuses their own local checkpoints. Same-machine
worktrees share the Git-common checkpoint; separate machines do not. This lets a
branch reuse the same local evidence without copying a graph into every
worktree. Git and CI coordinate shared drift through the repository; they do
not combine everyone into one live graph.

Enterprise sharing is a future inactive explicit opt-in. Version 2 makes no
enterprise-graph network calls and never switches to enterprise mode
automatically. This does not prohibit approved bounded Git fetches or other
project-native network operations.

Performance stays understandable: a cold start builds the needed local picture;
an incremental run updates only affected material; a cache hit reuses an exact,
already-verified checkpoint.

## What happens automatically

Before applicable work, Engineering identifies the project and authorized
scope; reads applicable instructions; discovers the existing toolchain; checks
relevant decisions and contracts; estimates change impact; selects validation;
and reports whether the work is ready, ready with advisories, or blocked.
For every accepted non-trivial engineering mutation, call the automatic
preparation controller before editing and continue only when its result permits
the authorized work. Trivial conversation, formatting, translation, and file
inspection deterministically skip the controller. `engineering prepare` is a
diagnostic and CI surface, not a manual prerequisite for normal work.
Unavailable or invalid Graphify query evidence blocks preparation unless the
exact task contract explicitly approves deterministic-only operation. That
waiver does not replace sufficient exact context or impact evidence; a
successful empty query is not a failure but still requires that evidence.

After applicable work, it compares predicted and actual changes, runs or
records the required checks, refreshes direct traceability, queues unrelated
maintenance, and records concise evidence. That evidence supports review; it is
not automatic approval.
Engineering completion runs automatically before claiming non-trivial work is
ready. `engineering complete` remains available only for diagnostics and CI;
normal users do not invoke it manually.

Engineering selects only the module the request needs: explain or query,
design or plan, implementation, debugging, review, completion and learning, or
maintenance. It does not load every workflow for every request.

## How applicable work is reported

For a non-trivial request, respond with all four headings below, in order, even
when the work is blocked:

```text
Engineering preparation: project, authorized scope, instructions, and native toolchain; unavailable evidence is unknown.
Readiness: ready, ready with advisories, or blocked; name the smallest missing authority or evidence.
Impact: affected contracts, artifacts, callers, and tests; say impact is unverified if they cannot be inspected.
Engineering completion: completed checks and evidence, or the checks required after authorization.
```

Do not invent a stack or contract, or present an unverified assumption as fact.

For a new project, discover the existing toolchain before proposing an endpoint,
framework, or stack. Setup proposes the v2 manifest and governed evidence set;
tracked artifacts and hooks are written only after approval. In a mid-flight
project, setup adopts the legacy controls when valid and does not create
duplicates. For a changed contract, inspect the current contract and affected
callers before describing a compatible change.

### Project setup

`engineering setup <project>` is always a non-mutating preview first. It shows
the exact governed controls, the managed Engineering blocks for `AGENTS.md` and
`CLAUDE.md`, the required `/graphify-out/` ignore, preserved hook installation,
and a digest for that complete bundle. The managed blocks establish the same
project-local auto-invocation contract for Codex and Claude while preserving all
unrelated instructions. Existing custom ignores and hooks are preserved.

Applying the preview requires a separate project-controls approval bound to the
displayed project-plan digest. Use `engineering approve-setup <project>` with
the displayed digest and explicit `--scope project_controls`; passing a digest
back to `setup` is never authority. If pinned Graphify is missing, the preview
also shows the exact selected external Python interpreter identity, no-shell
`<python> -m pip install git+...@<commit>` argv, reason, and a second digest. A
separate Graphify-install approval is required through the same
`approve-setup` operation with `--scope graphify_install` and that digest. When
both are required, one HMAC-authenticated, one-use attestation must contain both
scopes before any write. It binds immutable Git lineage, the complete project
plan, the exact interpreter bytes/version/path, and the pinned installer argv.
`setup` replans immediately before every mutation, consumes the attestation
once, and rejects stale, altered, partial, replayed, or caller-invented claims.
Ordinary preparation or completion cannot assert either approval or expand the
previewed bundle.

Hooks are installed only at the canonical `<git-common-dir>/hooks` boundary.
External or relative `core.hooksPath`, linked/reparse destinations, forged
markers, changed bytes, wrong modes, or a different dispatcher fail closed.
Existing custom hooks are preserved only through the exact approved migration
plan. Both the legacy `engineering-preserved` migration source and managed
`engineering-traceability-preserved` execution source have recursively bounded
paths, bytes, digests, modes, and file types in the preview. The installer
validates that exact approved snapshot at its inner mutation seam and derives
all migrated output solely from its approved bytes; it never rereads migration
content after approval. Each target's exact preimage is checked inside the
final replace operation immediately before publication. Drift either writes
nothing or preserves only the approved bytes. A managed
inventory makes later executed-hook change, removal, or addition require a
fresh attested setup. Linked/reparse preserved hooks are rejected before their
content is read. Setup likewise validates the unresolved project boundary and
file type of instructions, ignore, manifest, ledger, and link targets before
reading them. Each changed project document carries an approved exact pre-state
and is compared again during staging and immediately before transactional
replacement, so a concurrent edit is preserved rather than overwritten. The
legacy `bootstrap`, `reconstruct`, and `install-hooks` commands are read-only
setup forwarders; they cannot bypass the attested setup path.

Graphify installation is an authorized external prerequisite, not an
uninstallable project transaction. A failed install writes no project setup,
baseline, or hooks and reports `graphify_install_failed`. An installer success
that cannot be verified through that same interpreter reports
`external_change_unverified` and still writes no project setup. If the pinned
installation verifies but later project publication fails, Engineering restores
project files and hooks exactly, retains the verified pinned Graphify
installation, and reports `graphify_installed_project_setup_failed` with
recovery guidance. Re-running an already applied setup is a no-op.

## Autonomy

The project can use one of three levels. `Collaborative` is the normal default.

| Level | Behaviour |
|---|---|
| Guided | Explain and recommend; ask before editing project artifacts. |
| Collaborative | Reconcile routine, in-scope drift; queue unrelated safe maintenance. |
| Steward | Also processes safe queued maintenance when Engineering runs. |

Autonomy reduces routine supervision, not human authority. A task-local
override does not change the saved level. The practical difference between
Collaborative and Steward is timing: Collaborative leaves unrelated safe work
queued until it becomes relevant or a person runs maintenance once; Steward
processes that safe queue during the next foreground Engineering run. Steward
does not run in the background and has no scheduler or service.

Changing the saved level records one bounded, generic autonomy-history event
with the previous and new levels. Repeating the same command does not duplicate
that event, and no request text is copied into project history. Unrelated
project history is never truncated during this update. The controller keeps
existing legacy autonomy entries in the dedicated autonomy history without
changing unrelated history.

## What always needs approval

Every autonomy level requires explicit approval for publication, merge,
deployment, release, production change, destructive or irreversible action,
security/privacy/compliance/credential/financial decisions, public or persisted
contract changes, material architecture or dependency changes, ambiguous intent
or conflicting authoritative sources, and promotion to a shared skill.

## Maintenance

Engineering records unrelated stale items in a project-local queue. Use
`engineering maintain status <root>` to inspect it, `engineering maintain
<root>` to process safe queued work once, or `engineering maintain <root>
--area <stable-area>` to limit the work.
`engineering maintain` means one foreground pass: it deduplicates and ages the
backlog, processes only repairs that can be verified mechanically, and leaves
ambiguous, consequential, or failed repairs visible for review. It does not run
continuously, does not change the saved autonomy level, and does not bypass
approvals.

Automatic completion, graph-hook outcomes, and legacy-output reconciliation
feed that same queue in one bounded batch while holding the repository lock.
Completion exposes only opaque maintenance IDs. Invalid state, non-project
paths, URI/query/control text, credential-shaped values, and inconsistent or
future timestamps fail closed rather than being treated as an empty queue.
Replay never re-adds an item already consumed. A new completion publishes its
maintenance batch and manifest as one rollback-safe operation, and a verified
exact checkpoint causally closes only a checkpoint-stale item from the same
opaque branch lineage whose recorded commit is an ancestor of that checkpoint.
An item from another opaque branch lineage, or one with missing or unverifiable
lineage, stays queued. Repository paths and branch names are never stored in the
target.

## Reusable learning and distribution

A reusable learning candidate is raised only from a terminal, verified
completion, and the default is silence. At most one candidate is shown with a
generic title, applicable modules, and `keep`, `inspect`, or `dismiss`. It
remains project-local and quarantined while proposed or evaluating. Normalized
duplicates are not resurfaced. Promotion requires successful evidence from a
distinct second project, a validated declarative practice, sanitization, and
one explicit `Promote and apply <candidate-id>` confirmation. Promote means
apply: the candidate and owner-local applied-practice ledger advance together,
with no second application confirmation. The controller retains and verifies
those evidence and approval transitions; caller-supplied claims cannot promote
a candidate. Immutable Git root lineage
is shared by a repository's clones and linked worktrees and is unchanged by
remote edits; an independent root is a different project. HMAC-authenticated
local integrity protects controller attestations; "signed" does not mean a
remote identity or public-key signature. These attestations, not editable
completion manifests or queue arithmetic, authorize completion and promotion.
Project-local and controller lifecycle projections advance together. Applied
guidance affects only later relevant Engineering invocations, which report the
practice and why it applied. `learning-status` lists active candidates;
`learning-inspect` shows bounded guidance; and an exact confirmed
`learning-disable` makes a practice inactive without deleting its evidence.
Malformed, tampered, oversized, or version-incompatible practice state injects
nothing and is reported blocked. The installed base skill never rewrites itself.
A promoted practice may create only a reviewable source-improvement proposal;
normal design, implementation, review, release, and installation remain
required. One project's success never becomes an automatic enterprise default.

Project checks are executable capabilities, so discovery alone never authorizes
them. `engineering approve-checks <project>` shows the exact commands and records
a machine-local durable attestation over the project lineage and exact normalized
argv digest; it does not execute the checks, and ordinary source edits preserve that
approval, while a command or lineage change invalidates it. Inline interpreter
code requires the separate `--allow-inline-code` flag. That flag approves only
the displayed argv: it does not expand scope, bypass project safeguards, or
authorize external effects. The attestation binds the `allow_inline_code`
boolean; a false value never authorizes inline argv.
An older valid attestation without that field is treated only as false for an
otherwise exact non-inline command; it is never rewritten or accepted for inline
code.

This is approval of one exact command invocation, not approval of future source
behaviour and not a sandbox. Because source edits retain command approval, the
approved command's later code may exercise its remaining process permissions.
The credential-reduced environment retains only `APPDATA`, `COMSPEC`, `HOME`,
`LANG`, `LC_ALL`, `LOCALAPPDATA`, `PATH`, `PATHEXT`, `SYSTEMROOT`, `TEMP`, `TMP`,
`USERPROFILE`, `VIRTUAL_ENV`, and `WINDIR`; every other inherited environment
variable is removed. Shell execution stays disabled. Any connector, network,
publication, production, or other external effects still need separate approval
under the project's normal safeguards.

Only `promoted_applied` declarative material influences later local work;
legacy `promoted` records remain history and cannot become guidance without a
valid practice and fresh approval. The canonical installation is
in the current user's home (the resolved `ENGINEERING_USER_HOME`, or the normal
home when unset) at `~/.agents/skills/engineering/`; Codex reads that skill
directly and the named Claude loader at `~/.claude/skills/engineering/SKILL.md`
forwards to the same file. The `engineering-traceability` compatibility shim
forwards to that same canonical skill. The compatibility shim remains until
registered projects and callers no longer use the former skill name; removing it
is a separately reviewed compatibility change. Installation is atomic, records
the exact source commit and Graphify
pin, checks Codex and Claude parity, and retains one known-good rollback. It
publishes the bundle, loaders, receipts, and known-good rollback as one
rollback-safe transaction. It does not copy project evidence, paths,
credentials, or populated graphs.

The controller's HMAC-authenticated local integrity detects accidental or
caller-originated edits inside this owner-private machine trust boundary. It is
not public-key signing or nonrepudiation and does not prove a signed-in human
identity; hostile or shared multi-user storage and UNC storage are unsupported
and fail closed; they require a different handle-anchored security design.

`<engineering-home>` means the resolved `ENGINEERING_USER_HOME` when set,
otherwise the operating-system home. Code and rollback bundles live at
`<engineering-home>/.agents/skills/engineering/` and
`<engineering-home>/.agents/skills/.engineering.previous/`; the compatibility
shim is `<engineering-home>/.agents/skills/engineering-traceability/`, and the
Claude loader is `<engineering-home>/.claude/skills/engineering/SKILL.md`.
Machine-wide queue state is
`<engineering-home>/.agents/engineering/contribution-queue.json`; its controller
uses `<engineering-home>/.agents/engineering/controller/contribution-index.json`,
`<engineering-home>/.agents/engineering/controller/attestations.json`, and
`<engineering-home>/.agents/engineering/controller/attestation.key`. Installation
receipts are `<engineering-home>/.agents/engineering/install-receipt.json` and
`<engineering-home>/.agents/engineering/previous-install-receipt.json`. Per-project
attestations and keys remain under
`<git-common-dir>/engineering-graphs/controller/attestations.json` and
`<git-common-dir>/engineering-graphs/controller/attestation.key`.

## Read the technical contract when needed

Technical readers should use
[the controller contract](references/controller-contract.md) for routing,
preparation, readiness, completion, evidence, and safety details.

## Example

For a request to change an existing authentication contract, Engineering first
checks the current contract, affected callers and tests, required approval, and
the project-native validation. It then makes only the authorized change and
reports the evidence and any remaining decision.
