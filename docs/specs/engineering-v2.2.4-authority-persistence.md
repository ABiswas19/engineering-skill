# Engineering v2.2.4 Scoped Authority Persistence

## Decision ledger

| ID | Approved requirement | Design decision | Verification |
| --- | --- | --- | --- |
| AUTH-01 | Approval presence and approval re-request are different facts. | Resolution returns `business_authority_present` and `request_business_approval` separately. | Positive resolution test and missing-authority negative test. |
| AUTH-02 | Exact authority persists across unchanged turns, retries, callbacks, and bounded repair epochs. | Persist a controller-signed project-local authority record; transient turn and retry identifiers are not part of its binding. | Resolve the same binding with different continuation metadata. |
| AUTH-03 | Authority is exact and minimal. | Bind repository lineage, authority epoch, target, action class, normalized scope, and safeguards; delegated authority may only narrow scope and expiry. | Changed-field and widening-delegation tests. |
| AUTH-04 | Revoked, consumed, or expired authority cannot authorize work. | Terminal lifecycle transitions are signed, serialized by the shared repository lock, irreversible, and replay-idempotent; expiry is evaluated from the signed deadline. | Revocation, consumption, expiry, and concurrent conflicting-transition tests. |
| AUTH-05 | Changed project, target, action class, scope, safeguards, or epoch requires new authority. | Resolution requires exact binding equality and reports the changed binding class without copying request prose. | Table-driven mismatch tests, including another repository lineage. |
| AUTH-06 | Full Access and sandbox state are technical permissions, never business authority. | Native permission mode is reported but never used to create or match business authority. | Full Access without an authority record remains blocked for business approval. |
| AUTH-07 | Native destructive, connector, credential, and system approval prompts remain mandatory. | Native requirements are signed into the host approval and authority; matching action classes impose their requirement even if a caller omits it. Resolution returns `pending_native_approval` and never claims the prompt was satisfied. | Omitted destructive requirement and explicit connector/destructive tests. |
| AUTH-08 | Propagation preserves provenance and cannot broaden authority. | Child records retain a parent ID and approval reference, inherit repository/epoch/target/action/safeguards, and accept only subset scope and no-later expiry. | Delegation success and broadening rejection tests. |
| AUTH-09 | Exact-artifact acceptance history is distinct from task completion and authority. | Signed append-only audit events bind authority ID, artifact SHA-256, auditor reference, verdict, and timestamp; the authority-artifact-auditor tuple has one immutable observation, and conflicting replay fails closed. | Accepted/rejected event, replay, changed-time conflict, and ledger-bound tests. |
| AUTH-10 | Codex and Claude remain portable peers with native capabilities intact. | The canonical skill states the same authority contract for both hosts and installation continues to generate thin loaders over one canonical bundle. No tool, permission, context, autonomy, or concurrency restriction is added. | Repository parity and policy contract tests. |
| AUTH-11 | Worker retry exhaustion is not a new approval request. | Policy requires `PAUSED_AWAITING_CENTRAL_ADJUDICATION`; a new bounded epoch may reuse authority only when the exact binding and authority epoch remain unchanged. | Policy contract test plus unchanged-binding resolution test. |
| AUTH-12 | An owner may remove a repository-specific vulnerability-intake requirement for one release without representing the omitted capability as verified security coverage. | The audience policy records `not_required`, an exact owner-authority reference, and explicit residual risk; ordinary Issues remain prohibited for vulnerability or private-production evidence, while audiences with verified private reporting remain unchanged. | Policy-schema, overlay, exporter, negative Issue-intake, audience-isolation, and paired-release tests. |

## Storage and trust boundary

Authority state is owner-private and project-local beneath the Git common
Engineering controller directory. It is excluded from Git and shared by linked
worktrees on the same machine. Each record and audit event is authenticated by
the existing project-controller HMAC key. This provides local tamper evidence;
it does not prove a human identity or replace a native host approval.

### Superseded trust transport (historical only)

The original v2.2.4 design described a trusted-host SSH signer whose public
material was carried in a committed `.engineering-host-approvers` file and
read at `HEAD`. That transport is preserved here only to explain historical
records. It is superseded and is not a current trust or release mechanism:
neither a candidate tree nor a default branch may select the signer material
that admits a new approval, exception, equivalence review, or audit.

### Current v2.2.6 host-owned trust transport

The native host retains the approval record, trust descriptor, and
allowed-signers material outside candidate Git at its private Engineering
boundary. Engineering only reads and verifies exact host receipts from that
boundary; it exposes no approval-minting or signer-management API. Missing,
untrusted, changed, or invalid receipt, signer, repository, epoch, or contract
facts fail closed. The boundary records a typed unknown identity unless the
native host can prove a stronger identity.
The controller never infers authority from prose, Full Access,
sandbox mode, a passing test, task completion, or an audit verdict.

## Resolution flow

1. Normalize the requested repository lineage, epoch, target, action class,
   scope, safeguards, native requirements, and optional continuation metadata.
2. Load and authenticate the retained authority ledger.
3. Return `request_required` when authority is missing, mismatched, revoked,
   consumed, or expired.
4. Return `pending_native_approval` when exact business authority is present
   but a native destructive, connector, credential, or system prompt remains.
5. Return `authorized` only when exact business authority is present and no
   separate native prompt is declared.

Resolution is read-only. Consumption and revocation are explicit lifecycle
operations. Audit acceptance never consumes, revokes, or expands authority.

## Frozen artifact identity

Independent acceptance binds one clean commit with
`engineering.frozen-artifact.v1`. Let `HEAD` be the lowercase commit ID and let
`TREE` be the exact stdout lines from `git ls-tree -r --full-tree HEAD`, decoded
as text without altering fields. The SHA-256 input is UTF-8 without BOM:

```text
engineering.frozen-artifact.v1\n
commit=<HEAD>\n
<TREE lines joined by \n>\n
```

The reported identity is `sha256:` followed by the lowercase hexadecimal
SHA-256. The worktree must be clean and the commit and tree IDs must be reported
with the digest; any edit or commit requires a new digest and fresh auditors.

## Provenance investigation retained for release review

The v2.2.3 installation receipt's source digest is a digest of checkout bytes,
not canonical Git blob bytes. Equivalent source checkouts with different line
ending normalization therefore reproduce different source digests even when a
line-ending-insensitive comparison finds no semantic source difference. This
is an installation-provenance limitation to investigate separately; v2.2.4
does not silently reinterpret it as proof of either valid or invalid origin.

## Deferred and excluded

- External identity-provider proof and cross-machine authority sharing are
  deferred; local HMAC state cannot establish either.
- Installation-receipt digest canonicalization is deferred to a separately
  scoped installation-provenance change.
- No connector, network, publication, merge, deployment, installation,
  settings, PATH, credential, live-data, or populated-data action is included.

## Audience-specific security release decision

The release policy distinguishes `verified`, `unknown`, and owner-authorized
`not_required`. `not_required` is an explicit task-scoped release decision, not
a verified route and not security coverage. It requires an exact owner-authority
reference and a retained residual-risk statement. A repository using that state
must prohibit vulnerability and security-sensitive or private-production
evidence in ordinary Issues and must not invent a mailbox, contact, URL, or
redirect. A paired audience with verified private reporting remains independently
required and is verified against its own security overlay.
