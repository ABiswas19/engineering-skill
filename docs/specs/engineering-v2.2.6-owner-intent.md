# Engineering v2.2.6 owner-intent and exact-artifact release gate

## Status and scope

This approved design corrects a release-critical gap: a candidate must not be
able to narrow the owner-approved outcomes that Engineering evaluates. It
extends the existing local deterministic controller; it does not replace host
native task execution, install a workflow engine, create a scheduler, or put
owner intent, customer data, credentials, or runtime evidence in Git.

The scope is limited to owner-intent binding, outcome survival, outcome
acceptance, exact-artifact release tokens, and the commands and tests needed to
enforce them. The prior v2.2.5 orphan-recovery receipt and rollback remain
unchanged. Merge, installation, activation, deployment, credential, connector,
and destructive action remain separately approved native actions.

## Decision ledger and requirement coverage

| Approved requirement | Design location | Verification |
| --- | --- | --- |
| External owner-private intent; Engineering cannot mint approval | Owner-intent binding | forged/candidate-only binding rejection |
| Controller-injected outcome baseline | Outcome-survival v2 | candidate baseline injection and omitted-mapping rejection |
| Owner exceptions and independent replacement equivalence | Outcome-survival v2 | deferred/excluded and replacement negative tests |
| Typed evidence with no lower-class substitution | Outcome acceptance | evidence-class matrix tests |
| Independent exact-artifact audit | Outcome acceptance | role collision and artifact mismatch tests |
| Token gates for merge/install/activation | Release gate | missing/unknown/failed token rejection and positive token test |
| Intent continuity across preparation, completion, replay, and handoff | Execution binding | digest mismatch/replay tests |
| Legacy evidence remains readable but cannot gain a new release token | Compatibility | legacy status and gate-rejection tests |
| v0.6.0 regression and native Codex/Claude positive evidence | Incident scenarios | proxy-only failure and two-harness acceptance tests |

## External owner intent

`engineering.owner-intent.v1` is supplied through an explicit local binding
file and a separately supplied host approval file. Both are validated before
the controller writes a compact signed record under the Git-common private
controller directory. The tracked repository supplies only the pinned allowed
host signer list; the private signing key and the intent body never enter the
candidate tree.

The normalized binding is:

```json
{
  "schema": "engineering.owner-intent.v1",
  "intent_id": "intent-example-01",
  "repository_id": "sha256:<immutable-lineage-digest>",
  "authority_epoch": "epoch-example-01",
  "source_evidence": [{"identity": "source-example-01", "digest": "sha256:<digest>"}],
  "outcomes": [{
    "id": "OUTCOME-NATIVE-GRAPH",
    "criticality": "core",
    "statement_digest": "sha256:<digest>",
    "required_evidence": [{
      "class": "real_outcome",
      "interface": "native_harness",
      "environment": "candidate"
    }]
  }]
}
```

Validation bounds every list, rejects credentials and source bodies, requires
the current immutable repository digest, and canonicalizes identifiers and
digests. The host approval uses the existing pinned SSH signer trust mechanism
but a distinct `engineering-owner-intent` signing namespace and claim schema.
Only that external signature can bind or replace owner intent.

The retained record is keyed by the deterministic binding digest. Binding an
identical approved intent is idempotent. A changed binding creates a new intent
record only after a new external approval. `intent-status` is read-only and
reports `bound` or `owner_intent_unknown` without exposing source bodies.

## Outcome-survival v2 and intent-impact detection

For an intent-impacting change the controller obtains the complete baseline
from the active bound owner intent, never from the candidate handoff. The
scope-handoff schema carries the `owner_intent_id` and digest, but does not
accept caller-provided `baseline_ids`.

Intent impact is determined from the exact checkpoint graph as well as declared
material change class. Any selected context or exact downstream impact reaching
an explicit capability, assurance, or obligation node is intent-impacting. The
controller also treats redesign, replacement,
simplification, capability deletion, and a handoff carrying outcome survival as
intent-impacting. This prevents a candidate from escaping the gate by renaming
the request or omitting a caller flag, while preserving ordinary legacy
requirement links as readable history rather than silently upgrading them.

Each baseline outcome receives exactly one mapping:

- `INCLUDED` retains its required evidence.
- `REPLACED` supplies a replacement identity plus an independent equivalence
  reviewer distinct from architect, implementer, and writer.
- `DEFERRED` and `EXCLUDED` require an externally attested owner exception ID
  bound to the active owner-intent digest.

The controller rejects duplicates, omissions, mismatched intent digest, a
candidate-supplied baseline, self-attested exception, and role collisions. The
normalized v2 mapping digest travels in scope handoff, preparation,
execution-context, completion, replay, and release records.

## Outcome acceptance

`engineering.outcome-acceptance.v1` is an owner-private signed controller
record for one exact terminal completion. It binds:

- terminal completion digest and exact artifact digest;
- owner intent ID and digest;
- survival mapping digest;
- evidence matrix digest;
- independent auditor identity and role identities; and
- one `accepted`, `failed`, or `unknown` state for each core owner outcome.

Evidence entries name an outcome, a bounded evidence identity and digest, an
evidence class, interface, environment, and the actor role that produced it.
Valid classes are ordered: `design`, `proxy`, `unit`, `integration`,
`end_to_end`, `real_outcome`. A requirement is satisfied only by the same
class or a higher class and only when interface and environment match exactly.
The controller additionally requires all declared native harnesses for an
outcome to be represented; evidence from a policy kernel or unit test cannot
satisfy an executable native-harness requirement.

The owner-intent ID, digest, and authority epoch are copied into every
intent-impacting execution context. Its digest covers that projection, so a
handoff, compaction, or resumed worker cannot replace or remove the owner
baseline without producing a different invalid context.

The acceptance input records the architect, implementer, writer, and auditor.
The auditor must be distinct from all three and explicitly attest that the
original owner intent, rather than a candidate-local contract, was compared.
`unknown` is retained as a distinct state and always blocks a release token.

## Exact-artifact release gate

`engineering release-gate <root> <completion-id> --acceptance-id <id>` verifies
the retained terminal completion, its active owner intent, the exact outcome
acceptance record, and every core outcome. It emits one controller-signed
`engineering.release-token.v1` only when every core outcome is accepted at the
required evidence class and all bindings match byte-for-byte.

The token contains only opaque IDs/digests, the exact artifact digest, intent
digest, acceptance digest, issue time, and supported action gates. It does not
authorize an action. `verify-release-token` validates it for one requested
action (`merge`, `install`, or `activation`) and exact artifact. Calls made by
these action workflows must require this verification before their existing
native approval checks; a valid token never substitutes for those approvals.
`install_bundle` requires the exact token/root/artifact pair before any
v2.2.6+ install mutation and calls the `install` verification first. The
retained v2.2.5 two-argument installer path stays readable and rollback safe;
it cannot be retrospectively upgraded into a v2.2.6 release token.

Completion remains `implementation_complete` evidence. Release readiness,
installation, activation, and verified-current outcome remain separate states.

## Compatibility, privacy, and recovery

Existing `engineering.complete.v1`, scope-handoff v1, and delivery-evaluation
records remain readable. They are not rewritten or upgraded. A legacy
capability- or intent-impacting completion lacking an owner-intent binding is
reported as `owner_intent_unknown` and cannot receive a v2.2.6 release token.
Routine non-impacting work remains compatible with the existing handoff
contract.

All mutable owner-intent, acceptance, and release-token records use the shared
Git-common operation lock and atomic JSON publication. Their replay identities
are deterministic; conflicting replays fail closed. A compaction or handoff
must retain the owner-intent digest. A successor carrying a different or
narrowed digest blocks instead of silently continuing.

## Incident regression and positive proof

The mandatory regression models the v0.6.0 failure: the owner baseline requires
an executable native graph, autonomous fan-out/fan-in, no prompt-by-prompt
steering, and separate native dispatch/wake evidence from both Codex and
Claude; the candidate supplies policy-kernel/unit evidence and marks runtime
as excluded. Binding, mapping, acceptance, and release gate must refuse to
produce a token.

The positive synthetic contract requires evidence from both `codex_native` and
`claude_native` at `end_to_end` or `real_outcome` level, with matching native
harness interface/environment and a distinct independent auditor. The owner
intent must separately name capability negotiation, authenticated IPC,
anti-replay, idempotent effects, bounded retry/cycle detection, and distinct
completion states. Hooks, MCP availability, a policy kernel, or a unit test are
not substitutes for those per-harness native runtime facts. The test proves
only controller admission behavior; it does not claim that a real host run
occurred during this Engineering release.
