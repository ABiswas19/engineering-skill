# Engineering Applied Learning Design

**Status:** Approved; independent design review passed.

**Version target:** Engineering 2.1

## Purpose

Let a proven reusable engineering practice improve the owner's active local
harness without allowing the distributed Engineering skill to modify its own
source. Promotion and local application are one explicit operation.

## Architecture

Engineering has three separate layers:

1. The **base skill** is the stable, distributable Codex and Claude product.
   Ordinary work cannot rewrite its instructions, scripts, hooks, tests, or
   installed bundle.
2. The **applied harness** is owner-local, integrity-protected state under the
   existing Engineering home. It contains only promoted declarative practices.
3. The **source-improvement path** produces a reviewable proposal for the base
   skill. It never edits, commits, publishes, releases, or installs source.

The applied harness extends the existing Engineering-home convention:

```text
<engineering-home>/.agents/engineering/applied-practices.json
```

Codex and Claude resolve the same Engineering home and therefore consume the
same applied practices.

## Candidate contract

An Engineering worker may propose at most one reusable candidate after a
terminal verified completion. The default is silence. A candidate contains:

- one allowed declarative practice kind;
- a concise generic title and instruction;
- a bounded list of applicable Engineering modules;
- a deterministic verification criterion;
- exact completion evidence references; and
- a sanitization declaration.

Allowed practice kinds are generic guidance, test/evaluation pattern,
context-extraction rule, and verification-checklist addition. A candidate may
not contain arbitrary code, commands, hooks, dependencies, contracts, network
behavior, credentials, private names, repository paths, raw source text, or
private URLs.

Normalized candidate digests suppress duplicates. A dismissed candidate is not
raised again unless materially different evidence changes the normalized
practice.

## User lifecycle

After the first verified project, Engineering may show once:

> Possible reusable Engineering learning: `<practice>`. Keep for cross-project
> evaluation, inspect, or dismiss?

Only a terminal verified completion from a distinct immutable Git-root lineage
may evaluate the kept candidate. When that evidence passes, Engineering asks:

> This practice succeeded in two independent projects. Promote and apply it to
> my local Engineering harness?

Approval changes the candidate atomically to `promoted_applied` and adds it to
the applied-harness ledger. There is no separate application confirmation.
Rejection leaves it quarantined and inactive.

Applied practices affect only later relevant Engineering invocations. The
preparation or completion summary names each used practice and its reason. The
owner may inspect, disable, or roll back a practice; immutable evidence remains.

## Promotion transaction

The existing contribution queue, project-local contribution record, controller
attestation, and applied-harness ledger advance together. A partial write rolls
back. Before publication, the controller validates terminal evidence, distinct
second-project evidence, explicit combined approval, allowed declarative type,
sanitization, and the exact candidate digest.

Existing `promoted` records remain valid history. They migrate to
`promoted_applied` only when the same evidence and practice validation passes.
Legacy records with no valid declarative practice cannot influence an
invocation.

The ledger is bounded to 128 active practices and 256 KiB serialized size.
Exceeding either limit fails closed and leaves prior state unchanged.

## Source improvement

A promoted-and-applied practice may produce a bounded source-improvement
proposal containing the generic practice, evidence references, affected skill
contract, and required tests. The proposal is not a patch and grants no source
or publication authority. Normal design, implementation, review, commit,
release, and installation governance remains required.

## Standalone distribution

The canonical repository contains generic skill source, synthetic tests,
human-readable documentation, and canonical-source release controls. A separate
public mirror is regenerated through an allowlisted export and independent Git
history.

Neither repository contains project histories, applied-harness state,
contribution queues, controller keys, attestations, checkpoints, local paths,
private examples, or populated graphs. The export allowlist and source-path
inventory remain only in the canonical repository. The public tree contains
only generic source, synthetic tests, public-safe metadata, CI, and an approved
licence.

Empty repository creation requires verified owner, visibility, authenticated
identity, and destination absence. Source publication additionally requires an
approved licence, complete-tree scan, tests, independent exact-diff review, and
explicit delivery authority.

## Failure and authority boundaries

- Invalid, tampered, oversized, incompatible, or unverifiable state is not
  applied.
- An incompatible practice is disabled with a reason, not rewritten.
- Applied practices never expand task authority or approve merge, release,
  deployment, dependency, security, public-contract, or irreversible changes.
- The contribution queue is local state, not a remote registry.
- No autonomy level can bypass candidate, promotion, publication, or release
  approval.

## Verification

Tests must prove candidate silence, one-time surfacing, duplicate suppression,
private/executable-content rejection, durable keep/dismiss, distinct-project
evaluation, atomic promotion/application, rollback, tamper rejection, bounds,
later-invocation relevance, shared Codex/Claude consumption, base-source byte
identity, legacy migration, and proposal-only source improvement.

Repository acceptance must additionally prove no forbidden project or personal
references, no generated/private state, independent repository histories,
allowlisted public export, public-safe fixtures, full-tree scanning, and
working tests in both repository trees.

## Out of scope

- Self-modifying skill source or installation.
- Arbitrary executable practices.
- Automatic commits, pushes, pull requests, releases, or deployments.
- Enterprise contribution services or cross-user automatic adoption.
- Live project runtime, connector, schedule, or private-store changes.
