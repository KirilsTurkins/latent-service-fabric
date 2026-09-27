# ADR-0051: Author static release evidence without a Rust toolchain

- Status: Accepted
- Context: First Integration Feedback #633

## Decision

Maintain a Node.js frontend release tool that runs the existing static capture
adapter and released native packager, then creates interoperable publisher and
web-assembly builder evidence. It does not compile Rust, manufacture organization
trust, execute framework builds or change package build's unsigned behavior.
Organization policy, source approval and signing keys remain external inputs.

The observation uses `web-package-assembly/v1`: explicit supplied files,
operator-asserted repository, incomplete declared dependencies, non-hermetic
assembly and unchecked reproducibility. Exact material identities bind the
reviewed inventory, actual packager, Node/Python executables and maintained
assembly recipe. The adapter verifies source observations and output bytes;
the native packager supplies the output descriptor identity and embedded SBOM.
This does not establish that an asserted framework build actually ran.

## Authority and protected inputs

A signing request identifies the exact package and observation hashes,
publisher and builder role identities and raw public keys, and a half-open validity period.
Creating a request grants no approval. An external organization review/signing
job supplies the approved document and keys. Its policy must explicitly permit
the assembly recipe and source; a publisher key alone is insufficient.

The local signer accepts canonical machine JSON, rejecting duplicate members,
unsafe integers and unbounded structure. It requires Ed25519 PKCS#8 DER files
whose derived public keys match the approved role. Linux/WSL files must have one
link, belong to the current UID and deny group/other access, in a private canonical
directory. No key contents enter arguments, environment, package, receipt or
child process. Input buffers are cleared; Node/OpenSSL's internal key copies and
garbage-collection lifetime are outside a secure-erasure claim. HSM/KMS users may
produce the same closed DSSE/referrer profile in their independent signer.

One short-lived process signs at most one publisher envelope (4 KiB) and one
builder envelope (48 KiB). The existing native verifier independently checks
cryptography, exact package/output association, current publisher/builder policy,
revocations, tenant and SBOM before a completion marker is written. Signer-side
matching is not admission authority. Partial evidence directories cannot be
mistaken for completed output and are never automatically uploaded.

## Resource and recovery contract

Use existing capture/native asset and package bounds. JSON is at most 1 MiB,
16 levels, 8192 values and 4096 bytes per string; approved plans are at most
16 KiB and observations at most 32 KiB. Reads reject nonregular files, links,
changed size/identity/time and unsupported paths. Each child has a finite
deadline and 1 MiB combined diagnostic budget. Maintained children do not spawn
unbounded worker trees. Cancellation terminates the active child before returning.

Fresh private outputs and exact completion markers separate prepare, approval,
signing, verification and transfer. No background watcher, per-site owner or
automatic mutation retry is introduced. Push may have an uncertain remote
outcome; inspect/pull its recorded immutable digest before deciding what to do.
Publish and evidence renewal use persisted original operation IDs and explicit
generation preconditions. UNKNOWN/evicted receipts are not proof of nonexecution.
Route cutover and rollback use ADR-0047's durable route-set reconciliation.

Evidence renewal keeps package bytes unchanged but creates new approved evidence
and an explicit renewal operation. Trust/revocation changes require current
verification; old receipts and expired snapshots never revive authority.
Terraform provisions the runtime and protected state separately from frontend
publication updates. No publication rollout should replace the runtime revision.

## Qualification

The dedicated workflow authenticates the released archive against its exact
tag, source commit, publisher workflow and GitHub-hosted identity. It checks
signed hashes and the complete archive inventory before use. A digest-pinned
Ubuntu container has Node/Python and no Cargo/rustc. It runs as a non-root UID,
without capabilities, privilege escalation or external networking, with bounded
memory, processes, temporary disk and elapsed time.

New ephemeral test identities exercise actual released package verification,
revoked-publisher rejection, TLS OCI push/pull by digest, enforced publication,
GET/HEAD routing, evidence renewal, rollback and clean restart of two independent
static publications. The registry and node are actual processes. The test honors
the persisted restart clock floor and observes no dormant capsule resources.
Its minimal documentation example is not a Docusaurus compatibility claim;
framework/CSP qualification is tracked separately. No ACA/ACR support is inferred.
