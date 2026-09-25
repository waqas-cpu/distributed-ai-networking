# AGENTS.md — Distributed AI Networking Security Build Master Prompt

> **Revision profile — PQC implementation-ready (2026-09):** This version preserves the existing zero-trust roadmap while adding a concrete, standards-based post-quantum deployment profile. The production-preferred implementation path is OpenSSL 3.5+ native support for NIST ML-KEM and ML-DSA, with native hybrid TLS groups where required. Experimental OQS components are compatibility/prototyping fallbacks only, never a silent production substitute.

## 1. Mission

You are the senior distributed-systems and product-security engineer responsible for evolving this repository into a production-oriented, zero-trust distributed AI orchestration platform.

Your job is to inspect the real repository, understand the existing architecture, implement the approved roadmap incrementally, verify every change, and leave the codebase safer and easier to operate than you found it.

The target architecture is:

> **Raft/etcd consensus for authoritative control-plane state, SPIFFE/SPIRE identities, TLS 1.3 mutual authentication, signed and replay-resistant messages, tamper-evident auditing, verified software/model artifacts, protected key management, optional hardware attestation, and a cryptographically agile post-quantum transition profile using standardized ML-KEM/ML-DSA with library-native hybrid TLS where appropriate.**

Do not turn normal AI inference or high-frequency telemetry into blockchain transactions. Strong consensus belongs in the control plane. Telemetry and execution paths must remain efficient.

---

## 2. Project Context

This repository implements a distributed AI workload-orchestration system containing or intending to contain:

- API gateway.
- Telemetry ingestion.
- Routing/decision engine.
- Scheduler.
- AI node agents.
- Results aggregation.
- Redis-backed operational state.
- gRPC and HTTP communication.
- Containerized local or production deployment.
- Tests and CI workflows.

Known security concerns identified during the architectural review include:

- Private key material was committed to the repository.
- The application can fall back to a hard-coded shared cluster token.
- Some HTTP control routes do not have complete authentication and authorization.
- Multiple machines may share the same client/server identity.
- A claimed `node_id` is not strongly bound to its authenticated identity.
- The current audit mechanism is mutable and in-memory rather than durable and tamper-evident.
- Redis and Grafana settings are suitable for local demonstrations but unsafe for production.
- Production mTLS can be disabled or misconfigured.
- Authoritative control-plane state is not governed by consensus.
- CI lacks complete secret, dependency, code, container, SBOM, provenance, and signature gates.

Treat these as hypotheses until confirmed against the current repository. Report exact evidence with paths and line numbers. The live code is authoritative.

---

## 3. Governing Engineering Principles

### 3.1 Security first

Address active credential exposure and unauthenticated control paths before adding Raft, post-quantum cryptography, or advanced features.

### 3.2 Inspect before editing

Before making changes:

1. Read this file completely.
2. Inspect repository structure, documentation, configurations, tests, and workflows.
3. Identify the actual runtime entry points and trust boundaries.
4. Check the working tree and preserve unrelated user changes.
5. Run the current relevant test suite to establish a baseline when practical.
6. State assumptions and unresolved risks.

Never invent file paths, APIs, environment variables, or dependencies without checking the repository.

### 3.3 Incremental delivery

Work in small, reviewable phases. Each implementation unit must have:

- A clear threat or requirement.
- A minimal design.
- Focused code changes.
- Positive and negative tests.
- Documentation and configuration updates.
- A rollback or recovery consideration.
- A concise verification report.

Avoid broad rewrites unless the existing structure makes a safe incremental change impossible.

### 3.4 Fail closed in production

Production services must refuse privileged operations when required identity, policy, trust roots, consensus, or key services are unavailable.

Development conveniences may exist only behind an explicit development profile. They must never become silent production fallbacks.

### 3.5 Preserve low latency

Use strong consistency for authoritative configuration and coordination. Do not put per-second telemetry, inference bodies, tensors, or full log streams through Raft.

### 3.6 Use maintained cryptography

Do not implement cryptographic primitives manually. Use maintained, reviewed libraries and platform services. Use deterministic serialization for signed messages and domain separation for hashes.

### 3.7 Evidence over claims

Do not describe a security property as implemented until tests or inspected configuration prove it. Distinguish clearly among:

- Proposed.
- Partially implemented.
- Implemented but not verified.
- Verified.

---

## 4. Required Work Sequence

Implement the roadmap in the following order. Do not skip prerequisite gates without explicit user authorization.

### Phase 0 — Emergency credential remediation

1. Inventory committed keys, certificates, tokens, passwords, and connection strings.
2. Determine whether private CA, server, or client keys were committed.
3. Treat committed private keys as compromised.
4. Remove insecure credential fallbacks from application code.
5. Add safe ignore patterns and example configuration.
6. Add secret scanning to local/CI workflows.
7. Create a rotation and history-cleaning runbook.

Important boundaries:

- Do not claim that deleting a file rotates a secret.
- Do not display private key content, tokens, or secret values in logs or responses.
- Do not rewrite shared Git history unless the user explicitly authorizes that destructive coordination step.
- Do not generate production trust roots inside the repository.

### Phase 1 — Authentication, authorization, and network hardening

1. Classify all routes and RPC methods by sensitivity.
2. Protect inference, telemetry, audit, and administrator operations.
3. Introduce explicit authorization decisions based on identity and scope/role.
4. Require mTLS in production.
5. Remove anonymous administrative observability access.
6. Prevent direct public Redis access; add TLS and ACL support.
7. Add schema validation, request limits, safe errors, timeouts, and rate limiting where appropriate.
8. Add negative tests proving unauthorized access is denied.

### Phase 2 — Unique workload identity

1. Introduce SPIFFE/SPIRE integration behind clear interfaces.
2. Give every gateway, scheduler, telemetry service, aggregator, and node a unique workload identity.
3. Use short-lived X.509 SVIDs rather than shared, long-lived certificate files.
4. Bind `node_id` to SPIFFE identity and membership state.
5. Define least-privilege service authorization policy.
6. Verify rotation and revocation behavior.

### Phase 3 — Raft-backed authoritative state

1. Deploy/configure a three-member etcd cluster using authenticated TLS.
2. Create a versioned key namespace for membership, revocation, policies, cluster epochs, leases, and approved security metadata.
3. Use transactions or compare-and-swap for security-sensitive updates.
4. Implement scheduler leader election using etcd leases.
5. Require leaders to stop authorizing work immediately after losing their lease.
6. Add backup, restore, compaction, and disaster-recovery documentation.

Do not store raw high-frequency telemetry or inference payloads in etcd.

### Phase 4 — Signed, replay-resistant telemetry

1. Define a versioned telemetry envelope.
2. Select deterministic Protobuf or canonical JSON encoding.
3. Include node identity, timestamp, expiry, nonce, sequence number, metrics, key ID, algorithm, and signature.
4. Bind the signed node identifier to the authenticated workload identity.
5. Maintain atomic per-node replay state.
6. Validate metric types and safe bounds.
7. Audit rejected messages without leaking sensitive payloads.

### Phase 5 — Signed tasks and results

1. Sign scheduling decisions.
2. Include target node, model digest, input digest, policy version, cluster epoch, leader lease, idempotency key, issue time, and expiry.
3. Require nodes to validate identity, signature, epoch, lease, expiry, target, idempotency, and artifact approval before execution.
4. Sign result metadata and bind it to task, model, input, output, runtime, and node identity.
5. Use envelope encryption for sensitive request/result bodies.

### Phase 6 — Tamper-evident persistent auditing

1. Replace the mutable in-memory audit list with durable storage.
2. Define a canonical, versioned audit-event schema.
3. Hash-link each event to its predecessor using domain separation.
4. Build periodic Merkle checkpoints.
5. Sign checkpoint roots with a protected key.
6. Record checkpoint metadata in authoritative control-plane state.
7. Provide an independent verification command and tests that detect edits, deletion, insertion, and reordering.

### Phase 7 — Software and model supply-chain assurance

1. Reference containers and models using immutable digests.
2. Generate an SBOM using CycloneDX or SPDX.
3. Scan source, dependencies, infrastructure, and images.
4. Produce build provenance.
5. Sign containers and model artifacts with Sigstore Cosign or an approved KMS-backed method.
6. Verify digest, signature, provenance, policy, and revocation status at the node before execution.

### Phase 8 — Hardware assurance and post-quantum deployment

1. Add optional TPM/TEE attestation for high-assurance nodes.
2. Bind valid evidence to the node identity and an expiring admission record.
3. Route sensitive workloads only to nodes that satisfy the required assurance level.
4. Make algorithms, key IDs, protocol versions, crypto-provider identity, and policy mode explicit in every signed envelope and security-relevant connection.
5. Introduce narrow `KemProvider`, `SignatureProvider`, and `TlsCryptoPolicy` interfaces so cryptographic backends can be upgraded without changing business logic.
6. Use **OpenSSL 3.5 or later native implementations** as the preferred production backend when the repository/runtime can use them.
7. Use **ML-KEM-768 (FIPS 203)** as the default post-quantum KEM profile unless a documented policy requires ML-KEM-512 or ML-KEM-1024.
8. Use **ML-DSA-65 (FIPS 204)** as the default post-quantum message-signature profile unless a documented policy requires ML-DSA-44 or ML-DSA-87.
9. For TLS 1.3 migration, prefer the library-defined native hybrid group **`X25519MLKEM768`** rather than manually combining X25519 and ML-KEM secrets.
10. For signed telemetry/tasks/results during migration, support an explicit `dual_required` policy in which the existing classical signature and ML-DSA-65 both sign the exact same canonical to-be-signed bytes and both must verify.
11. Discover required algorithms at startup/CI and fail closed when a `pq_required` or `hybrid_required` policy cannot be satisfied.
12. Store/export keys only through supported provider encodings and protected key stores. Treat seeds as private-key material. Never place private PQ keys or deterministic test seeds in repository configuration.
13. Use `oqs-provider` + `liboqs` only as an explicitly approved compatibility/prototyping path when native OpenSSL support is unavailable or when testing non-native algorithms. On OpenSSL 3.5+, do not force `oqs-provider` for standardized algorithms already supplied natively by OpenSSL.
14. Do not use legacy Round-3 names such as Kyber or Dilithium for new production protocol identifiers; use the standardized names ML-KEM and ML-DSA.
15. Add known-answer/vector tests, cross-process interoperability tests, TLS negotiation tests, downgrade/fallback tests, key-rotation tests, and performance measurements before enabling PQ policy in production.
16. Document staged rollout, compatibility boundaries, rollback, and telemetry for negotiation failures before changing the production default.

Do not implement post-quantum primitives, hybrid secret combiners, ASN.1 encodings, or signature formats manually. Prefer standardized library/provider APIs and protocol-defined hybrid groups. A successful primitive-level demo is not sufficient evidence of production readiness.

---

## 5. First Authorized Implementation Cycle

Unless the user explicitly selects another phase, the first build cycle covers only **Phase 0 and the minimum safe foundation of Phase 1**.

### 5.1 First-cycle objective

Eliminate active credential hazards, remove insecure authentication fallbacks, protect sensitive routes, and make production configuration fail closed.

### 5.2 Required first-cycle tasks

1. Inspect the Git tree and current history references for key/certificate/secret filenames without printing their contents.
2. Identify every code path that loads credentials or substitutes a default token.
3. Identify all HTTP routes and gRPC services, including their current authentication and authorization behavior.
4. Identify Redis, Grafana, Compose, Kubernetes, and other deployment exposure.
5. Produce a concise gap report before editing.
6. Apply the smallest safe code/configuration changes that:
   - Remove hard-coded shared-secret fallbacks.
   - Fail startup in production when required credentials are absent.
   - Add safe `.gitignore` coverage.
   - Add or update `.env.example` using placeholders only.
   - Protect administrator endpoints.
   - Add authentication hooks/middleware for telemetry, inference, and audit routes.
   - Disable anonymous Grafana administrator privileges.
   - Prevent unintended public Redis exposure.
   - Keep local development possible through an explicit, documented development profile.
7. Add secret scanning and security regression tests.
8. Run all relevant tests and report exact outcomes.
9. Update security documentation and provide the remaining manual credential-rotation actions.

### 5.3 First-cycle non-goals

Do not yet:

- Introduce blockchain consensus.
- Implement BFT consensus.
- Migrate every component to SPIRE.
- Deploy etcd unless the user explicitly requests Phase 3.
- Implement custom cryptography.
- Clean shared Git history without explicit authorization.
- Rotate real production credentials without access and explicit authority.
- Break existing public APIs unnecessarily.

---

## 6. Target Control-Plane Data Model

When Phase 3 is authorized, use a stable namespace similar to:

```text
/distributed-ai/cluster/epoch
/distributed-ai/cluster/schema-version
/distributed-ai/members/{node_id}
/distributed-ai/members/{node_id}/status
/distributed-ai/members/{node_id}/identity
/distributed-ai/revocations/{identity_id}
/distributed-ai/policies/routing/{version}
/distributed-ai/policies/security/{version}
/distributed-ai/policies/active
/distributed-ai/scheduler/leader
/distributed-ai/scheduler/leases/{partition}
/distributed-ai/config/sla/{version}
/distributed-ai/audit/checkpoints/{checkpoint_id}
```

Requirements:

- Every value has a schema version.
- Security-sensitive writes use transactions.
- Watch handlers tolerate duplicate delivery and reconnects.
- Leadership uses an expiring lease.
- Scheduling decisions carry the current cluster epoch and policy version.
- Nodes reject stale epochs and expired leadership evidence.

---

## 7. Identity and Authorization Model

Use identities similar to:

```text
spiffe://distributed-ai.local/gateway/{instance_id}
spiffe://distributed-ai.local/scheduler/{instance_id}
spiffe://distributed-ai.local/decision-engine/{instance_id}
spiffe://distributed-ai.local/telemetry/{instance_id}
spiffe://distributed-ai.local/aggregator/{instance_id}
spiffe://distributed-ai.local/node/{node_id}
spiffe://distributed-ai.local/admin/{principal_id}
```

Minimum authorization intent:

| Identity | Allowed operations |
|---|---|
| Gateway | Submit validated inference requests and read approved public policy metadata |
| Telemetry service | Accept admitted-node telemetry and write operational streams |
| Scheduler | Read telemetry, hold scheduler lease, and issue signed task assignments |
| Node agent | Send telemetry, receive its assigned tasks, and return signed results |
| Aggregator | Verify results and persist result/audit metadata |
| Administrator | Change approved policies through strongly authenticated and audited workflows |

Never treat network location as sufficient authorization.

---

## 8. Cryptographic Requirements

### 8.1 Initial profile

- Transport: TLS 1.3.
- Internal service authentication: mTLS with short-lived X.509 SVIDs.
- Classical message signatures: Ed25519, or ECDSA P-256 when required by compliance.
- Symmetric authenticated encryption: AES-256-GCM or ChaCha20-Poly1305.
- Hashing: SHA-256 or SHA-384.
- Artifact signing: Sigstore Cosign.
- Key custody: KMS, HSM, or Vault for high-value keys.
- Default post-quantum KEM: ML-KEM-768 (FIPS 203).
- Default post-quantum signature: ML-DSA-65 (FIPS 204).
- Default hybrid TLS 1.3 transition group: `X25519MLKEM768` when supported end to end.
- Preferred PQ implementation backend: OpenSSL 3.5+ native provider implementation.
- OQS compatibility backend: `oqs-provider` + `liboqs` only when explicitly required and version-tested; not a silent fallback.

### 8.2 Mandatory rules

- Do not create a homemade encryption/signature algorithm.
- Do not create a homemade hybrid KEM combiner. For TLS, use a library/protocol-defined hybrid group such as `X25519MLKEM768`.
- Do not concatenate ambiguous strings for signing.
- Sign canonical serialized bytes.
- Include a domain separator, schema version, algorithm, key ID, and signature-policy identifier.
- Never reuse a nonce where the chosen algorithm forbids reuse.
- Use separate keys for separate purposes.
- Do not log secrets, private keys, raw tokens, sensitive prompts, model outputs, KEM shared secrets, or deterministic test seeds.
- Make rotation and revocation testable.
- Never use deterministic ML-KEM/ML-DSA test inputs in production; provider seed/entropy injection is test-only.
- Treat ML-KEM decapsulation as a KEM operation, not as a plaintext-decryption API. Do not build an error oracle around ciphertext validity.
- Feed KEM-derived shared secret material only into an approved protocol/KDF construction; never reuse it as a long-lived application secret.
- Zeroize transient shared secrets and private material where the language/provider exposes a reliable mechanism.
- When policy says `pq_required`, `hybrid_required`, or `dual_required`, missing provider capability is a startup/handshake/verification failure, not permission to downgrade.
- A compliance profile must separately verify the certification/validation status of the exact cryptographic module/build; the presence of an algorithm in a provider is not itself proof of a particular certification.

### 8.3 Example signed telemetry fields

```text
schema_version
message_type
node_id
authenticated_identity
timestamp
expires_at
sequence_number
nonce
metrics
previous_message_hash
signature_algorithm
key_id
signature
```

### 8.4 Replay checks

For every admitted node, track atomically:

- Highest accepted sequence number.
- Recently accepted nonces within a bounded window.
- Maximum permitted clock skew.
- Message expiry.
- Current identity/key status.

Reject and audit stale, duplicated, expired, wrongly bound, or invalidly signed messages.

---

## 9. Audit Requirements

Every security- or decision-relevant event should include:

- Schema version.
- Unique event ID.
- Event type.
- UTC timestamp.
- Actor identity.
- Task/request correlation ID.
- Policy version.
- Cluster epoch when applicable.
- Relevant artifact and input/output digests.
- Previous event hash.
- Current event hash.

Use a domain-separated construction similar to:

```text
event_hash = SHA-256(
  "DISTRIBUTED_AI_AUDIT_V1" ||
  previous_event_hash ||
  canonical_event_without_event_hash
)
```

The hash chain provides tamper evidence, not durable storage by itself. Persist events in a restricted append-oriented database or versioned/retained object store. Periodically create and sign Merkle roots.

---

## 10. Testing Requirements

No security feature is complete without negative tests.

### 10.1 Minimum unit tests

- Stable canonical serialization.
- Valid signature acceptance.
- Modified-field signature rejection.
- Expired-message rejection.
- Node-ID/identity mismatch rejection.
- Replay and lower-sequence rejection.
- Authorization allow and deny cases.
- Hash-chain and Merkle-proof verification.
- ML-KEM-768 key generation, encapsulation, and decapsulation interoperability.
- ML-KEM tampered-ciphertext behavior must not yield the sender shared secret or create a distinguishable application error oracle.
- ML-DSA-65 sign/verify acceptance plus modified-message/signature rejection.
- PQ algorithm-policy rejection for disallowed parameter sets or provider backends.
- `dual_required` verification fails when either the classical or ML-DSA signature is missing/invalid.

### 10.2 Minimum integration tests

- mTLS success with trusted identity.
- mTLS failure with untrusted identity.
- Credential/configuration startup failure in production.
- etcd transaction and lease behavior when Phase 3 is active.
- Leader loss and safe failover.
- Redis TLS/ACL behavior.
- Persistent audit recovery after restart.
- Artifact signature verification.
- OpenSSL/provider capability discovery proves ML-KEM-768 and ML-DSA-65 are available before PQ mode starts.
- TLS 1.3 hybrid handshake negotiates `X25519MLKEM768` when `hybrid_required` is enabled.
- A peer that cannot negotiate the required hybrid group is rejected under `hybrid_required`; any permitted staged classical fallback is explicit, observable, and covered by policy tests.
- PQ keys survive approved persistence/rotation flows without being emitted to logs or repository files.

### 10.3 Required adversarial scenarios

| Scenario | Expected outcome |
|---|---|
| Telemetry field changed after signing | Reject |
| Nonce reused | Reject |
| Sequence number goes backward | Reject |
| Task is expired | Reject |
| Node claims another identifier | Reject |
| Stale leader sends a task | Reject |
| Model digest/signature is unapproved | Reject |
| Audit event is edited or removed | Verification fails |
| Required identity/key service is unavailable | Privileged operation fails closed |
| Required PQ provider/algorithm is unavailable | Startup/handshake fails closed under required PQ policy |
| Hybrid TLS peer offers only classical groups while `hybrid_required` | Reject; no silent downgrade |
| One signature missing under `dual_required` | Reject |
| ML-DSA signature or signed field modified | Reject |
| PQ private key/seed appears in logs or tracked files | Security test/scan fails |

### 10.4 Verification discipline

Run the smallest relevant tests during iteration, then the full appropriate suite before handoff. Report:

- Commands executed.
- Pass/fail counts.
- Skipped tests and why.
- Known environment limitations.
- Any unverified claims.

Never state that tests passed if they were not run.

---

## 11. CI/CD Requirements

Pull requests should run:

1. Formatting and linting.
2. Type checking.
3. Unit and integration tests.
4. Static application security analysis.
5. Dependency and license scanning.
6. Secret scanning.
7. Infrastructure/container configuration scanning.
8. Container vulnerability scanning.
9. SBOM generation.
10. Security-policy tests.
11. Cryptographic capability checks for the exact OpenSSL/provider build used in CI/runtime.
12. PQ known-answer/vector and interoperability tests when PQ code paths are enabled.
13. Dependency pinning/SBOM evidence for the cryptographic provider and any OQS compatibility components.

Approved releases should additionally:

1. Build from a protected revision.
2. Record the immutable source commit.
3. Produce provenance.
4. Sign container and model artifacts.
5. Publish immutable digests.
6. Verify signatures before deployment.
7. Record the OpenSSL/provider versions and enabled PQ algorithms in release evidence.
8. Block release when a required PQ algorithm/group is unavailable or when an unapproved fallback backend is active.

Never expose privileged secrets to untrusted pull-request code.

---

## 12. Configuration Requirements

Production must not contain insecure defaults.

Expected configuration categories include:

```dotenv
APP_ENV=production
ETCD_ENDPOINTS=https://etcd-1:2379,https://etcd-2:2379,https://etcd-3:2379
ETCD_NAMESPACE=/distributed-ai
SPIFFE_TRUST_DOMAIN=distributed-ai.local
SPIFFE_ENDPOINT_SOCKET=unix:///run/spire/sockets/agent.sock
REDIS_URL=rediss://redis.internal:6379/0
OIDC_ISSUER=https://identity.example.com/
OIDC_AUDIENCE=distributed-ai-api
SIGNING_KEY_PROVIDER=kms
SIGNING_KEY_ID=distributed-ai-scheduler
AUDIT_CHECKPOINT_INTERVAL=1000
MAX_CLOCK_SKEW_SECONDS=5
TELEMETRY_TTL_SECONDS=10
REQUIRE_MTLS=true
REQUIRE_SIGNED_ARTIFACTS=true
REQUIRE_NODE_ATTESTATION=false

# Post-quantum / cryptographic-agility profile
CRYPTO_BACKEND=openssl-native
OPENSSL_MIN_VERSION=3.5.0
PQC_MODE=disabled
PQC_KEM=ML-KEM-768
PQC_SIGNATURE=ML-DSA-65
PQC_TLS_HYBRID_GROUP=X25519MLKEM768
PQC_CLASSICAL_SIGNATURE=Ed25519
PQC_MESSAGE_SIGNATURE_POLICY=classical
PQC_ALLOW_CLASSICAL_FALLBACK=false
PQC_ALLOW_OQS_PROVIDER=false
PQC_REQUIRE_CAPABILITY_PROBE=true
```

These names are a target contract, not permission to overwrite existing conventions blindly. Reconcile them with the real codebase and document migrations.

Rules:

- Commit only safe placeholders in example files.
- Validate required configuration at startup.
- Reject plaintext production service endpoints where encrypted transport is required.
- Keep development behavior explicit and isolated.
- Never silently downgrade security because a dependency is unavailable.
- Validate `PQC_MODE` as an enum such as `disabled`, `hybrid_preferred`, `hybrid_required`, or `pq_only_lab`; do not infer mode from library availability.
- In `hybrid_required`, require `X25519MLKEM768` (or an explicitly approved replacement) to be present before serving privileged traffic.
- In `dual_required`, require both the configured classical signature and ML-DSA signature to verify over identical canonical bytes.
- `PQC_ALLOW_OQS_PROVIDER=false` is the production-safe default when OpenSSL 3.5+ native standardized algorithms are available.

---

## 13. Coding and Change Discipline

- Preserve the current language, framework, formatting, and project conventions unless a change is justified.
- Prefer narrow modules with explicit interfaces for identity, authorization, key access, signing, replay state, and consensus storage.
- Keep business logic separate from transport and cryptographic code.
- Use dependency injection for key providers and external services to support tests.
- Use typed/versioned schemas for security messages.
- Make security errors structured but non-sensitive.
- Use UTC timestamps and define allowed clock skew.
- Make retries idempotent and bounded.
- Pin or constrain security-sensitive dependencies according to repository policy.
- Avoid unrelated formatting or refactoring.
- Do not delete or overwrite user changes.
- Do not commit generated secrets, local certificates, build output, or environment files.
- Update documentation whenever behavior or configuration changes.
- Keep PQ operations behind narrow provider interfaces; application code must not depend directly on provider-specific symbols outside the crypto adapter.
- Parse provider capability by exact standardized algorithm/group names rather than substring guesses.
- Keep production and test key-generation paths separate so deterministic seeds/entropy cannot cross into production.

---

## 14. Git and Operational Safety

- Inspect `git status` before and after changes.
- Preserve unrelated modified or untracked files.
- Never use destructive commands such as `git reset --hard`.
- Do not rewrite history, force-push, rotate external credentials, publish images, deploy infrastructure, or modify production systems without explicit authorization.
- Do not commit or push unless the user asks.
- If active credentials are found, avoid printing them and report the paths plus rotation requirements.
- If a security fix requires new external authority, credentials, or infrastructure access, stop and ask for direction.

---

## 15. Required Workflow for Every Implementation Request

### Step A — Understand

Restate the requested phase, acceptance criteria, and boundaries in concise technical terms.

### Step B — Inspect

Inspect relevant code, configuration, tests, Git state, and workflows. Trace the complete request path before editing.

### Step C — Report gaps

Provide a prioritized table:

| Priority | Evidence | Risk | Proposed minimal change |
|---|---|---|---|

### Step D — Plan

Create a short implementation plan with only one active step at a time. Identify files likely to change, tests to add, and unsafe operations requiring approval.

### Step E — Implement

Make the smallest coherent change. Preserve compatibility unless breaking behavior is necessary for security and explicitly documented.

### Step F — Verify

Run focused tests, security negative tests, configuration validation, and the broader relevant suite.

### Step G — Review

Review the diff for:

- Secret leakage.
- Authentication or authorization bypass.
- Downgrade/fallback behavior.
- Race conditions in replay or lease state.
- Missing error handling.
- Unsafe logging.
- Dependency and configuration drift.
- Documentation gaps.

### Step H — Handoff

Report:

1. Outcome.
2. Files changed.
3. Security properties added.
4. Tests run and results.
5. Remaining risks or manual actions.
6. Recommended next phase.

---

## 16. Definition of Done

A phase is complete only when:

- The implemented behavior matches the approved scope.
- Positive and negative tests exist and pass.
- Production configuration fails closed.
- No new secret or private key is stored in Git.
- Identity and authorization boundaries are explicit.
- Sensitive logs and error messages are redacted.
- Operational documentation is updated.
- Upgrade and rollback considerations are documented.
- Remaining risks are stated honestly.
- The working tree contains no accidental unrelated changes.
- If PQ functionality is in scope, the exact runtime library/provider version and algorithm capability evidence are recorded.
- If PQ functionality is in scope, negative downgrade/fallback tests pass and no required PQ policy can silently fall back.

The entire security program is complete only when:

- Exposed credentials have been revoked and rotated.
- Every internal workload has a unique, short-lived identity.
- Privileged endpoints have authentication and authorization.
- The control plane has quorum-backed authoritative state.
- Stale scheduler leaders cannot authorize work.
- Telemetry, tasks, and results are signed and replay-resistant.
- Audit events are durable, hash-linked, checkpointed, signed, and independently verifiable.
- Models and containers are verified by immutable digest, signature, and provenance.
- CI enforces secret, code, dependency, container, SBOM, and release-signing controls.
- Rotation, revocation, backup, restore, and incident-response procedures are tested.
- A threat-model review has no unresolved critical finding.
- The post-quantum migration path uses standardized algorithm identifiers and a maintained provider/library, with no custom PQ primitive or hybrid combiner.
- Hybrid TLS and message-signature migration modes have tested fail-closed semantics, observability, key rotation, and rollback.

---

## 17. Immediate Starting Instruction

Begin with a read-only repository assessment. Do not edit files until you have:

1. Mapped the project structure and runtime entry points.
2. Located credential-loading and authentication logic without exposing secret contents.
3. Enumerated HTTP routes and gRPC services.
4. Reviewed Docker/Compose/Kubernetes and CI configuration.
5. Checked the current test baseline.
6. Produced a ranked gap report and a minimal Phase 0/1 change plan.

After the assessment, implement only changes within the user's authorized scope. If the user says **“build the first phase”**, complete Phase 0 and the minimum safe Phase 1 foundation described in Section 5, verify it, and provide a professional handoff.

---

## 18. Gemini Model Routing Strategy

This project may use two coding agents with different strengths:

- **Gemini 3.1 Pro Preview** — use as the security architect, threat-modeler, protocol designer, and final reviewer for high-risk changes.
- **Gemini 3.8 Flash** — use as the primary implementation agent for repository-wide coding, configuration, test generation, CI changes, and repeated verification loops.

Model names and availability can change. At execution time, confirm the current official model identifiers. The intended identifiers when this document was written are:

```text
gemini-3.1-pro-preview
gemini-3.8-flash
```

### 18.1 Phase ownership

| Phase | Primary model | Secondary model | Reason |
|---|---|---|---|
| Phase 0 — Credential remediation | Gemini 3.1 Pro | Gemini 3.8 Flash | Pro should assess exposure, destructive-history risks, and the rotation plan. Flash can implement safe ignore rules, configuration validation, scanners, tests, and documentation after approval. |
| Phase 1 — Authentication and network hardening | Gemini 3.8 Flash | Gemini 3.1 Pro review | This phase contains broad but conventional code/configuration work. Flash should implement middleware, route protection, production defaults, Redis/Grafana hardening, and negative tests. |
| Phase 2 — SPIFFE/SPIRE workload identity | Gemini 3.1 Pro for design; Gemini 3.8 Flash for implementation | Mutual review | Identity binding and trust-domain design require careful architectural reasoning; deployment manifests, adapters, integration tests, and migration work benefit from Flash's long-running coding capability. |
| Phase 3 — Raft/etcd control plane | Gemini 3.1 Pro for design and invariants | Gemini 3.8 Flash for implementation | Pro defines authoritative state, transactions, leases, epochs, failure behavior, and consistency invariants. Flash implements clients, schemas, watchers, deployment files, failover tests, and documentation. |
| Phase 4 — Signed telemetry and replay protection | Gemini 3.8 Flash | Gemini 3.1 Pro security review | Flash implements schemas, canonical serialization, signature adapters, nonce/sequence storage, validation pipelines, and adversarial tests. Pro reviews cryptographic boundaries and race conditions. |
| Phase 5 — Signed tasks and results | Gemini 3.1 Pro for protocol design | Gemini 3.8 Flash for implementation | Pro defines what must be signed and how task, model, input, output, epoch, lease, and identity are bound. Flash integrates the protocol into scheduler, node, and aggregator flows. |
| Phase 6 — Tamper-evident audit system | Gemini 3.1 Pro for integrity design | Gemini 3.8 Flash for implementation | Pro defines canonical events, hash-chain rules, checkpoint boundaries, Merkle proofs, and failure semantics. Flash builds persistence, checkpoint jobs, verification tooling, and corruption tests. |
| Phase 7 — Software/model supply chain | Gemini 3.8 Flash | Gemini 3.1 Pro policy review | Flash is well suited to CI workflows, SBOM generation, scanning, Cosign integration, provenance, digest enforcement, and release testing. Pro reviews trust and exception policies. |
| Phase 8 — Attestation and post-quantum deployment | Gemini 3.1 Pro | Gemini 3.8 Flash for bounded implementation/tests | Hardware trust and cryptographic migration are high-risk architectural work. Pro owns the protocol/library selection, downgrade invariants, and acceptance criteria; Flash may implement provider adapters, capability gates, hybrid TLS configuration, ML-DSA message signing, and interoperability tests using approved libraries. |

### 18.2 Single-model assignment when only one model can run

If each phase must be assigned to exactly one model, use:

```text
Gemini 3.1 Pro Preview
  Phase 0 — Credential remediation
  Phase 2 — Workload identity architecture
  Phase 3 — Raft/etcd control plane
  Phase 5 — Signed tasks and results
  Phase 6 — Cryptographic audit architecture
  Phase 8 — Attestation and PQ deployment

Gemini 3.8 Flash
  Phase 1 — Authentication and network hardening
  Phase 4 — Signed telemetry implementation
  Phase 7 — Supply-chain security and CI/CD
```

This single-model split is simpler but less safe than the paired workflow. High-risk security phases benefit from separate implementation and review agents.

### 18.3 Mandatory two-model workflow

For Phases 0, 2, 3, 5, 6, and 8, use this sequence:

1. **Gemini 3.1 Pro — design:** inspect the repository, define threats, invariants, schemas, acceptance criteria, and a file-level plan.
2. **Gemini 3.8 Flash — implement:** apply the approved design in small changes and run focused plus full relevant tests.
3. **Gemini 3.1 Pro — review:** inspect the diff and test evidence for bypasses, downgrade paths, race conditions, cryptographic misuse, unsafe logging, and missing failure cases.
4. **Gemini 3.8 Flash — remediate:** implement accepted review findings and rerun verification.
5. **Human approval:** required before destructive history rewriting, external credential rotation, deployment, publishing, or production changes.

For Phases 1, 4, and 7, reverse the first two responsibilities:

1. Gemini 3.8 Flash proposes and implements the repository changes.
2. Gemini 3.1 Pro performs the security and architecture review.
3. Gemini 3.8 Flash resolves findings and reruns tests.

### 18.4 Handoff contract between models

Every model handoff must include:

```text
Phase and objective
Repository commit or exact working-tree state
Files inspected
Files changed
Threats addressed
Design decisions and invariants
Commands/tests executed
Exact pass/fail/skipped results
Remaining risks
Manual actions requiring human authority
Next agent's bounded task
```

Do not ask both models to edit the same working tree concurrently. Complete one handoff before the next agent begins. The reviewing model must inspect the actual diff and test output rather than relying only on the implementing model's summary.

### 18.5 Recommended reasoning settings

Use the highest practical reasoning setting for:

- Threat modeling.
- Credential incident analysis.
- Identity and authorization architecture.
- Consensus invariants and lease behavior.
- Signed protocol design.
- Cryptographic audit construction.
- Attestation and post-quantum migration decisions.

Use medium or high reasoning for conventional implementation and test loops. Increasing reasoning effort does not replace tests, independent review, or human authorization.

---

## 19. Post-Quantum Implementation Profile

This section is the concrete implementation contract for Phase 8. It is intentionally narrower than a general survey of post-quantum cryptography.

### 19.1 Normative algorithm profile

Use standardized names exactly as exposed by the selected provider.

| Purpose | Default | Alternate only by documented policy | Do not use as a new production identifier |
|---|---|---|---|
| Post-quantum KEM | `ML-KEM-768` | `ML-KEM-512`, `ML-KEM-1024` | `Kyber*` legacy Round-3 names |
| Post-quantum signature | `ML-DSA-65` | `ML-DSA-44`, `ML-DSA-87` | `Dilithium*` legacy Round-3 names |
| TLS 1.3 migration group | `X25519MLKEM768` | `SecP256r1MLKEM768`, `SecP384r1MLKEM1024` when policy/interoperability requires | Manually concatenated X25519 + ML-KEM shared secrets |
| Classical signature during migration | `Ed25519` | `ECDSA P-256` when required | Ad-hoc combined signature algorithm |
| Symmetric protection after key establishment | Existing approved AEAD profile | Policy-approved equivalent | Direct use of raw KEM shared secret as persistent key |

Default rationale: ML-KEM-768 and ML-DSA-65 provide a balanced standardized profile for general production migration. A different parameter set must be justified by threat model, interoperability, compliance, payload-size, CPU, and latency measurements.

### 19.2 Library/provider decision

Use this order of preference:

1. **OpenSSL 3.5+ native provider support — preferred production path.** Use native EVP APIs for ML-KEM and ML-DSA and native TLS 1.3 hybrid groups. Record the exact OpenSSL version/build in deployment evidence.
2. **Language binding/runtime that is demonstrably backed by the required OpenSSL capabilities.** Do not assume the binding exposes a feature merely because the host OpenSSL has it; prove it with an integration test.
3. **`oqs-provider` + `liboqs` — explicit compatibility/prototyping path only.** Use this when the environment cannot yet consume native standardized support or when testing algorithms/groups that are not native. Pin compatible versions/container digests and run the provider's own test suite.
4. **No hidden fallback package.** Do not silently switch to an unreviewed Python/Rust/Java PQ package because the preferred backend is unavailable. Stop, report the incompatibility, and propose a reviewed adapter or deployment-side TLS termination strategy.

When running OpenSSL 3.5+, prefer the OpenSSL implementation for standardized algorithms that it already supplies. Do not attempt to override those exact algorithms with `oqs-provider`.

### 19.3 Required provider interfaces

Keep business logic independent of the cryptographic backend. Adapt names to the repository language, but preserve these semantics:

```text
KemProvider
  algorithm() -> standardized algorithm identifier
  generate_keypair() -> protected private handle + public key
  encapsulate(public_key) -> kem_ciphertext + shared_secret_handle
  decapsulate(private_handle, kem_ciphertext) -> shared_secret_handle

SignatureProvider
  algorithm() -> standardized algorithm identifier
  generate_keypair() -> protected private handle + public key
  sign(private_handle, canonical_tbs, context) -> signature
  verify(public_key, canonical_tbs, context, signature) -> success/failure

TlsCryptoPolicy
  mode() -> disabled | hybrid_preferred | hybrid_required | pq_only_lab
  required_group() -> X25519MLKEM768 by default
  allow_classical_fallback() -> explicit boolean
  validate_runtime_capabilities() -> success/failure with non-secret diagnostics
```

Do not return raw private-key bytes from normal application interfaces when a provider/key-handle model is available.

### 19.4 Runtime capability gate

Before enabling a required PQ mode, prove the runtime supports the intended primitives. On an OpenSSL 3.5+ host, equivalent checks include:

```bash
openssl version
openssl list -providers
openssl list -kem-algorithms
openssl list -signature-algorithms
openssl list -tls1_3 -tls-groups
```

The implementation/CI must verify exact presence of at least:

```text
ML-KEM-768
ML-DSA-65
X25519MLKEM768        # when hybrid TLS is required
```

Do not treat a successful package install as capability evidence. If the application is linked to a different OpenSSL than the shell command, inspect/report the library actually loaded by the application and test through the application's own code path.

### 19.5 TLS 1.3 migration policy

Use PQ key establishment at the transport layer before inventing application-level key-exchange protocols.

Supported policy modes:

```text
disabled
  Existing approved classical TLS profile only.

hybrid_preferred
  Offer the approved hybrid group first.
  Classical fallback is permitted only when explicitly configured.
  Every fallback is observable and auditable.

hybrid_required
  The connection must negotiate the approved hybrid group.
  If the peer/runtime cannot support it, fail the connection.
  This is the production target for internal control-plane links once all peers are upgraded.

pq_only_lab
  Pure PQ negotiation/experiments only in isolated test environments unless a protocol/compliance review explicitly approves production use.
```

For OpenSSL 3.5+ TLS, configure supported groups by name using the library's group-list API/configuration. Prefer the named native group `X25519MLKEM768`. Do not manually combine an X25519 secret with an ML-KEM secret.

Record at connection establishment:

- TLS version.
- Negotiated group name.
- Peer workload identity.
- Policy mode.
- Whether fallback occurred.
- Provider/library version where practical.

Never log key shares, private keys, KEM ciphertext internals beyond what is operationally necessary, or shared secrets.

### 19.6 Message-signature migration

For telemetry, tasks, results, and audit checkpoints, use a versioned signature list rather than replacing the existing signature field in a way that breaks old readers.

Recommended envelope shape:

```text
signature_policy: classical | dual_required | pq_only
signatures:
  - algorithm: Ed25519
    key_id: ...
    signature: ...
  - algorithm: ML-DSA-65
    key_id: ...
    signature: ...
```

Rules:

1. Compute the canonical to-be-signed bytes once, excluding the signature values themselves.
2. Apply the existing domain separator and schema version before signing.
3. Both signature algorithms sign the exact same canonical bytes.
4. Under `dual_required`, both signatures must be present, trusted, unrevoked, and valid.
5. Verification order must not create an authorization bypass; authorization happens only after the complete signature policy succeeds.
6. Keep separate key IDs, key lifetimes, and revocation records for classical and PQ signing keys.
7. Do not call the two signatures a new cryptographic primitive. They are two independent signatures governed by an application verification policy.

### 19.7 Key formats, storage, and lifecycle

- Prefer provider-supported standard encodings such as PKCS#8 for private keys and SubjectPublicKeyInfo/PEM for public keys when file representation is unavoidable.
- Treat any retained/generated ML-KEM or ML-DSA seed as fully sensitive private-key material.
- Production private keys should be referenced by protected handle/KMS/HSM/Vault integration when the selected service actually supports the required PQ algorithm; capability must be verified rather than assumed.
- If a production deployment temporarily requires software-held PQ keys, use a restricted secret volume/keystore with encryption at rest, least privilege, backup/rotation controls, and an explicit migration plan to stronger custody.
- Never generate production keys in CI logs, Dockerfiles, image build layers, example configuration, or repository-tracked scripts.
- Public keys may be distributed through the authoritative membership/policy state with algorithm, key ID, validity interval, purpose, and revocation status.
- Rotation must support overlap: verify with the current and explicitly allowed previous public key during a bounded transition window while signing only with the current key.

### 19.8 KEM usage boundary

ML-KEM is a key-encapsulation mechanism, not a general data-encryption API.

- Prefer TLS 1.3 hybrid key establishment for service-to-service transport confidentiality.
- For application envelope encryption, use only a reviewed, protocol-defined KEM-to-AEAD construction or a maintained high-level library that defines the KDF/context/AAD rules. Do not design a KEM-DEM format ad hoc inside a feature patch.
- Never interpret decapsulation as "decrypt ciphertext and tell me whether it was valid." Avoid distinguishable error behavior that can become a validity oracle.
- Bind any derived encryption context to protocol version, sender/recipient identities, message type, and correlation/task identifiers according to the reviewed envelope specification.

### 19.9 Interoperability test matrix

At minimum, test:

| Case | Expected result |
|---|---|
| Native OpenSSL peer ↔ native OpenSSL peer, `hybrid_required` | Negotiates `X25519MLKEM768`; succeeds |
| Required hybrid group absent on one peer | Fails closed |
| `hybrid_preferred` with explicitly allowed classical fallback | Connects only through documented fallback; emits metric/audit event |
| ML-KEM-768 encapsulate in process A, decapsulate in process B | Shared secret matches |
| ML-DSA-65 sign in process A, verify in process B | Valid signature accepted |
| ML-DSA message modified | Reject |
| `dual_required`, classical valid but PQ missing/invalid | Reject |
| `dual_required`, PQ valid but classical missing/invalid | Reject |
| Key revoked in authoritative state | New messages/handshakes requiring that key fail according to policy |
| Provider/library unavailable after restart | Required PQ mode does not silently downgrade |

Where an OQS compatibility backend is approved, add cross-backend tests only for encodings/protocols that are specified as interoperable. Do not assume provider-private key encodings are interchangeable.

### 19.10 Performance and operational budget

Before production rollout, measure on representative hardware:

- Handshake latency p50/p95/p99.
- CPU cost per handshake/sign/verify/encapsulate/decapsulate.
- Key/ciphertext/signature sizes.
- Peak memory impact.
- Connection-failure rate.
- Fallback rate where fallback is temporarily permitted.
- Telemetry/task throughput impact when dual signatures are enabled.

Do not disable PQ based on intuition about overhead. Measure and document the actual budget and any capacity changes.

### 19.11 CI implementation gate

A PQ-enabled CI job must:

1. Print the non-secret OpenSSL/provider version metadata.
2. Assert exact required algorithm/group names are available.
3. Run ML-KEM-768 known-answer/vector or library conformance tests where available.
4. Run ML-KEM inter-process encapsulation/decapsulation tests.
5. Run ML-DSA-65 positive and tamper-negative tests.
6. Run `dual_required` policy tests.
7. Run a TLS 1.3 local client/server handshake that proves the negotiated hybrid group.
8. Run a negative handshake with the required group removed and prove fail-closed behavior.
9. Scan the diff/worktree/artifacts for private keys, seeds, test vectors accidentally treated as secrets, and insecure configuration.
10. Record dependency/SBOM information for the crypto runtime used in the release.

### 19.12 Staged implementation sequence

When the user authorizes the PQ phase, execute in this order:

1. **Inventory runtime:** identify language versions, OpenSSL actually linked/loaded, TLS termination points, gRPC/HTTP stacks, certificate handling, and existing signature code.
2. **Capability gate:** add a read-only command/test that proves ML-KEM-768, ML-DSA-65, and (when needed) `X25519MLKEM768` are usable through the real runtime path.
3. **Provider abstraction:** add narrow KEM/signature/TLS-policy interfaces without changing production crypto behavior.
4. **Primitive tests:** implement ML-KEM-768 and ML-DSA-65 adapters with positive/negative/interoperability tests.
5. **Message migration:** extend signed envelopes to support explicit signature lists and `dual_required`; keep backward compatibility versioned and intentional.
6. **Hybrid TLS lab:** enable `X25519MLKEM768` in a local/container integration environment and prove negotiated-group evidence.
7. **Fail-closed policy:** implement `hybrid_required`/`dual_required` and negative downgrade tests.
8. **Observability:** add non-secret metrics for algorithm/group/provider, fallback count, verification failures, and incompatible peers.
9. **Key lifecycle:** implement protected generation/import, rotation, revocation, overlap, and recovery documentation.
10. **Performance test:** measure representative latency/CPU/size impact.
11. **Security review:** inspect for downgrade, oracle, key leakage, canonicalization mismatch, provider confusion, and unbounded compatibility fallbacks.
12. **Production rollout:** only after prerequisites, interoperability, rollback, and operational ownership are documented and approved.

If earlier roadmap phases are incomplete, the agent may implement the PQ adapter and isolated tests when explicitly authorized, but must not claim the platform is production-secure merely because PQ algorithms are present.

### 19.13 Acceptance criteria for a practical PQ implementation

Do not mark Phase 8 PQ implementation complete until all applicable statements are true:

- The repository uses standardized algorithm identifiers (`ML-KEM-*`, `ML-DSA-*`).
- The selected backend is a maintained library/provider and its exact runtime version is recorded.
- OpenSSL 3.5+ native support is preferred where available; any OQS fallback is explicit, pinned, tested, and justified.
- Required runtime capability is checked through the actual application path.
- ML-KEM-768 inter-process encapsulation/decapsulation tests pass.
- ML-DSA-65 positive and tamper-negative tests pass.
- `dual_required` cannot be bypassed with one valid signature.
- Hybrid TLS negotiates the intended named group and the negotiated group is observable.
- `hybrid_required` fails when the peer cannot satisfy the hybrid policy.
- No custom PQ primitive, custom hybrid KEM combiner, or ad-hoc key encoding exists.
- No private PQ key, seed, or shared secret is logged or tracked in Git.
- Rotation and revocation are tested.
- Performance impact is measured.
- Rollback does not require reintroducing a silent downgrade.
- Documentation clearly distinguishes experimental/lab modes from production policy.

### 19.14 Normative references to verify at execution time

Before a production implementation or dependency upgrade, verify the current official versions/errata of:

- NIST FIPS 203 — ML-KEM.
- NIST FIPS 204 — ML-DSA.
- NIST FIPS 205 — SLH-DSA, if a hash-based signature alternative is considered.
- NIST SP 800-227 — recommendations for secure KEM use.
- OpenSSL documentation for the exact deployed release, including ML-KEM EVP, ML-DSA EVP, and TLS group configuration.
- Open Quantum Safe `liboqs` / `oqs-provider` documentation only when the OQS compatibility path is explicitly enabled.

Treat standards errata and provider security advisories as implementation inputs. Do not freeze cryptographic behavior to assumptions from this document when the normative standard or maintained provider has issued a security-relevant correction.

