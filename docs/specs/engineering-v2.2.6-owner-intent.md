# Engineering v2.2.6 owner intent and exact-artifact release gate

## Status and scope

This approved design prevents a candidate from narrowing the owner-approved
outcomes Engineering evaluates. It is a local policy overlay: it preserves
native Codex and Claude execution, permissions, dispatch, callbacks, and
completion semantics. It does not install a workflow engine, create a
scheduler, put owner intent or runtime data in Git, or perform merge,
installation, activation, deployment, credential, connector, or destructive
actions.

The v2.2.5 receipt and rollback are unchanged. The first v2.2.6 delivery is a
one-time bootstrap governed outside the candidate by installed v2.2.5, the
recorded package approval, and independent exact-artifact audits. After
activation, owner-intent admission uses the host-owned external boundary
defined below. It never depends on GitHub branch policy, collaborators, remote
default-branch files, or a personal owner key.

## Decision ledger and requirement coverage

| Approved requirement | Controller rule | Verification |
| --- | --- | --- |
| External owner intent; Engineering cannot mint approval | Host-signed `engineering.host-receipt.v1` binds repository, epoch, contract, claims, and an external host anchor. Engine only validates and retains it. | forged, wrong repository, wrong epoch, wrong contract, and candidate-anchor substitutions reject |
| Controller-injected outcome baseline | Outcome-survival v2 derives every baseline ID from the active imported owner intent. | candidate baseline injection, omissions, and self-exclusion reject |
| Typed evidence and independent audit | Exact artifact acceptance binds required evidence class/interface/environment and a role-distinct audit attestation. | unit/proxy downgrade and role collision reject |
| Exact artifact release token | A release token binds the terminal artifact and, for install, the exact clean source bundle. | A-token/B-bundle and receipt fact mismatches reject |
| Non-circular v2.2.6 bootstrap | Bootstrap uses the external delivery receipt and never invokes post-activation host trust. | missing facts and self-gate invocation reject |
| Post-activation completeness | Host imports all recorded owner-approved outcomes for `accepted_owner_outcomes` and `product_releases` before downstream admission. | pre-import product/owner-outcome dependent work rejects |
| Historical evidence is not upgraded | Legacy records are readable but are `owner_intent_unknown` for new capability-impacting release work. | legacy release-token request rejects |

## External owner intent and host receipts

`engineering.owner-intent.v1` contains only repository lineage, authority
epoch, source-evidence digests, outcome statement digests, and required
evidence classes/interfaces/environments. It never stores populated intent
bodies in Git.

The native host owns the post-activation anchor outside candidate Git. The
anchor is a private descriptor plus allowed-signers bytes at the configured
Engineering user-home boundary. Its public schema is:

```json
{
  "schema": "engineering.host-trust-anchor.v2",
  "anchor_id": "host-anchor-<opaque-id>",
  "format_version": 1,
  "signers_digest": "sha256:<digest>",
  "identity": {"state": "unknown"}
}
```

Every new approval envelope carries a matching host receipt:

```json
{
  "schema": "engineering.host-receipt.v1",
  "receipt_id": "host-receipt-<opaque-id>",
  "repository_id": "sha256:<immutable-lineage-digest>",
  "authority_epoch": "epoch-example-01",
  "contract": "engineering.owner-intent.v1",
  "identity": {"state": "unknown"},
  "trust_anchor": {"schema": "engineering.host-trust-anchor.v2", "...": "..."}
}
```

`identity.state` remains `unknown` unless the native host can prove a stronger
typed identity. An SSH principal is an opaque host/service or declared-role
identifier; it is not a claim that a person was cryptographically identified.
The controller loads the host anchor afresh, verifies private storage and the
signers digest, verifies the receipt fields and signature, and fails closed.
It has no command that writes the anchor or allowed-signers material.

## Outcome survival, acceptance, and release

For intent-impacting work, outcome-survival v2 obtains the complete baseline
from the active host-bound owner intent. Every outcome is `INCLUDED`,
`REPLACED`, `DEFERRED`, or `EXCLUDED`; replacement requires independent
equivalence and deferral/exclusion requires a host-attested owner exception.
Preparation and completion both derive intent impact from declared selection,
authorized/result paths, changed paths, and rename sides, so underselection or
renaming cannot evade the fence.

Exact acceptance retains distinct `accepted`, `failed`, and `unknown` states
for every core outcome. It verifies evidence type, interface, environment,
exact artifact, original owner intent, mapping digest, and independent auditor
role. A lower class never satisfies a higher class. The v0.6.0 regression
therefore cannot convert policy kernel/unit evidence and self-excluded runtime
into a release token; the positive contract requires independently audited
Codex and Claude native end-to-end evidence.

`release-gate` remains an evidence gate, not an action. It emits a
controller-signed token only when all core outcomes are accepted. An
install-capable token and the installer both bind the exact source commit,
source digest, version, staged digest, and accepted artifact. Native approval
remains a separate requirement for merge, install, activation, deployment,
credential, connector, and destructive actions.

## Bootstrap and downstream import

For the first v2.2.6 installation only, the controller first reports
deterministic exact-source and installed-v2.2.5 capability evidence. That
pre-audit report cannot authorize an installation. Only after independent
exact-artifact audits accept the paired artifacts may root write a
host-private record outside candidate Git. The installer accepts only an
equality-bound `engineering.v2.2.6-bootstrap-authorization.v2` reference to
that resolved record. The record binds repository, epoch, both candidate
commits, trees and bundle digests, installed-v2.2.5 receipt, recorded owner
approval, and at least two distinct signed independent audit receipts. Missing,
forged, stale, mismatched, duplicate, or candidate-created evidence fails
closed. It neither uses nor creates the post-activation anchor.

After activation, `intent-bind` and `intent-import` bind the recorded
`OWNER_APPROVED` baseline and prove coverage for both `accepted_owner_outcomes`
and `product_releases`. A read-only dependent-dispatch gate fails closed until
that import is complete. That contract applies to every accepted owner outcome
and every product release; later v0.6.1 and frontend work must consume it when
separately authorized, without this Engineering repair dispatching or changing
them.

## Compatibility, privacy, and recovery

Legacy source and receipts remain readable and are never rewritten. A legacy
capability-impacting completion without a v2 imported owner intent remains
`owner_intent_unknown` and cannot receive a new release token. All new private
records use the shared lock, atomic publication, bounded data, and no source
body. Bootstrap and install transactions retain v2.2.5 rollback on failure;
host-authority unavailability fails closed for new admissions without changing
historical state.
