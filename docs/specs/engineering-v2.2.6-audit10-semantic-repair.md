# Engineering v2.2.6 audit10 semantic repair

## 1. External owner-source semantics

The authoritative bootstrap ledger is host-owned and signed outside candidate
Git. It contains a source projection supplied by the owner/root authority, not
one generated from the candidate registry. Each source requirement binds a
stable source requirement ID, `OWNER_APPROVED` lifecycle state, an exact source
excerpt and statement digest, and the candidate requirement and obligation IDs
that implement it. Verification resolves the immutable source bytes, requires
the excerpt exactly once, verifies its digest, and compares the complete signed
projection with the candidate registry. A source row may cover only the exact
generic classes semantically supported by its authenticated excerpt. Every
other complete-ledger row remains explicitly `pending` with a reason; pending
is retained truth, never promoted owner approval. Missing, conflicting,
unclassified, extra, or candidate-generated source semantics fail closed.
Engineering validates the record but cannot mint it.

The host record uses `engineering.v2.2.6-owner-approved-ledger.v2` with exactly
six top-level fields: `schema`, `source_requirements`, `pending_requirements`,
`pending_obligations`, `requirements`, and `obligations`. `requirements`
contains the complete normalized candidate rows,
including their design, contract, runtime, negative-test, and native-evidence
fields; changing any one of those fields under an unchanged host ledger fails
closed. Every source requirement has exactly:

```json
{
  "source_requirement_id": "<stable owner-source id>",
  "lifecycle_state": "OWNER_APPROVED",
  "source_excerpt": "<exact UTF-8 excerpt occurring once in the host source>",
  "statement_digest": "sha256:<digest of exact excerpt bytes>",
  "requirement_ids": ["<candidate requirement id>"],
  "obligation_ids": ["<generic obligation id>"]
}
```

Across the signed supported and pending rows together, every candidate
requirement and obligation ID occurs exactly once, and no ID occurs in both
states. The supported validator requires both exact candidate roots, the
host ledger, and the host owner source; it only returns the canonical ledger
after both candidate registries and the exact source bytes reconcile:

```text
python tools/v226_owner_baseline.py ledger \
  --internal-root <exact-internal-root> \
  --public-root <exact-public-root> \
  --owner-ledger <absolute-host-ledger-path> \
  --source <absolute-owner-source-path>
```

The command cannot create or replace the host ledger, source, trust anchor,
signer material, approval, installation, or activation.

### Native decision-source receipts

When approval is recorded in a native Codex session rather than an automation
prompt, the signed source evidence uses
`engineering.owner-approved-bootstrap-source.v2` with kind
`codex_native_decision_receipt`. Its owner-private source is a canonical
`engineering.owner-approved-native-decision-source.v2` receipt outside
candidate Git. The receipt binds the immutable native JSONL file by absolute
path, byte length, and SHA-256 digest; it separately binds the proposal and
approval message IDs, turn IDs, UTC timestamps, one-based line numbers,
raw-line digests, roles, exact excerpts, excerpt digests, and half-open UTF-8
byte spans within the native message text.

```json
{
  "schema": "engineering.owner-approved-native-decision-source.v1",
  "decision_id": "<stable-host-decision-id>",
  "lifecycle_state": "OWNER_APPROVED",
  "native_source": {
    "schema": "engineering.native-codex-session-jsonl.v1",
    "kind": "codex_session_jsonl",
    "path": "<absolute-owner-private-path>",
    "digest": "sha256:<exact-file-digest>",
    "length": 1
  },
  "proposal": {
    "line_number": 1,
    "message_id": "<native-message-id>",
    "turn_id": "<native-turn-id>",
    "timestamp": "<UTC-instant>",
    "role": "assistant",
    "excerpt": "<exact-proposal-excerpt>",
    "excerpt_digest": "sha256:<exact-excerpt-digest>",
    "excerpt_utf8_span": {"start": 0, "end": 1},
    "raw_line_digest": "sha256:<JSONL-line-digest-without-terminator>"
  },
  "approval": {
    "line_number": 2,
    "message_id": "<native-message-id>",
    "turn_id": "<native-turn-id>",
    "timestamp": "<UTC-instant>",
    "role": "user",
    "excerpt": "<exact-approval-excerpt>",
    "excerpt_digest": "sha256:<exact-excerpt-digest>",
    "excerpt_utf8_span": {"start": 0, "end": 1},
    "raw_line_digest": "sha256:<JSONL-line-digest-without-terminator>"
  },
  "safeguards": [
    {
      "source_requirement_id": "<stable-id>",
      "lifecycle_state": "OWNER_APPROVED",
      "source_excerpt": "<exact-proposal-safeguard-excerpt>",
      "statement_digest": "sha256:<exact-excerpt-digest>",
      "requirement_ids": ["<candidate-requirement-id>"],
      "obligation_ids": ["<candidate-obligation-id>"],
      "proposal_excerpt_utf8_span": {"start": 0, "end": 1}
    }
  ]
}
```

The receipt contains exactly nine safeguard mappings for this approval. Each
mapping binds one stable source requirement ID and its exact proposal-text
span to the complete ledger requirement and obligation IDs. The mappings must
equal the ledger projection in order and content, with every candidate ID
covered exactly once. Missing, duplicated, reordered, candidate-controlled,
non-canonical, reparse-relocated, ACL-weak, changed, ill-ordered, or
digest-mismatched source evidence fails closed. The owner-baseline signature
binds the receipt digest and source kind; rendering or validating the receipt
does not mint owner authority.

The stable decision ID is also a semantic join key, not merely metadata. The
proposal must explicitly recommend approval, either naming that exact ID or
binding the complete nine exact safeguard spans; the later owner message must
consist of one unambiguous affirmative approval of the same ID. The validator
may discard only Codex's typed `ambient-ui-state` block and
the `My request` transport heading before comparing the complete owner request
to the signed approval excerpt. A denial, question, unrelated follow-up,
changed decision ID, scope change, or approval excerpt that hides other request
text fails closed even when every byte span and digest is internally
consistent.

Every host-supplied release-matrix input, including the evidence root,
execution envelope, referenced logs and metadata, audit reports, native
decision receipt, and native session, crosses the shared OS-bound host-path
validator before resolution or reading. A symlink, Windows junction, mount
point, or other reparse ancestor therefore cannot redirect trusted evidence.

Root prepares the generic receipt from an owner-private manifest and native
session with:

```text
python tools/v226_owner_baseline.py decision-source \
  --manifest <owner-private-decision-manifest.json> \
  --session <immutable-native-session.jsonl> \
  --owner-ledger <owner-private-v2-ledger.json> \
  --repository <exact-candidate-root>
```

The canonical output is then supplied to `material` with
`--source-kind codex_native_decision_receipt`, `--source-id` equal to the
receipt decision ID, and a version. Only the native owner signer may sign that
material under the `engineering-v226-owner-baseline` namespace. Populated
message content, IDs, paths, hashes, and mappings remain host-private and are
never committed to either repository.

```text
python tools/v226_owner_baseline.py material \
  --internal-root <exact-internal-root> \
  --public-root <exact-public-root> \
  --source <owner-private-native-decision-receipt.json> \
  --source-kind codex_native_decision_receipt \
  --source-id <stable-host-decision-id> \
  --source-version 1 \
  --authority-epoch <fresh-epoch> --baseline-id <fresh-baseline-id> \
  --receipt-id <fresh-receipt-id> --owner-principal <owner-principal> \
  --architect-principal <architect-principal> \
  --implementer-principal <implementer-principal> \
  --writer-principal <writer-principal> \
  --semantic-principal <semantic-auditor-principal> \
  --technical-principal <technical-auditor-principal> \
  --issued-at <UTC-instant> --expires-at <UTC-instant> \
  --replay-nonce <fresh-nonce>
```

Root writes the canonical material bytes exactly, then uses the native owner
key without exposing it to Engineering:

```text
ssh-keygen -Y sign -f <owner-private-signing-key> \
  -n engineering-v226-owner-baseline <canonical-material.json>
python tools/v226_owner_baseline.py approval \
  --material <canonical-material.json> \
  --signature <canonical-material.json.sig>
```

## 2. Native observability truthfulness

The README describes Engineering's native observability before comparisons to
LangGraph or Langfuse. A capability matrix names the owning module, evidence
source, storage or projection, interface, privacy boundary, support state, and
known limitation for every claimed capability. The disclosure states that
Engineering is not a runtime telemetry backend and does not provide a
persistent dashboard or token/cost collection unless an external provider is
separately supplied. Static HTML is only a projection. The skill and plugin do
not acquire owner, merge, install, deployment, or product authority.

## 3. Per-outcome dependent-dispatch completeness

The post-activation import has exactly one mapping for every active owner
outcome. Each mapping binds:

- lifecycle state `DESIGN_MAPPED`;
- design document path and section;
- schema/API path and interface;
- concrete runtime behavior;
- negative-test path and selector;
- required native or served evidence class, interface, and environment; and
- exact design/contract artifact repository, commit, tree, and digest.

The signed import covers the normalized mappings and their digest. The
controller revalidates completeness at dispatch time and blocks a successor release,
frontend, or other dependent lane if any outcome is missing, duplicated,
Unknown, proxy-only, stale, or bound to the wrong artifact. These mappings are
the pre-dispatch design/acceptance contract; they do not claim future runtime
evidence already exists. Populated later outcomes remain host-private and are
bound immediately after v2.2.6 activation.

## Requirement matrix

| Owner requirement | Design section | Contract | Runtime rule | Negative proof | Acceptance proof |
| --- | --- | --- | --- | --- | --- |
| Genuine external owner source | 1 | Host ledger source projection and native decision-source receipt | Verify exact source-kind bytes, proposal/approval records, and signed mappings before registry comparison | Candidate omission/conflict, wrong source kind, altered native record/span, or unresolved receipt rejects | Host-issued record resolves and matches exact registry |
| Truthful native observability | 2 | README disclosure and capability matrix | Documentation gate blocks missing, late, or overstated claims | Missing matrix/negative boundary/order rejects | Repository test proves exact section and claims |
| Per-outcome dispatch completeness | 3 | Post-activation import outcome maps | Revalidate every active outcome before dependent dispatch | IDs/scopes-only, incomplete, Unknown, proxy, wrong artifact reject | Complete signed maps admit idempotently |

## Compatibility and recovery

Historical records remain readable as non-authoritative history but cannot
authorize new dependent dispatch without the current complete mapping contract.
The one-time bootstrap remains governed by installed v2.2.5, recorded owner
approval, and independent exact-artifact audits. Owner source, approvals, and
populated outcomes stay outside candidate Git. Any unavailable host source or
receipt blocks the affected admission without changing installed state.
