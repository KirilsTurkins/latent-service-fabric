# Immutable target inspection

`latent route target` and `NodeService.InspectHttpTarget` inspect the existing
tenant-scoped catalog and compiled capability plans. The authenticated caller
must have tenant administrator management access. An ordinary application
caller, caller-supplied operator header, or publication from another tenant does
not grant access. The route resolver, publication catalog and HTTP binding owner
remain the authoritative selectors.

```text
latent route target --service examples/java-http-adapter \
  --contract latent:web/application@0.1.0 --function handle \
  --publication publication:sha256:<64-lowercase-hex> --include-preparation
```

An ordinary typed child can use the same query with its actual service, contract
and function. `exportCompatible` reports that requested typed export;
`httpCompatible` separately identifies the buffered web application export. A
typed child does not acquire an HTTP surface by running on an HTTP-enabled node.

Every selector is nonempty and bounded at 512 UTF-8 bytes. Publication selectors
must use the exact `publication:sha256:` identity and the configured tenant.
There are at most 32 candidates, dependencies, policies per dependency and HTTP
bindings per candidate. Requests are limited to 8 KiB and responses to 64 KiB.
`maximumWaitMillis` accepts zero for the 10 second default or a finite value at
most 30 seconds; the original RPC deadline can shorten that wait. There is no
background poller or implicit retry.

## Selection and currentness

Without an explicit revision/publication the reply preserves all bounded
candidates. A legacy manifest selector remains absent in
`requestedPublication` even when the compiled candidate captured an exact
`publication`. `componentDigest` and `packageDigest` are independent identities;
raw local artifacts without a verified package association report absence and
`unmanaged-publication` rather than manufacture a package identity. Package kind
is reported only from the authorized catalog's verified package association.

`selectedRevisionId` is present only when a supported explicit `routingKey` was
supplied and the existing resolver selected a returned candidate. A canary reply
without that key lists candidates and weights. This does not predict which
revision an arbitrary future HTTP request will select, and inspection never
changes the existing routing algorithm.

`catalogTransaction`, `routeGeneration`, and the compiled capability
`bindingGeneration` describe one retained catalog publication. `httpBindings`
contains each actual HTTP object's `id`, `generation`, selected deployment
generation and currentness. Those object generations are separate mutation
preconditions. Dependency records retain the selected binding and policy
`id`/`digest`/`revision`, safe provider profile and configuration identity, and
the actual provider configuration epoch. Credentials, raw configuration,
policy restrictions and provider payloads are absent.

The handler checks its retained catalog, original admission and dependency/HTTP
binding identities again after preparation. A change produces `state=stale`
and clears positive candidate eligibility. `policyStoreGeneration`, when
configured, is sampled before and after the observation through the existing
policy owner. Provider identity and currentness remain explicit per dependency.
`liveGrantsChecked=false` states that grants for a future application's caller
were not evaluated. A coherent report is a bounded observation, not a reservation
or permission to execute.

After a policy is revoked or replaced, inspection can report
`policy-changed-or-revoked` while retaining the deployment's original selected
policy revision. Restoring a grant does not refresh an already compiled
deployment. Read the canonical current objects, use a new reviewed deployment
operation with explicit generation/state preconditions, and inspect that new
selection before updating its HTTP binding. Recover uncertain mutations using
their original deployment/trigger operation IDs; inspection does not replay them.

## Preparation and output

`--include-preparation` uses the existing repository preparation path and
consumes the original ready pin. It checks the same factory, immutable
descriptor and current admission without materialization, an active execution
slot, guest Store, activation or provider operation. Preparation may fill the
existing bounded compiler/cache owners. It does not publish, bind, invoke or
modify application state.

Each candidate reports `ready`, `rejected`, `unavailable`, or `not-requested`.
An unavailable backend/admission context or bounded wait cannot establish
compatibility. Rejections expose only versioned closed diagnostic enum numbers,
optional exact numeric requirements and the trusted profile digest; no arbitrary
error strings are returned. Unknown enum numbers are preserved descriptively and
do not establish eligibility.

A ready report includes the actual selected profile, declared manifest budget,
engine version/configuration digest, target triple/CPU feature set, codec limits
and actual export contract/function tuples. `imports` lists actual callable
host/provider interfaces. `typeImports` lists actual validated resource-free
type-only interfaces; these do not require a callable provider binding.
`importCount` counts both lists, whose combined maximum is 64. There are at most
128 prepared exports. These lists come from the validated component surface,
not caller-declared manifests.

Component/package identities use canonical `sha256:<64-lowercase-hex>` values;
the original engine configuration identity uses
`blake3:<64-lowercase-hex>`. `sealedMetadataFingerprint` is the engine-owned
`lsf-wasmtime-preparation-metadata-v2` identity. It is distinct from a signed
artifact or raw contract-metadata document hash, and cannot be substituted for
one during package verification.

Normal CLI output uses the existing human/JSON envelope, with inspection fields
directly under `data`. Unsigned 64-bit values are canonical decimal strings;
absent optional values remain null, present zero remains `"0"`, and repeated
fields remain arrays. Machine clients use the same generated protobuf operation
and bounded native transport owners as the common client profile. The query
produces no synthetic activation, public HTTP header or operation receipt.
