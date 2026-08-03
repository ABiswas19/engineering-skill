# Engineering

Engineering is a project-neutral skill for starting, reconstructing, maintaining, and completing software work with traceable requirements, decisions, changes, verification, and exact-commit code graphs.

It works in new and mid-flight Git repositories, supports selectable autonomy levels, and can install its pinned Graphify dependency after explicit inspection and approval. Generated graphs and deterministic controller state live outside project history so linked worktrees share one local checkpoint catalogue without committing private runtime state.

Installing Engineering does not establish a repository graph. Its first use
silently assesses whether the repository is unmanaged, greenfield, or managed,
then inspects Graphify and local checkpoint evidence before making graph-derived
claims. A managed repository with no valid canonical default-branch checkpoint
builds or refreshes one only through the supported pinned Graphify runner; an
unavailable or incompatible runner is an actionable blocker, never a substitute
generator. The Graphify graph and deterministic overlay are published and
validated together at one exact default-branch commit. Feature and scratch
checkpoints remain isolated local evidence: active work stays feature-scoped,
merged work is historical, and stale, orphaned, or corrupt records are excluded
from canonical claims rather than silently merged or deleted.

The skill source is `.agents/skills/engineering`. Read its `SKILL.md` for the human operating model and `references/controller-contract.md` for storage and command details.

## Capability Assurance direction

The approved next design makes Capability Assurance a core Engineering
capability for every project, including software maintained by one developer.
It will distinguish what is intended, implemented, deployed, reachable,
verified, recently observed, contradicted, and accepted. Missing evidence will
remain unknown rather than being presented as green.

The design keeps the exact-commit Engineering graph immutable. Time-varying
deployment, telemetry, incident, synthetic-check, and role-authenticated human
evidence lives in a separate local operational overlay and is joined to the
graph when status is queried. There is no persisted `is_live` boolean.

Capability Assurance is implemented in Engineering 2.2. The independently
reviewed scope, verification boundary, and explicitly deferred surrounding
harness services remain in
[`docs/specs/engineering-capability-assurance-design.md`](docs/specs/engineering-capability-assurance-design.md).

## Bounded execution context direction

For a governed worker task, the approved 2.2 design will have the controller
produce one redacted, digest-validated execution-context bundle from the
authorized scope and exact context closure. It will carry stable provenance but
no raw source bodies, credentials, connector payloads, or unbounded history.
The runner must reject a stale, altered, scope-expanded, or malformed bundle
before dispatch. Existing project context systems remain authoritative; this
adds no second context store or router.

The bundle is an enforced context boundary only when the runner prevents other
graph-derived context from reaching the worker. Where that isolation is not
available, Engineering reports the bundle as advisory rather than pretending it
provided the worker with only the relevant context.

## Surrounding engineering harness

Engineering remains a per-project skill. During setup and reconstruction, the
Capability Assurance design requires it to inspect the project and recommend
missing surrounding controls only when it has all three grounds: a declared
assurance obligation, observed missing or contradictory evidence, and a
project-neutral remediation class. Common gaps use deterministic detector
packs; a non-catalogue recommendation is an evidence-bound advisory. Without
those grounds, Engineering reports **unknown** rather than guessing.

Illustrative examples include:

- exact release and deployment identity;
- environment, region, tenant, cohort, or feature-flag topology;
- telemetry, synthetic-check, incident, and bug adapters;
- an authenticated route for role-relevant human feedback;
- a scheduler for periodic evidence collection;
- a private cross-project status registry or portfolio view; and
- notification and decision-routing controls.

These examples are illustrative, not a fixed catalogue or a promise that the
skill can detect every gap. Engineering may recommend a different
project-neutral control only when discovered evidence grounds it. A
recommendation is diagnostic only: the skill does not install a service, create
a user interface, activate a connector, or change a live environment.

Engineering owns each project's capability manifest and topology, evidence
requirements, assurance reducer, environment/cell status, bounded bug/incident
mapping adapters, selective feedback contract, and grounded recommendations. It
is not a scheduler, telemetry warehouse, identity provider, feedback UI, or
cross-project portfolio/admission authority. A surrounding harness owns those
services and is the only authority that may aggregate a fully-live result across
projects.

## Decisions stay project-owned

Engineering uses one authoritative project decision ledger. A project may
declare its existing ledger with `decision_ledger`; otherwise Engineering uses
its standard project ledger. Graphify and the deterministic overlay only index
that ledger. A material, user-approved architecture, contract, governance,
security, scope, dependency, deployment, or supersession decision must retain
its project-native ID and source-resolvable overlay node. Routine code choices,
tests, progress, and task completion do not create or advance decisions.

## Local map

Run `engineering map` from a Git project to open its current exact-checkpoint
map; use `--no-open` for CI. It renders only the pinned Graphify code AST and
the deterministic/assurance overlays already stored in the local common Git
state. It never calls an LLM, `graphify extract`, a network service, or a
second store. `--budget` on Graphify context queries is a returned-context cap,
not an API-token spend. Exact cache hits only reopen the existing map; a source
change follows the existing incremental Graphify update path.

This restriction applies to graph construction, traversal, and rendering. It
does not restrict the host Codex or Claude agent from reasoning about an
authorized task. When prose is necessary, the host uses the bounded, redacted
execution-context slice; Engineering never turns that into a Graphify backend
or semantic document-ingestion call.

## What remains outside Engineering v2.2

Version 2.2 owns the per-project capability manifest and topology, evidence
obligations, status reducer, deployment-cell assessment, adapter contracts,
selective-feedback contract, execution-context bundle, and evidence-grounded
harness-gap recommendations.

Always-on scheduling and evidence collection, telemetry storage, identity and
role verification, feedback UI or channel, credentials and connectors,
cross-project operational storage or portfolio roll-up, notifications and
decision routing, and cross-project fully-live authority remain outside the
skill. Those surrounding components can provide fresher and more complete
evidence, automate periodic reassessment, support independent post-deployment
verification, and offer cross-project visibility.

They are enhancements, not dependencies: Engineering remains usable without
them and reports **unknown** when the required evidence is absent. During setup
or completion it may recommend one only when a declared assurance obligation
and an observed gap or contradiction support a project-neutral remediation
class. Otherwise it omits the suggestion or reports **unknown**. The examples
above remain illustrative, not a promise to detect arbitrary needs.

Where human feedback is relevant, a project README or generated status output
should identify the supported feedback route, required role, release and
environment scope, privacy boundary, and evidence freshness. The README itself
is guidance, not an authenticated feedback store. Projects should normally
reuse an existing issue tracker, service portal, collaboration surface, or
product interface before building a new frontend.

This repository is available under the Apache License 2.0. Verification does not authorize installation or use in a live project.
