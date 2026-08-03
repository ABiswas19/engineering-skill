# Engineering Capability Assurance Design

**Status:** Approved direction; independent written-spec review passed;
implementation plan pending.

**Version target:** Engineering 2.2 after the verified 2.1 baseline.

## Outcome

Engineering must tell a developer, team, or enterprise which approved
capabilities exist, where they are deployed, whether their intended interfaces
are reachable, what evidence shows they work, what contradicts that evidence,
and which questions remain unresolved.

Capability Assurance is part of the universal Engineering core. Enterprise
scale changes topology, evidence adapters, role separation, and aggregation;
it does not require a second edition of the skill.

Engineering 2.2 adds the operational evidence overlay, capability-status
reducer, adaptive deployment cells, selective feedback contract, safe reaction
policy, and harness-gap recommendations to the verified 2.1 traceability and
local-controller baseline.

## Decisions

1. One project retains one independently rebuildable, exact-commit Engineering
   graph. Cross-project graphs are not merged into a canonical umbrella graph.
2. The commit-bound graph represents intended and built truth. Time-varying
   operational evidence is stored in a separate local overlay and joined at
   query time.
3. Capability Assurance is enabled for every governed project. Evidence
   adapters are optional; missing adapters produce explicit unknowns.
4. Existing version 2 manifests remain valid. The new setup path reconstructs
   unknown assurance fields without rewriting historical evidence or claiming
   activation.
5. A single persisted `is_live` flag is prohibited. A human-facing live status
   is a derived projection over scoped evidence.
6. Environment topology is a directed deployment graph, not a hard-coded DTAP
   sequence. Status is evaluated for each material deployment cell.
7. Deterministic deployment, configuration, route, telemetry, synthetic-check,
   and incident evidence is collected before human feedback is requested.
8. Human evidence is role-scoped, release-scoped, environment-scoped, sparse,
   and authenticated by the external surface that collected it.
9. A developer may hold several roles, but one role's evidence never silently
   substitutes for another. A developer cannot attest for an end user they do
   not represent.
10. Bugs and incidents are evidence against affected capabilities until the
    fix is deployed, regression evidence passes, affected routes are checked,
    and the configured stability window elapses.
11. Non-green states trigger safe collection, bounded rechecks, deduplication,
    and promotion blocking automatically. Production changes remain separately
    authorized unless a project has an explicit pre-approved safety control.
12. Setup produces a harness-gap recommendation only when it can identify a
    declared assurance obligation, observed missing or contradictory evidence,
    and a project-neutral remediation class. Otherwise it reports **unknown**;
    it never guesses a control from project type or a README example.
13. Deterministic detector packs identify common obligation-and-evidence gaps.
    A non-catalogue recommendation remains an evidence-bound advisory finding,
    not a claim that Engineering can discover every missing control.
14. Engineering owns the per-project capability manifest and topology, evidence
    requirements, assurance reducer, environment and cell status, bounded
    bug/incident mapping adapters, selective feedback contract, and grounded
    harness-gap recommendations.
15. Engineering is not a scheduler, telemetry warehouse, identity provider,
    feedback UI, or cross-project portfolio/admission authority. A surrounding
    harness owns those services and is the only authority that may aggregate a
    fully-live result across projects.
16. An execution-context bundle is controller-produced, redacted, bounded, and
    provenance-labelled. It is the only graph-derived context supplied to a
    governed worker; a runner that cannot enforce that boundary reports it as
    advisory rather than claiming isolation.

## User and data flow

1. **Resolve the project.** Engineering binds one Git root, instructions,
   default branch, current commit, native build tools, and existing graph.
2. **Discover the landscape.** It inspects repository-native release metadata,
   CI/CD, deployment or infrastructure descriptors, environment candidates,
   ownership, observability, incident tracking, issue templates, and existing
   feedback routes.
3. **Ask only consequential unknowns.** Setup asks for the business/system
   boundary, the actual production cells, promotion topology, authoritative
   release identity, role authority, evidence sources, privacy restrictions,
   and action policy only when they cannot be established safely.
4. **Reconstruct capabilities.** Stable capability identities connect intended
   outcomes, requirements, decisions, dependencies, contracts, implementation,
   tests, interfaces, and required evidence.
5. **Collect operational receipts.** Approved adapters contribute bounded,
   source-backed observations without copying raw telemetry, messages, or
   credentials into the graph.
6. **Derive status.** Engineering reduces graph and overlay evidence for one
   capability, release, and deployment cell. Contradictions and stale evidence
   remain visible.
7. **React safely.** It performs permitted read-only rechecks, blocks unsupported
   promotion claims, and produces a concise owner decision only when automatic
   recovery is insufficient.
8. **Request selective feedback.** Relevant people are contacted through an
   existing authenticated surface only after the observation and stability
   conditions are met.
9. **Recommend missing harness controls only when grounded.** A recommendation
   names the declared assurance obligation, observed gap or contradiction,
   project-neutral remediation class, evidence, expected outcome, and smallest
   manual next step. Common gaps use deterministic detector packs; a
   non-catalogue finding is an evidence-bound advisory. Without all of that,
   Engineering reports **unknown**. It does not create suggested
   infrastructure.
10. **Prepare bounded execution context when a worker is used.** The controller
    derives one redacted bundle from the prepared scope and exact-context
    closure. The runner validates it before dispatch and supplies no other
    graph-derived context to that worker.

## Capability and evidence model

Each capability has a stable project-local identity, intended business or user
outcome, criticality, requirements, interfaces, dependencies, acceptance
conditions, and required evidence profile.

The per-project manifest also records the declared deployment topology,
material environment/cell identities, evidence requirements, applicable
bug/incident mapping adapters, selective-feedback contract, and assurance
reducer inputs. It is project-local capability truth, not a telemetry archive,
identity system, or portfolio registry.

Each operational receipt is bound to:

- one capability and material interface;
- one release or immutable artifact/configuration identity;
- one deployment cell;
- an evidence kind and authoritative source;
- observation time, validity window, result, and scope;
- confidence and contradiction state; and
- an actor role when the evidence is human-authored.

A deployment cell may contain environment, region, tenant, cohort, version,
feature flag, or another project-declared partition. Unused dimensions are
absent; they are not populated with placeholder values.

The derived projection reports these independent dimensions:

| Dimension | Meaning |
|---|---|
| Lifecycle | Intended, specified, implemented, released, retired, or unknown |
| Deployment | Absent, partial, present, or unknown for the selected cell |
| Availability | Healthy, degraded, unavailable, or unknown |
| Verification | Passed, failed, stale, scope-mismatched, not run, or unknown |
| Acceptance | Not required, pending, accepted, rejected, or unknown |
| Confidence | Confirmed, strong, weak, conflicting, or unknown |
| Freshness | Current, aging, stale, expired, or unknown |

The friendly summary may say **fully live**, **partially live**, **not live**, or
**unknown** only as a derived view. Fully live requires every project-declared
required cell and interface to satisfy its release, deployment, availability,
verification, acceptance, confidence, and freshness policy.

## Truth and contradiction handling

Engineering keeps four evidence classes distinct:

- **Intended truth:** approved requirements, decisions, contracts, and target
  topology.
- **Built truth:** source, artifact, test, and release evidence.
- **Observed truth:** deployment records, configuration, telemetry, synthetic
  checks, incidents, and bug reports.
- **Human truth:** role-scoped confirmation, rejection, correction, or reported
  problem.

Synthetic checks are scoped observations, not proof of all user experience.
Human feedback is material evidence, not a replacement for telemetry. A human
correction supersedes an incorrect synthesis but does not erase the source
history. When intended and observed truth disagree, the projection remains
conflicting until new evidence resolves the discrepancy.

## Bounded execution context

When Engineering delegates a governed task, the controller produces an
`execution-context` bundle from the prepared authorization envelope and exact
context closure. The bundle contains only a schema version, task and scope
identity, source-commit identity, stable context identifiers, relationship and
provenance labels, bounded redacted assertions where permitted, and a digest.
It contains no raw source bodies, credentials, connector payloads, private
runtime evidence, or unbounded prompt history.

The runner validates the schema, digest, task/scope binding, source commit,
forbidden-context exclusions, and provenance before dispatch. A malformed,
stale, scope-expanded, or digest-mismatched bundle fails closed. The worker
receives the validated bundle rather than the complete graph or unrelated
context. Existing project-specific context systems remain authoritative; this
contract adds no second context store or router.

This contract is an enforced context boundary only when the selected runner
also prevents undeclared graph-derived sources from reaching the worker. A
full-worktree or direct human session that cannot provide that isolation must
label the bundle as advisory. It may use it for relevance, but it must not
claim that irrelevant or forbidden context was technically unavailable.

## Adaptive landscapes and roles

Setup models the topology it finds: one production runtime, development plus
production, DAP, DTAP, progressive delivery, regional deployments, tenant
partitions, version cohorts, or a project-declared combination. Production is
never inferred solely from an environment name.

Topology, roles, and evidence policy are versioned. A landscape change starts
a new validity period and does not rewrite earlier receipts. A release moving
through several cells retains separate status in every cell.

Relevant roles may include developer, release owner, operator, service owner,
business owner, end user, support, risk, or assurance. Projects declare only
roles that materially affect their acceptance and control model.

## Selective human feedback

Human feedback is requested only when all applicable conditions hold:

- the capability is materially user-facing or outcome-significant;
- the exact release and configuration have been stable long enough to observe;
- the configured usage, eligible-user, or time threshold has been reached;
- no unresolved severe incident makes the question misleading;
- the recipient's role is relevant to the evidence gap;
- the same role has not confirmed the same material release and cell; and
- telemetry or deterministic evidence cannot answer the remaining question.

The observation window scales with capability size, impact, usage frequency,
and rollout pattern. Rare or seasonal capabilities use an explicit longer
window rather than being declared healthy because nothing happened.

The project README or status output names the supported feedback route and its
privacy boundary. Collection normally reuses an issue tracker, service portal,
collaboration surface, or product interface. Local command-line confirmation is
sufficient only when the person is legitimately acting in the required role.

## Reaction policy

| State | Automatic response | Human decision |
|---|---|---|
| Unknown or stale | Collect permitted evidence; run bounded safe recheck; preserve last valid receipt | Choose or authorize a missing evidence source when material |
| Intended/deployed mismatch | Mark conflicting; block unsupported promotion; trace the smallest affected boundary | Resolve ambiguous authority or approve corrective work |
| Synthetic failure | Retry within policy; deduplicate; associate existing bug/incident evidence | Choose rollback, hotfix, acceptance, or deferment when consequential |
| Telemetry degraded/unavailable | Mark evidence unavailable; do not present cached green as current | Decide whether monitoring repair or operational intervention is required |
| Severe linked bug | Downgrade affected capability/cell; block live claim; verify fix lineage | Authorize consequential remediation or risk acceptance |
| Negative human evidence | Record role and scope; link the affected capability; seek corroborating evidence | Decide product, process, training, rollback, or requirement response |
| Partial rollout | Preserve per-cell truth and aggregate as partial | Decide expansion, pause, or rollback |

Notifications are deduplicated and batched. The system stays silent when an
automatic bounded recheck restores current green evidence and no decision is
required.

## Harness-gap recommendations

The setup and completion paths compare declared assurance obligations with the
project's actual evidence and controls. They may recommend a control only when
all three conditions hold: a declared obligation, observed missing or
contradictory evidence, and a project-neutral remediation class. A
recommendation contains a plain-language title, those three grounds, evidence
references, affected capabilities or cells, expected benefit, and smallest
manual next step. Otherwise the result is **unknown**, not a generic
recommendation.

Common examples are missing release identity, absent deployment evidence,
unobservable critical routes, no incident-to-capability mapping, no relevant
feedback path, incomplete role authority, missing scheduler, or a need for a
private cross-project roll-up. These examples are illustrative, not a promise
to detect every gap. Deterministic detector packs cover common patterns. The
skill may issue another project-neutral advisory only when the discovered
evidence proves the need.

Recommendations remain advisory. Creating a service, connector, dashboard,
scheduled job, credential, repository, or live-environment change requires the
normal design, security, and authorization path.

## Scale and large-project safeguards

The design must handle production older than the default branch, capabilities
spanning repositories, partial and canary rollouts, regional or tenant drift,
feature flags, mobile/client version cohorts, managed services without a Git
commit, AI model or data drift, rare processes, dependency incidents,
restricted security evidence, monitoring outages, topology changes during an
observation window, and receipt volume too large for an in-memory scan.

Per-project authority remains local. Engineering does not operate a scheduler,
telemetry warehouse, identity provider, feedback UI, or portfolio/admission
service. A surrounding harness may consume bounded, versioned summaries and
explicit cross-project dependency edges; it must not merge project graphs or
become a second source of project capability truth. That surrounding harness is
the only authority that may aggregate a fully-live result across projects.

## Compatibility and migration

- Existing version 2 projects remain readable without editing their manifests.
- First use reconstructs assurance state conservatively and marks absent
  operational evidence unknown.
- Existing exact-commit checkpoints remain immutable.
- Operational overlays, identities, attestations, credentials, telemetry, bug
  content, and human feedback remain local and untracked.
- No connector, scheduler, feedback request, or live action activates during
  migration.
- The current local-first operation remains valid; the wording changes from
  one-developer scope to one-developer usability with multi-role and
  multi-environment support.

## Verification contract

Implementation requires failing tests first for at least:

1. implemented does not imply deployed, reachable, working, or accepted;
2. a passing synthetic check cannot erase a contradictory severe bug;
3. no usage is not equivalent to healthy usage;
4. stale or scope-mismatched evidence cannot produce fully live;
5. production cannot be inferred from its name;
6. one role cannot attest for another without explicit authority;
7. topology drift preserves history and re-evaluates affected cells;
8. partial rollout is not aggregated as fully live;
9. a feature branch graph cannot overwrite canonical operational truth;
10. missing adapters produce unknown rather than green;
11. a harness recommendation requires a declared obligation, observed missing
    or contradictory evidence, and a project-neutral remediation class;
12. common detector packs and non-catalogue advisories do not claim universal
    discovery, and insufficient grounds return unknown;
13. a valid execution-context bundle excludes forbidden and irrelevant
    graph-derived context, raw source bodies, and unbounded prompt history;
14. malformed, stale, scope-expanded, or digest-mismatched execution context
    fails before runner dispatch, while an unisolated runner reports advisory
    context rather than enforcement;
15. bounded summary federation never imports private evidence or merges graphs;
16. reaction and notification policies deduplicate, batch, and preserve human
    authority; and
17. backward-compatibility fixtures, Linux and Windows checks, sensitive-data
    scanning, exact source/public export parity, exact-diff design and build
    review, and non-mutating smoke evidence all pass.

## Scope reconciliation

| Requirement | Disposition | Verification |
|---|---|---|
| Assurance for solo and enterprise projects | Included | Same reducer passes single-cell and multi-cell fixtures |
| Built versus deployed versus working visibility | Included | Independent dimensions and contradiction tests |
| Dynamic DTAP/DAP/production-only landscapes | Included | Topology fixtures and drift history |
| Telemetry, bug, synthetic, and selective human evidence | Included | Adapter contracts and reaction tests |
| Human feedback without a new UI | Included | Existing-surface adapter and role tests |
| Grounded harness recommendations | Included | Obligation, evidence, and remediation-class fixtures; unknown otherwise |
| Bounded execution context | Included | Schema/digest, redaction, exclusion, runner, and advisory-boundary fixtures |
| Cross-project fully-live aggregation | Deferred to a surrounding harness | Bounded-summary export contract only |
| Scheduler, telemetry warehouse, identity, feedback UI, and portfolio/admission services | Excluded from the skill | Reuse/recommendation boundary tests |
| New feedback frontend | Excluded by default | Reuse-first acceptance check |
| Automatic production mutation | Excluded | Authority regression tests |
| Project-specific adapters and populated evidence | Excluded from distribution | Sensitive-data and export gates |

## Implementation boundary

This document authorizes no implementation, installation, connector, scheduler,
feedback request, deployment, or live-project change. After written-spec review,
the next governed step is a separate implementation plan based on the verified
Engineering 2.1 default branch. That plan must define and version the bounded
cross-project summary schema before either the Skill exporter or a surrounding
harness consumes it.
