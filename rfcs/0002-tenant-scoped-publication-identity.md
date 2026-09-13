# RFC-0002: Tenant-scoped publication identity

- Status: accepted
- Date: 2026-09-13
- Issue: [#264](https://github.com/KirilsTurkins/latent-service-fabric/issues/264)
- Decision: [ADR-0027](../adr/0027-separate-publication-authority-from-component-identity.md)
- Implementation: #265 catalog, #266 runtime/deployments, #267 public selectors

## Problem and preserved decisions

The delivered catalog keys immutable publications and lifecycle records by the
component `ReleaseDigest`. Consequently, correcting an embedded SBOM creates a
different immutable package that cannot coexist with the first publication of
the same Wasm. Different tenant/package associations also conflict. This is the
intentional compatibility rule in ADR-0019, not a demonstrated authorization
bypass.

Supersede only that uniqueness rule. Preserve ADR-0019's component/package
separation, ADR-0010's immutable metadata versus deployment policy, and ADR-0024's
package-bound immutable SBOM. Do not make authenticated inventory mutable to
avoid fixing publication identity. Keep fresh activation state, fixed/shared
execution resources, current authorization and the authenticated native loader.

## Four identities

| Identity | Meaning | Does not establish |
| --- | --- | --- |
| Component digest (`ReleaseDigest`, legacy field name) | Exact executable Wasm bytes | Package association, tenant, lifecycle or permission |
| `PackageDigest` | Exact immutable package manifest and its authenticated content graph | Admission to a tenant or current execution authority |
| `PublicationRef` | One immutable artifact association in one explicit catalog scope | Permission to use it without current authorization |
| Deployment revision | Exact selected publication plus immutable deployment configuration at that revision | Current eligibility or permission to roll back |

A publication owns independent admission, lifecycle generation, selected evidence
and operation history. It is not the compiled code or a persistent guest instance.

## Canonical publication identity

Introduce a strict `PublicationId` with the canonical textual form
`publication:sha256:` followed by 64 lowercase hexadecimal digits (83 bytes).
There is no implicit conversion from component, package or guest blob identities.
Parsing validates representation only; storage and authorization validate the
complete association. Retained IDs must not retain oversized caller capacity.

The identifier hashes this versioned, length-framed tuple:

```text
SHA-256(
  "lsf-publication-v1\0" ||
  frame(scope-kind) || frame(scope-value) ||
  frame(content-kind) || frame(content-identity)
)
```

`frame` is an unsigned 64-bit little-endian byte length followed by exact bytes.
Scope kind is `tenant` with the validated tenant's exact UTF-8 bytes, or
`local-unscoped` with an empty value. Tenant identity is not case-folded or
normalized. Content kind is `package` or `trusted-local`; the identities below
are canonical lowercase `sha256:` strings encoded as ASCII.

For a package, content identity is its `PackageDigest`. The stored package kind
and complete verified association must match that immutable package; the same
digest cannot be relabeled as another package kind.

For trusted-local content, identity is the SHA-256 of its canonical immutable
version-1 `COMPLETE` record: component digest/length, exact persisted descriptor
metadata digest and manifest digest, with no admission field. This is a local
content identity, never a fabricated `PackageDigest` or publisher proof. The
existing completion encoding is specified by
[the integrity codec](../crates/latent-artifacts/src/local_repository/integrity.rs).
Migration preserves those bytes; new local publication uses the same bounded
canonical encoding. A future incompatible completion encoding needs a distinct
identity version rather than silently changing this construction.

`PublicationRef` carries both the ID and explicit scope. The scope must agree
with the stored association and the caller's authenticated context. IDs are not
bearer capabilities and cannot authorize cross-tenant discovery or execution.
Enforced package publications require tenant scope. Local-unscoped publications
remain an explicit trusted-local compatibility case, not a public tenant bypass.

## Uniqueness, tenant restrictions and replay

Exactly one publication exists for a given scope and immutable content identity.
Publishing the same association again is an exact-content replay; it does not
reset lifecycle state, restore a revoked publication, replace evidence silently
or mint fresh authority from a historical receipt. A conflicting immutable
association under an existing ID is corruption/conflict, not an overwrite.

Different immutable packages can coexist in one tenant with the same component.
The same package can be independently admitted into two tenants only when its
immutable manifest permits both scopes and each tenant's current policy approves
the publisher, builder, evidence and package. Specifically:

- An embedded nonempty `manifest.metadata.tenant` remains an exact restriction.
  A different requested tenant is denied.
- An absent embedded tenant means tenant-neutral package content. It may be
  admitted independently into each explicitly authorized tenant; absence is
  not authority and does not create a global publication.
- Never rewrite signed manifest bytes to insert the receiving tenant. The
  publication/admission record and catalog view carry the selected tenant
  separately from immutable package metadata.
- Trusted-local artifacts retain their existing explicit tenant or unscoped
  interpretation. Tenant neutrality does not promote raw local content to
  enforced package trust.

Corrected SBOM `S2` produces package `P2` alongside `P1` containing `S1`, even
when both contain component `C`. Each package needs its own valid proofs. Detached
evidence renewal for `P1` cannot silently turn its embedded inventory into `S2`.
Revoking or renewing either publication does not alter the other's lifecycle.

Operation replay remains scoped by authenticated scope and operation ID, with
the complete original intent and exact publication bound to the receipt. Reusing
an operation ID for another package/publication conflicts. Recovery of a lost
response returns the retained original association, even after another package
containing the same component is admitted. Replay is not a current execution
grant. The bounded history window remains explicit; a pruned/unknown operation
does not justify guessing a publication or automatically replaying a mutation.

## Legacy selectors and public compatibility

Existing `ReleaseDigest`, Protobuf field numbers, component fields, package
digests and guest blob digests retain their meanings. No existing wire string is
reinterpreted as a package or publication identity. #267 adds an explicit
publication selector and additive result fields to current contracts.

Requests choose exactly one of a legacy component selector or an explicit
`PublicationRef`. Supplying both, a present-but-invalid new selector, an unknown
scope variant or a mismatched tenant is rejected; it never falls back to the
legacy field. Results may report publication, package and component together as
distinct facts. Non-capsule results have no invented executable component.

Fresh legacy resolution uses this rule within the already authorized scope:

| Visible immutable associations for component C | Result |
| --- | --- |
| Zero | Not found, without revealing foreign-scope candidates |
| Exactly one | Resolve that publication, then check its current eligibility |
| More than one | Fail with a documented ambiguity error requiring an explicit publication |

Count associations independently of their admitted/revoked/retired state.
Revocation must not make a fresh request silently choose another package.
Resolution needs at most two matching index entries to establish ambiguity;
there is no unbounded candidate enumeration. Unauthorized callers receive no
candidate list or foreign-tenant existence information.

Malformed or competing selectors use `InvalidArgument`. Permission to operate
on the requested scope is checked before lookup; an absent publication within
that authorized scope uses `NotFound`, including an ID owned by another scope.
Ambiguity uses `StateConflict`, reason `publication-selector-ambiguous`, with
`retryable: false` and bounded guidance to supply a publication. It is not a
transient error that clients should resolve by repeating the same selection.

Historical state is different from a fresh component-only request. Migration
binds every retained deployment revision, route/rollback target and committed
operation to its exact original publication. Those captured associations remain
usable for inspection and replay after coexistence; eligibility is still checked
at execution/rollback. They are never recomputed by selecting first/latest.

Internal callers that lack a trusted scope must use an explicit publication or
an already captured legacy association. A global component lookup cannot choose
another tenant's publication as an authorization shortcut.

An old publisher can still submit an exact package/local artifact, and component
fields in its response remain unchanged. The new server also returns the exact
publication. If the old client ignores it, later fresh component-only requests
can fail with ambiguity; it must upgrade to select coexistence explicitly.

## Artifact ownership and lifecycle

Store each immutable package and component safely deduplicably. Publication
metadata, admission grants, evidence selection, revocation and lifecycle
generations stay independent. Byte equality cannot copy another publication's
authority. Grant creation always verifies current trust and the exact scope.

Reference accounting must distinguish retained publication metadata, historical
references, active source/preparation pins and shared content owners. Retiring
one publication cannot unlink bytes while another publication or live owner
needs them. Physical bytes may be charged once to a bounded shared store while
each publication pays its own metadata/index/authority charge. GC uses bounded
node-owned work; recovery validates references before deleting or granting use.

Lifecycle generations are monotonic per publication and are never reset by
republication, evidence renewal, migration or restart. Revocation/tombstone and
generation floors cannot be pruned merely to admit more records. Exhausted
security-history capacity fails closed. Reclaiming payload bytes is distinct
from erasing the security floor or reusing an identity with generation one.

Non-capsule package kinds fit the same scoped publication model with an optional
component association. This RFC does not enable them on executable admission.
Their owning Phase 3 tickets must define admission and usage; prepare/invoke
reject a non-executable publication rather than treating package bytes as Wasm.

## Runtime, cache and deployment authority

#266 carries the exact publication through sealed sources, metadata/readiness
tokens, queued work, route pins and the final guarded-start check. A currentness
token binds publication, tenant, lifecycle generation and the issuing catalog
owner. A token from another publication or a retired/reopened owner cannot be
substituted because component bytes match.

Deployment revisions bind publication and configuration; changing either creates
a new revision under existing CAS/preconditions. Captured rollback targets keep
their publication through restart and still require current eligibility.

Immutable code deduplication is separate from prepared authority. Compiled code
may be shared only with exact engine/target/code-generation/host-ABI compatibility
and independently owned images. Fresh activations receive new stores, grants,
budgets, handles and provider bindings for their publication. Metadata, secrets,
policy generations, lifecycle capabilities and guest state are not shared code.

The existing native cache may remain conservative: add publication identity to
its exact authenticated input association, preserve compiler/sandbox/key and
engine checks, and never broaden native sharing merely to save compilation.
Component-only cache hits cannot bypass independent publication admission.
Dormant publication count allocates bounded metadata and shared artifact storage,
not one repository, file handle, worker, provider, store or cell per publication.

## Persistence migration and downgrade fence

#265 delivers a version-2 catalog format and explicit offline migration under the
existing exclusive catalog-root owner. New catalogs use the new format. Opening
an old root must either follow its supported explicit migration path or return
an actionable migration-required result; it must not pretend old records already
contain independently scoped publication authority.

Migration preserves original immutable `COMPLETE`/package bytes and historical
operation receipts, retaining bounded mappings to their derived publications.
Missing scope, package/local completion identity, inconsistent receipts, damaged
content or an ambiguous retained association is a migration error. No proof,
tenant or permission is invented to make recovery succeed.

Expired or revoked historical admissions remain inspectable and ineligible.
Migration verifies their immutable associations and security history without
requiring or fabricating a new positive execution grant. Positive eligibility
after migration still requires current trust and lifecycle checks.

The durable sequence is:

1. Take the root owner, reject a concurrently running node/migrator, validate old
   mode/currentness records and preflight configured metadata/disk limits.
2. Persist a versioned migration intent and an old-reader-recognized format
   fence before making new-format associations visible. The existing lifecycle
   `MODE` reader rejects versions other than one; use that checked boundary or an
   equally proven existing rejection path. A new marker ignored by old binaries
   is insufficient, including for empty catalogs.
3. Build/verify bounded batches of new records and legacy association mappings.
   Each committed progress boundary records deterministic identity/count/digests
   and is synced before advancing. Original immutable bytes and history remain
   recoverable; there is no per-mutation whole-catalog rewrite or dual writer.
4. Validate the completed index/content/lifecycle associations, sync the new
   format root and commit the active-format marker. Only then admit ordinary
   operations. #266 separately migrates deployment/control records against these
   retained exact associations before exposing routes.

Migration staging/progress must use a namespace that old startup cleanup cannot
reap. Tests must show that an old-reader attempt rejects the fenced format without
destroying original bytes, committed records or migration progress. The initial
durable fence must identify enough validated recovery state to resume safely;
an unrelated ignored intent file cannot create a window for mixed-format writes.

Migration has explicit record, byte, staging, disk and work limits. Batch size
defaults to 32 records with a hard ceiling of 1,024; existing tighter record and
byte bounds still apply. Intent/progress metadata is bounded, and one batch owns
at most its reserved input/output state. Total mapping and security-history
charges count against configured catalog limits. Backup/copy requirements are
preflighted; quota exhaustion cannot delete originals or lower security floors.

An interrupted migration is resumable from validated durable progress; it is not
served as a mixed-layout catalog. Failure reports the migration stage and exact
root/format recovery action without secrets. #265 supplies the offline migration
entry point and finite status/receipt; #267 composes it into operator inspection
and upgrade workflows rather than creating a second migration implementation.

Downgrade of a migrated root is unsupported and old binaries must reject it.
Rollback means stopping all owners and restoring a complete consistent offline
backup of catalog and control state. Removing the format fence or rewriting
component fields is not a supported downgrade. The v1 reader rejection and each
crash boundary require executable tests, not only an operator warning.

A backup restore is not permission to forget subsequent revocations, generation
floors or committed operations. Before serving restored state, reconcile all
required current security history. If the older format cannot represent that
history or newer publications, refuse downgrade and recover with the new runtime.

## Compatibility and implementation owners

| Surface | Required association and compatibility | Owner |
| --- | --- | --- |
| Admission and artifact catalog | Scoped publication; immutable package/local content; current tenant policy; tenant-neutral package handling | #265 |
| Shared content storage | Bounded deduplication, retained references and safe reclamation | #265 |
| Lifecycle and evidence renewal | Independent publication generations, selected evidence and durable security floors | #265 |
| Operation/audit receipts | Exact publication/intent; unchanged historical bytes and component fields; bounded replay window | #265 storage, #267 projections |
| Preparation and native cache | Publication-bound source/currentness; code identity never substitutes for authority | #266 |
| Deployments, routes and rollout | Publication pinned in immutable revision/CAS and captured targets | #266 |
| Rollback/restart | Retained original association plus current eligibility; no first/latest re-resolution | #266 |
| RPCs, CLI and schemas | Additive explicit selector/result fields, validated presence, bounded pages, ambiguity diagnostics and migration workflow | #267 |
| Rust/TypeScript/Go/C/Java/.NET models | Distinct typed identities and identical selector/error/receipt semantics | #267 then shared client profile #227 |
| Executable clients, providers and web | Consume the selected publication model; no second identity stack | #228/#230/#260–#263 and their owning Phase 3 tickets |

#264 closes on this accepted decision and consistent documentation. It does not
claim that coexistence, migration, selectors or code sharing are already delivered.
#265, #266 and #267 must each satisfy their executable criteria before the Phase 3
gate #240 can accept the identity correction.

## Finite acceptance scenarios

| Scenario | Required observation | Owner |
| --- | --- | --- |
| Same C, corrected embedded SBOM S1→S2 | Distinct P1/P2 and publications coexist, both immutable and independently authenticated | #265/#267 |
| Same C, different packages in one tenant | Distinct exact publication selection; fresh legacy C is ambiguous | #265/#267 |
| Same tenant-neutral P/C in two tenants | Independent authorization, lifecycle and evidence; embedded foreign-tenant restriction still denies | #265/#266 |
| Revoke/renew/retire one publication | Another publication stays independent; shared bytes remain while referenced | #265/#266 |
| Captured operation/deployment plus later coexistence | Replay, held route and rollback retain their original association | #265/#266/#267 |
| Warm/native/queued work with wrong or stale publication | Fail at currentness/guarded start; no borrowed grant or code-only permission | #266 |
| Migration/publication interruption, race or quota failure | Finite cleanup/recovery, no mixed visibility, no missing history or premature byte reclamation | #265 |
| New explicit versus legacy wire requests in six languages | Original field meaning, exact scope, invalid presence and ambiguity agree; no foreign candidate leak | #267 |
| Clean separate client/node workflow and restart | Publish, migrate, select, invoke, revoke/renew, replay and rollback use actual implemented paths | #267/#238 |

Use small deterministic fixtures, explicit readiness/cleanup barriers and bounded
watchdogs. No 100,000-release/load campaign is required for the identity change.
Historical benchmarks and release evidence remain tied to their original
versions. #239 measures the completed Phase 3 resource model; #237/#240 update
completion documentation only after the implementation and evidence pass.

## Alternatives rejected

Keeping one component as one publication prevents legitimate package reuse.
Making SBOM/configuration mutable breaks immutable package authentication.
Selecting first/latest or silently ignoring revoked candidates changes the
selected authority. Reinterpreting `ReleaseDigest` breaks existing wire meaning.
One private catalog or execution resource per publication violates bounded shared
ownership. A separate compiled-code identity is useful but does not repair any
of those authorization or migration defects by itself.
