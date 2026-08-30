# Engineering v2.2.6 bootstrap and host-authority repair

## Purpose and recorded incident

This repair retains the approved v2.2.6 owner-intent, outcome-survival, exact
artifact, and independent-audit outcome. It corrects a repeated
`ORCHESTRATION_ROUTING_FAILURE`: an implementation-derived trust mechanism was
incorrectly promoted into GitHub branch-protection, collaborator, and personal
key prerequisites, pausing an already approved delivery path.

Those GitHub controls are neither owner authority nor a release prerequisite in
this design. This repair does not change GitHub settings or access, create or
publish keys, push, merge, install, activate, or modify v2.2.5. It changes
only the generic controller, its synthetic tests, and its documentation.

## Corrected requirement matrix

| Requirement | Design rule | Verification |
| --- | --- | --- |
| First v2.2.6 delivery cannot authorize itself | Before audit, the controller exposes deterministic exact-source and installed-v2.2.5 capability evidence only. After independent audits accept the exact paired artifacts, root records a signed host-private record and supplies an equality-bound `engineering.v2.2.6-bootstrap-authorization.v2` reference. Resolution never calls post-activation trust admission. | A pre-audit handoff cannot install; a post-audit handoff resolves the installed v2.2.5 receipt, root approval, and distinct independent audit receipts while the post-activation trust loader is deliberately unavailable. |
| No GitHub or personal-key gate | Bootstrap validation contains no branch-protection, collaborator, remote-policy, or personal-owner-key requirement. Local Git is used only to derive the copied source bundle identity. | A complete bootstrap authorization has no GitHub-policy or personal-key field; replacing a candidate-local signer file has no effect. |
| Post-activation admissions use host-owned state | The host provisions an owner-private anchor and allowed-signers material outside candidate Git. Controller code only reads and verifies it; it has no command that creates, changes, or promotes that anchor. | Missing, reparse, ACL, digest, repository, epoch, contract, signature, or anchor mismatch fails closed. A restarted controller rereads the retained external state. |
| No unproven human identity claim | The host receipt records `identity: {"state": "unknown"}` unless the native host can prove a stronger typed identity. Cryptographic principals are opaque service or role identifiers, not claims that a human identity was proved. | A receipt that substitutes a candidate-controlled anchor is rejected; status surfaces `unknown` rather than inventing an identity. |
| Recorded approval becomes governing intent only after activation | `intent-bind` retains the exact host-approved binding. `intent-import` must then prove that the recorded `OWNER_APPROVED` baseline is complete for both `accepted_owner_outcomes` and `product_releases`. Dependent dispatch gates remain closed until that import succeeds. | Before import, generic dependent-dispatch admission rejects product-release and owner-outcome work; after a complete host receipt it returns a non-authorizing admission fact. |
| Prior safeguards survive | Exact source/token/receipt reconciliation, actual-artifact intent impact, controller-injected survival baseline, independent auditor roles, equivalence and exception attestations, typed evidence, rollback, sanitization parity, privacy, and separate native approvals remain required. | Existing regressions plus focused new negative tests and complete paired suites. |

## Bootstrap boundary

Before v2.2.6 is installed, a durable root/host `OWNER_APPROVED` package record
is authority evidence, not an Engineering `INTENT_BOUND` receipt. The native
host keeps a private bootstrap-authority boundary outside candidate Git. The
candidate can only read a pre-audit capability report; it cannot create,
replace, or self-sign the final host record.

The pre-audit report binds only the exact v2.2.6 source bundle and the actual
installed v2.2.5 receipt. It is deliberately insufficient to install. Once
two independent exact-artifact audits have accepted a concrete internal/public
pair, root performs the separate post-audit action: it writes a host-private
record that resolves the following evidence before the installer receives a
small reference:

`engineering bootstrap-handoff-status <skill-source> --home
<absolute-host-home>` is the supported read-only handoff for both stages. It
does not accept authority input and has no operation that creates a record,
approves a candidate, installs a bundle, or activates a runtime.

```json
{
  "schema": "engineering.v2.2.6-bootstrap-host-record.v1",
  "record_id": "bootstrap-record-<opaque-id>",
  "repository_id": "sha256:<immutable-lineage-digest>",
  "authority_epoch": "epoch-<opaque-id>",
  "candidate_pair": [
    {
      "role": "internal",
      "source_git_commit": "<40-hex>",
      "source_git_tree": "<40-hex>",
      "source_digest": "sha256:<bundle-digest>",
      "artifact_digest": "sha256:<candidate-artifact>",
      "base_commit": "<40-hex>"
    },
    {"role": "public", "...": "the same exact binding fields"}
  ],
  "candidate_pair_digest": "sha256:<pair-digest>",
  "installed_v225": {
    "receipt_digest": "sha256:<installed-v2.2.5-receipt>",
    "skill_version": "2.2.5",
    "source_git_commit": "<40-hex>",
    "source_digest": "sha256:<installed-bundle-digest>"
  },
  "owner_approval": "signed host receipt bound to repository, epoch, pair, and installed receipt",
  "independent_audits": [
    "signed accepted semantic receipt with its own role, signer, and replay nonce",
    "signed accepted technical receipt with a distinct role, signer, and replay nonce"
  ],
  "identity": {"state": "unknown"}
}
```

The caller's authorization is intentionally smaller and must equal the
resolved host record exactly:

```json
{
  "schema": "engineering.v2.2.6-bootstrap-authorization.v2",
  "record_id": "bootstrap-record-<opaque-id>",
  "record_digest": "sha256:<host-record-digest>",
  "source_bundle": {
    "source_git_commit": "<40-hex>",
    "source_digest": "sha256:<bundle-digest>",
    "skill_version": "2.2.6"
  }
}
```

Resolution recomputes the source commit, tree, digest, version, pair digest,
and ancestry; resolves the actual installed v2.2.5 receipt; and verifies the
host-signed owner and audit claims, roles, signatures, timestamps, and unique
replay nonces. It rejects missing, forged, stale, wrong-repository,
wrong-epoch, wrong-contract, wrong-artifact, duplicate, non-independent, or
changed evidence. The installer then recomputes the copied bundle and staged
tree before it writes its receipt. A token for bundle A and a copy of bundle B
is rejected before publication.

## Post-activation host-owned trust

After activation, the native host—not candidate Git—owns a private authority
directory under the configured Engineering user home. It contains exactly an
`engineering.host-trust-anchor.v2` descriptor and its allowed-signers bytes.
The descriptor carries an anchor ID, format version, allowed-signers digest,
and `identity: {"state": "unknown"}`. It contains no repository policy,
collaborator list, or personal owner key.

Every new owner approval, authority approval, owner exception, equivalence
attestation, independent audit, and host attestation carries an
`engineering.host-receipt.v1`. The receipt binds the caller's repository
lineage digest, authority epoch, required contract, exact external anchor, and
the unknown-or-proven identity state. The host signs the canonical claims plus
that receipt under the operation namespace. The controller validates the
external anchor and receipt on every admission; it never trusts a candidate
copy, default branch, remote URL, or candidate-selected signer list.

Legacy v1 remote-anchor records remain readable history. They are not an
active v2.2.6 host boundary and cannot yield a new owner-intent release token.

## Activation import and downstream fence

Immediately after activation, the native host must perform `intent-bind` and
`intent-import`. The import is host-signed and names the retained binding's
repository, epoch, digest, all outcome IDs, and both required coverage scopes:
`accepted_owner_outcomes` and `product_releases`. The controller stores this
compact private receipt separately from the owner-intent ledger.

`dependent-dispatch-status` is a read-only gate. It cannot dispatch anything;
it only fails closed until a complete import exists. The successor release and frontend
lanes must use that generic product-release/accepted-owner-outcome gate after
their separately authorized work begins. This preserves the capability to
enforce the owner decision without changing those lanes now.

## Recovery and compatibility

The v2.2.5 installed receipt and rollback bundle remain untouched. New
bootstrap receipts are retained as `engineering.install.v5` and carry the
equality-bound host-record reference plus the exact source commit, tree, and
digest; legacy `engineering.install.v3` and `engineering.install.v4` receipts
remain readable historical evidence. Every new receipt must reconcile the
actual copied bundle. A failure before publication leaves no new install
surface; transaction rollback retains the known-good prior bundle. A missing
or malformed host authority anchor after activation results in `Unknown` and
blocks only new owner-intent admissions and dependent release work. It does not
rewrite historical evidence or manufacture a replacement authority.

Release-token enforcement applies after the one-time bootstrap has activated
v2.2.6. The bootstrap itself remains governed by installed v2.2.5, the recorded
owner decision, and distinct exact-artifact audits; it does not require or mint
its own future release token.
