# Vault KV-v2 secrets

The Linux x86_64 `vault-kv-v2-secrets-v1` adapter in `latent-vault`
implements `latent:secrets/reader@0.1.0`. It returns an explicitly selected
KV-v2 string field, its numeric version as a decimal string, media type, and
optional expiry. UTF-8 and explicitly configured canonical base64 decoding
are supported.

Installation uses trusted Rust composition: shared [provider pools](provider-pools.md),
`VaultConfig`, protected `ProviderCredential` bindings, a trusted `SecretClock`,
and `VaultSecretProvider::install`. Register the resulting invoker with
`ActivationCapabilityRuntime::install_secrets` and compile current capability
bindings for its provider reference. The current
[standalone provider configuration](../reference/standalone-providers.md)
has no Vault installation field; use the Rust embedding for this adapter.

## Endpoint and reference authority

One configured HTTPS origin uses explicit static peers and the existing
`HttpAddressPolicy`; TLS verifies the configured server name and selected trust
roots. The transport performs no ambient DNS, proxy discovery, redirect,
decompression or HTTP retry. A guest cannot supply a URL, API operation, token,
mount, field selector or namespace.

Each of at most sixteen `VaultReference` rows binds an exact tenant/reference
pair to a mount, path, field, optional positive version, encoding, media type
and optional operator expiry. The shared provider also requires a protected
credential binding for every configured tenant. Namespace, mount and path
segments accept bounded ASCII letters, digits, `_`, `-` and `.`, excluding
empty segments and `.`/`..`. Encoded separators and query/fragment injection
are rejected. The optional Vault namespace is a fixed operator header.

The supported API is `GET /v1/{mount}/data/{path}` with an optional
`?version={positive-integer}`. Version metadata in that response is validated.
Listing keys, arbitrary metadata APIs, writes, arbitrary authentication methods,
token renewal, and dynamic database/cloud secret leases are outside this profile.
See the [upstream KV-v2 API](https://developer.hashicorp.com/vault/api-docs/secret/kv/kv-v2).

`None` selects the latest remote version; `Some(n)` selects exactly version `n`.
A successful response must include a positive version and compatible KV
metadata. Destroyed or unavailable versions resolve to `not-found`; HTTP
401/403 resolve to `permission-denied`. Malformed, oversized, unsupported,
transport and capacity failures resolve to `unavailable`. No raw response text
is included in typed errors.

## Authentication, rotation and freshness

Tokens come from [protected local credential references](local-secrets.md),
scoped to the actual tenant, provider ID and origin. Token material is limited
to 4096 printable non-space ASCII bytes. It is resolved after provider queue
admission, including on cache hits. Tokens never become guest-readable secret
references merely because the provider can use them.

Explicit local-store reload controls token rotation. A private, zeroizing token
fingerprint binds cached values and pending disclosures to the currently
protected token. The fingerprint is not exposed in provider identities or
status. Rotation invalidates a pending copy made under different token bytes;
a fresh read cannot fall back to those cached values. Already-started network
work drains under its original finite owner and may have sent its old header.
Already disclosed guest bytes cannot be revoked.

Provider configuration epochs use the shared replacement contract. New work
requires a current binding/compiled plan. An accepted old operation retains
its original ownership until it finishes or is cancelled; explicit provider
`close()` also prevents pending disclosure. Configuration replacement is not
proof that old network work has physically ended.

The default cache freshness bound is five seconds, with a sixty-second hard
maximum; zero disables caching. Remote token revocation, KV updates and deletion
can therefore take up to the configured cache TTL to be observed on an existing
cache entry. Local credential expiry/rotation and original capability authority
remain independently checked. There is no stale-on-error fallback after expiry.

Operator expiry and scheduled KV deletion use both a Unix timestamp and a
derived monotonic deadline; observed expiry is sticky. Cache TTL is only a
freshness bound. KV version metadata never creates a renewable dynamic lease,
and a response claiming a nonempty lease ID, nonzero lease duration or renewable
lease is rejected. Missing version data is not invented.

Concurrent misses receive monotonically increasing local sequence numbers.
A late reply cannot replace or disclose an older result after a newer request.
Latest-version high-water marks reject remote version regression for the
installed provider. Restoring an older Vault snapshot intentionally requires
an explicit new provider configuration epoch.

## Resource ownership and disclosure

| Limit | Default | Hard maximum |
| --- | ---: | ---: |
| Reference rows / credential scopes | configured | 16 each |
| Selected decoded value | 16 KiB | 32 KiB |
| Raw JSON response | 64 KiB | 256 KiB |
| Retained plaintext and parser reservation | 1 MiB | 4 MiB |
| Cached values | 16 | 16 |
| Cached value capacity | 256 KiB | 512 KiB |
| Cache TTL | 5 seconds | 60 seconds |
| Authentication token | supplied | 4096 bytes |

The parser also limits depth to eight, nodes to 2048, collection entries to
64, and decoded keys to 128 bytes. Duplicate decoded keys are rejected. It
validates shape before selecting a field and does not build an unrestricted
JSON value tree. Only string values can become secret bytes.

Raw response/parser workspace and selected-value capacity are reserved before
allocation. Cache and active disclosure owners share the same plaintext
ceiling. Eviction or provider close cannot refund a value still held by a
disclosure. Cache accounting uses retained capacities rather than just logical
lengths. The provider's fixed metadata, TLS/HTTP state and protected token store
have additional shared pool charges; these logical bounds are not a whole-process
RSS limit.

Expired cache entries are reclaimed lazily during reads or by the trusted
`prune_expired()` operation; `close()` fences reads and clears available cached
owners. There is no per-reference cleanup or renewal timer. All retained owners
remain charged until destruction. No dormant deployment opens a connection or
creates a secret-specific task, thread, process or listener.

A remote read charges one outbound request; a verified cache hit charges none.
Selection determines this cost before original broker dispatch. A cache entry
that becomes stale after selection fails instead of silently issuing unreserved
network work. Queue, connect, TLS, response and copy stages share the original
activation deadline and cancellation. The shared pool's finite failure backoff
also applies; it does not cause automatic retries.

Immediately before canonical guest copying, the provider checks the original
call, current protected token, selected sequence/version, provider closure and
expiry. The result/lowering owner stays charged through guest Store destruction.
Provider-owned raw/decoded buffers and token copies use zeroizing owners. As
with local secrets, this is best-effort erasure of owned buffers, not a promise
to erase guest copies, allocator/kernel copies or all TLS/JSON internals.

Audit uses the broker's approved capability/request digest, configuration epoch
and finite `SecretResolved`/`Rejected` outcomes. Numeric selected versions are
returned to the authorized guest; secret values, tokens, value digests and raw
Vault diagnostics are absent from audit and health snapshots. `SecretResolved`
means provider resolution, not proof that guest code consumed the bytes.

## Validation

`tools/run_vault_secret_tests.py` owns a TLS Vault 2.1.0 dev fixture pinned by
image digest. It caps server memory, CPU, PIDs, temporary storage and logs, uses
only public synthetic credentials, and verifies container identity before
cleanup. CI reuses its already-built Cargo test harness. The fixture is not a
production Vault configuration or a benchmark.

```sh
cargo test --locked -p latent-vault --lib
cargo test --locked -p latent-wasmtime --test local_secrets --test vault_secrets
python3 tools/run_vault_secret_tests.py
```

The real-server tests cover guest reads, latest/exact versions, deleted/destroyed
versions, cache expiry, local rotation, remotely revoked tokens, TLS identity,
cancellation, outage and healthy reuse, dormant deployments and audit redaction.
Finite synthetic TLS tests cover malformed/oversized bodies, value limits,
evicted-but-retained owners, out-of-order replies and provider epoch replacement.

The adapter has its own workspace crate so the dependency graph remains acyclic:
Vault composes the HTTP transport and local credential store, while HTTP can
continue to test its protected credentials against `latent-secrets`.
