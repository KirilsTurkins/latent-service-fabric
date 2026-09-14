# Protected local secrets

The Linux x86_64 `protected-local-secrets-v1` provider implements the existing
`latent:secrets/reader@0.1.0` contract. A read returns bytes, media type, an operator
version, and optional expiry. The WIT function remains synchronous to the guest;
Wasmtime suspends its fiber while host admission or required auditing waits.
No host ABI source, digest, or package version changes for this provider.

Installation is an explicit trusted Rust composition step using `latent-secrets`,
the existing [provider pools](provider-pools.md), and
`ActivationCapabilityRuntime::install_secrets`. Ordinary standalone startup does
not infer secret sources from imports. Standalone provider configuration and
management remain the separate Phase 3 delivery in #226. The [Vault KV-v2 adapter](vault-secrets.md) reuses this protected credential store.

## Sources and filesystem trust

`LocalSecretStore::open` takes one absolute protected root, finite limits, an
explicit environment-key allowlist, and a trusted clock. It opens the root on the
pool's bounded control worker. `reload(expected_generation, specs)` reads every
source on that same worker infrastructure and installs the candidate only after
all reads and validation succeed. There are no file watchers or automatic reloads.

Each `SecretSpec` names an exact tenant/reference pair. Its file source is one
configured leaf under the root, with at most 255 ASCII letters, digits, periods,
underscores or hyphens; `.` and `..` are rejected. Guest references never become
paths or environment keys. Sources cannot be directories, FIFOs, devices,
symlinks, or hard-linked files.

The shared `latent-protected-files` crate supplies the reviewed ownership, mode,
ACL, and no-follow descriptor checks also used by
[node bootstrap credentials](protected-configuration.md). Secret roots additionally
retain their ancestor descriptors and verify directory and leaf identity before
returning a source. Removal, replacement, changed content/permissions, unsupported
ACL inspection, unreadable files, and oversized sources reject the candidate.
The root must exclude traversal outside the effective user/service group and
must not be group/other writable. Conventional roots use `0700`, with `0600`
secret leaves; deliberate root/service-group arrangements are supported.

The filesystem, kernel, root account, service identity, and selected service group
are trusted. These checks do not isolate secrets from a process with the same
authority, protect a compromised kernel/filesystem, or provide a transaction
across multiple independently edited source files. Operators must finish source
updates before reloading. Replacing the root or an ancestor requires reopening
the store. A successful reload retains the validated values; later source-file
edits or deletion do not change them until another explicit reload succeeds.

Environment sources use only explicitly allowlisted names from the kernel's
**initial process environment**. The loader verifies procfs and reads this process's
environment into a prepaid, zeroizing buffer with an overflow sentinel. It never
allocates an unchecked individual value through `std::env::var_os`. Duplicate
selected keys, missing names, malformed entries, an oversized snapshot/value, or
unavailable procfs fail closed. Environment mutations made after process startup
are not observed. Use file rotation or a new operator-controlled process
environment when changing such values. No environment import is installed in Wasm.

## Authorization and rotation

A raw read requires an exact tenant/reference/read grant, the installed provider
binding, current policy/publication authority, and the activation's existing
budget. A queued read checks authority after obtaining its provider slot and
selects the then-current material. A reference existing in another tenant does
not make it accessible. A cached value never bypasses authorization or expiry.

The initial material generation is zero. Reload uses an expected-generation
precondition and advances the generation monotonically. A failed or concurrent
candidate leaves the current generation unchanged; empty candidates revoke all
retained references. A material generation is separate from the provider's
configuration epoch. Source values, versions and expiry are never hashed into
the public provider identity. Adding a new raw reference to the installed
provider's authority requires a new provider installation and binding.

After required audit completion, a retained read checks cancellation, expiry and
the selected material generation again at the bounded guest-copy boundary.
Rotation before this boundary rejects that retained read with `unavailable`.
Already copied guest bytes cannot be revoked. Provider/policy revocation obeys
the broker's guarded dispatch boundary: newly accepted operations must use
current authority; a previously accepted operation may finish under that decision.

Expiry checks both the supplied Unix timestamp and a monotonic deadline computed
at loading. Once observed expired, that entry remains expired even if the wall
clock moves backward. Reload is the explicit way to install a renewed value.
`close` rejects new reads/reloads immediately; physically retained material stays
charged until its owners are destroyed.

The unchanged WIT error set contains `not-found`, `permission-denied`, `expired`,
and `unavailable`. Capacity, stale material, cancellation, deadline and other
provider failures use `unavailable` when a typed result can still be returned;
the activation may instead finish with the engine's interruption result. No
automatic retry is implied. Required audit reports `SecretResolved` for the
accepted provider resolution, not proof that guest code consumed its result.

## Plaintext and opaque credentials

`SecretPurpose::GuestValue` explicitly authorizes plaintext disclosure when the
read grant also permits it. The guest can copy those bytes into its memory,
outputs, logs or subsequent authorized operations. LSF does not erase arbitrary
guest memory on revocation or automatically sanitize guest-generated output.

`SecretPurpose::ProviderCredential` instead binds material to a tenant, logical
provider ID and exact HTTP origin. `bind_credential` produces a trusted opaque
provider object; it is never a guest-readable secret handle. Both buffered and
streaming HTTP support `install_with_secret_references`, with one configured
credential header per destination, at most 16 bindings, and at most 4 KiB per
resolved value. The header grammar, destination, provider, tenant, and current
material/expiry are checked. Guest headers cannot override it. Cross-origin
redirects strip credentials and never reintroduce them later in the chain.

HTTP resolves its header at request construction from the current generation.
It does not cache plaintext in a reusable client. A request whose header was
already constructed may finish with that value after rotation. The shared TLS
connection's destination authority remains independent of its request header.

Provider material uses private zeroizing owners without Debug or serialization.
Raw reads borrow the retained value only for one prepaid canonical copy. The
private host lowering DTO also wipes its byte vector when dropped. Audit and
status contain authority references, outcomes and counters, never value bytes or
a value digest. Zeroization is best effort: it does not promise removal from
kernel buffers, swap, crash dumps, TLS/HTTP library buffers, registers, arbitrary
allocator copies, or guest memory. HTTP header values are marked sensitive for
library diagnostics; that flag is not memory erasure.

## Finite ownership

| Store limit | Default | Hard maximum |
| --- | --- | --- |
| References, including all tenants and purposes | 16 | 16 |
| Bytes in one value | 16 KiB | 32 KiB |
| Retained bytes per material generation | 512 KiB | 1 MiB |
| Simultaneously retained/candidate generations | 2 | 8; minimum 2 |
| Initial environment snapshot | 128 KiB | 1 MiB |
| Allowlisted environment names | explicitly configured | 64 |
| Public version/media-type text | explicitly configured | 128 bytes each |

Generation byte charges include retained vector capacity and empty-file
sentinels. Generation metadata, candidate source buffers, environment capture,
root descriptors and opaque bindings also have separate prepaid pool metadata
charges. One reload can run per store. Outstanding reads retain their old
generation and can prevent another reload when the configured generation limit
is full. Capacity is never refunded merely because a waiter disappeared.

Control workers and their payloads remain charged until the actual work retires.
Dropping a reload future requests cancellation; it cannot stop an uninterruptible
filesystem syscall. Cancellation before the installation boundary leaves the
old generation intact. After installation, cancellation cannot roll it back;
inspect the reported generation if the original waiter was lost. A filesystem
with indefinitely stuck syscalls requires the deployment's external containment
and operator recovery rather than an unbounded replacement worker pool.

Guest results keep both call and canonical-copy reservations until Store
destruction. Repeated reads can therefore exhaust finite per-activation/provider
capacity. Dormant deployments allocate no secret instance, worker, socket,
listener, file watcher or execution state. The store and pool are shared node
resources, with bounded retained material.

## Validation

`cargo test -p latent-wasmtime --test local_secrets --locked` executes the
maintained [guest fixture](../../examples/local-secrets/README.md). It covers
allowed/versioned reads, denied names and provider-only values, tenant isolation,
rotation, expiry/clock rollback, stale reads, queue revocation, cancellation,
traps, cell reuse, audit redaction, environment capture, capacity and dormant
deployments. Shared protected-file tests cover ACLs, modes, links, descriptor and
ancestor replacement, FIFO rejection and bounded reads. HTTP tests use real
connections to check opaque header rotation and rejection after revocation.

Non-HTTP TLS credentials use the distinct `TlsProviderCredential` purpose and
`bind_tls_credential` path. The [NATS publisher](nats-events.md) checks the tenant,
provider and exact protocol/server-name/port destination; this cannot substitute
for an HTTP credential or authorize a guest read.
