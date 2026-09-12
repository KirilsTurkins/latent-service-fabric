# Isolated trusted-local AOT compilation

Phase 2 issue #150 adds a bounded compiler producer to `latent-wasmtime`.
`IsolatedAotCompiler` launches an approved one-job executable, verifies its input
and output, and returns locally authenticated native bytes with an owned memory
allowance. The child uses Wasmtime 47.0.3's safe `Engine::precompile_component`;
it never instantiates a guest or loads native output.

Persistent AOT storage and native loading belong to #151. Current runtime
preparation continues to compile portable components through the existing
Wasmtime path. This producer is a host API; it does not yet replace that path or
add an automatic node/CLI AOT cache.

## Host API and input authority

Create a `ValidatedAotProfile` from a validated `WasmtimeConfig`, configure a
`TrustedAotCompilerAuthority` with a protected local key, and construct
`IsolatedAotCompiler` with the absolute executable path, its approved SHA-256,
the profile, authority and `AotProcessLimits`.

`reserve` accepts a concrete `OwnedArtifactPreparationSource` and exact
`ReleaseDigest`. It obtains the catalog's current lifecycle/admission capability
and reserves resources before the fresh bounded fetch. The job checks component
bytes, descriptor, manifest, metadata and the retained capability. Missing
capabilities and different release associations are rejected. Enforced catalogs
retain their configured trust authority; trusted-local catalogs retain their
explicit local scope. A local artifact without an OCI package has an absent
package identity, never an invented digest.

```rust,ignore
let job = compiler.reserve(catalog_source, &release)?;
let cancellation = job.control();
// Run on an existing bounded blocking worker; this call owns the child.
let output = job.run()?;
let native_bytes = output.output();
let receipt = output.receipt();
```

`AotJobControl::cancel` signals the owner. Dropping an unstarted job starts no
process. The producer has no internal queue, compiler thread pool or dormant
service process. Its blocking operation can be owned by the existing fixed
compiler workers when #151 integrates native reuse.

## Exact compatibility and provenance

Private construction of `AotCompatibilityKey` binds:

- catalog scope, optional real package identity, component SHA-256 and size;
- the verified component metadata fingerprint;
- complete validated runtime/security configuration, actual target and detected
  CPU requirements;
- Wasmtime's actual engine compatibility fingerprint, measured from a real
  compiler-only engine;
- the exact host capability-contract digest;
- the approved compiler executable digest; and
- the versioned sandbox policy and its configured resource limits.

Human-readable CPU/compiler labels and caller metadata cannot substitute for
these derived identities. The compiler-only engine uses the runtime's relevant
code-generation settings without allocating runtime pooling resources. The
pinned Wasmtime feature configuration excludes parallel compilation; unexpected
thread creation is also denied by the sandbox.

The parent checks the configured executable and hashes the actual running
`/proc/<pid>/exe` before sending bootstrap data. It checks the child's actual
engine fingerprint and exact enforced-sandbox profile before sending untrusted
Wasm. Successful output requires exact framing, EOF, successful child exit and a
fresh check of the original release capability. A lifecycle or policy change
does not silently upgrade a queued job to a new capability.

## Linux sandbox

The implemented profile is Linux x86_64 with Landlock ABI 3 and seccomp.
Unsupported hosts, unavailable facilities and partial enforcement fail closed.
The child accepts only three directional pipe descriptors and one thread. Before
reading its bootstrap header, it applies finite hard limits and marks inherited
descriptors above stderr close-on-exec through the safe `close_fds` API, then
re-executes `/proc/self/exe`. This preserves its PID and exact executable image.
A private clean marker suppresses a second re-exec but still requires strict
descriptor inventory; it grants no enforcement capability. The fallback CLOEXEC
scan is fixed and bounded, and any descriptor left open causes rejection.

The child
sets a parent-death signal with a parent-identity race check, disables core dumps,
sets hard resource limits and enables no-new-privileges. These prerequisites are
checked again after trusted engine initialization.

Final entry completes its `/proc/self` inventory and personality checks before
setting and verifying non-dumpable state through `prctl`. Linux [changes proc
file ownership](https://man7.org/linux/man-pages/man5/proc_pid.5.html) when
dumpability is disabled, so doing this earlier prevents an
unprivileged child from reading its own personality. This order also preserves
the parent's earlier executable authentication. No untrusted component bytes
are read until dump protection, Landlock and seccomp all succeed; the final
filter forbids changing dumpability. The acceptance harness runs every child
probe without root credentials, including when its launcher runs as root.

Before receiving the component, the child installs a Landlock filesystem policy
with no allowed paths and a fixed default-deny seccomp policy. File opens,
networking, process/thread creation, further executable launches, privilege
changes and unrelated kernel interfaces are denied. Reads are restricted to
stdin; writes are restricted to stdout/stderr. Only private anonymous
non-executable mappings and required non-executable protection changes are
permitted. Executable mmap/mprotect, file mappings, pkey changes and remapping
are denied. A read-implies-execute personality is rejected.

No child scratch directory, cache, filesystem log, namespace or delegated cgroup
is required. All input/output uses bounded pipes. Existing native compiler and
library mappings remain executable. The sandbox does not claim to hide all host
metadata or isolate the kernel itself. The configured compiler binary, trusted
bootstrap and host OS remain part of the trusted computing base.

## Protocol and ownership

The executable is an internal worker, not a general-purpose CLI. Its fixed
startup arguments carry the parent PID, sandbox limits and input/output ceilings.
All numbers and argument counts are validated. `--worker-v1` launches the
bounded sanitation stage; `--worker-clean-v1` carries the same numeric arguments
after re-exec and repeats prerequisite checks. Neither mode can skip full
sandbox enforcement.

1. Parent authenticates the running executable, then writes a four-byte
   little-endian bootstrap length and at most 4,096 trusted bootstrap bytes.
   Child has already applied launch limits and checked clean descriptors before
   reading the fixed prefix. Dump protection is deferred until final entry,
   after the parent's executable authentication and the child's final proc reads.
   Direct descriptor I/O prevents read-ahead into later frames.
2. Child initializes the trusted engine and enters the full sandbox. Its
   readiness frame contains `LSFAOTR1`, the 32-byte engine fingerprint, a
   two-byte profile-ID length and the exact
   `lsf-linux-x86_64-landlock3-seccomp-v1` profile ID.
3. Parent checks readiness, writes an eight-byte component length and exact
   component bytes, then closes stdin. Child requires EOF before compiling, so
   extra input is not interpreted as another job.
4. Child writes an eight-byte native-output length and exact bytes, then exits.
   Parent accepts only complete bounded output followed by EOF and success.

The parent clears the child environment and owns nonblocking pipe I/O without
per-pipe threads. Diagnostics are fixed strings; panic details are suppressed.
The parent caps collected diagnostics. Cancellation, timeout, malformed frames
and compiler failures retain the child owner and resource reservations through
termination and reaping. A shutdown timeout does not report those resources as
already freed.

## Default bounds

Limits are independently validated and may be lowered. Byte allowances may be
exhausted before a job-count ceiling.

| Resource | Default | Hard ceiling |
| --- | ---: | ---: |
| Reserved/running jobs | 2 | 16 |
| Aggregate input allowance | 128 MiB | 512 MiB |
| Aggregate document allowance | 128 MiB | 512 MiB |
| Aggregate native-output allowance | 256 MiB | 1 GiB |
| Retained output owners | 4 | 64 |
| One component | 64 MiB | 64 MiB |
| One native output | 128 MiB | 512 MiB |
| One job deadline, including its unstarted reservation | 30 seconds | 300 seconds |
| Child virtual address space | 512 MiB | 4 GiB |
| Child CPU time | 30 seconds | 300 seconds |
| Child stack | 8 MiB | 64 MiB |
| Child descriptor ceiling | 16 | 64 |

The child address-space ceiling includes executable mappings, engine, input,
output and intermediate allocations; it is not an RSS metric. Process creation
is denied, so descendants cannot multiply that allowance. Core and regular-file
output limits are zero. Bootstrap and one output receipt are additionally bounded
at 4 KiB and 8 KiB respectively.

The parent's `maximum_metadata_bytes` controls acceptance/fingerprinting of
metadata; it is not a pre-decode heap ceiling. Encoded source reads are bounded
by `maximum_document_bytes` and the concrete repository's read bounds, and
decoding retains that repository's fixed validation limits. Producer allowance
counters do not represent all decoder allocations or measured process RSS.

`snapshot()` reports reserved jobs, input/document/native allowances, output
owners and their fixed metadata charge. `TrustedAotOutput` is immutable and
neither cloneable nor publicly constructible/deserializable. Its native allowance
remains charged until the actual output owner is dropped, even after compilation
and shutdown finish. Borrowing bytes does not release that ownership.

## Local authentication and #151

`TrustedAotCompilerAuthority` holds a nonzero 256-bit key in zeroizing storage.
Provision it outside the child and any replaceable cache. The producer does not
provision keys or trust keys supplied in packages or receipts.

Only the private completed-job path can seal native bytes. Its domain-separated
keyed-BLAKE3 authenticator binds the compatibility-key digest, exact native
SHA-256, size and configured compiler identity. Verification uses constant-time
MAC equality. Replacing native bytes and recomputing caller-controlled digests
does not establish authentic output. The bounded receipt is future storage
metadata, not a public constructor for `TrustedAotOutput`.

This authority is local to the configured host/key. It implies no publisher-key
reuse, distributed native attestation protocol or keyless trust. Authentication
also does not grant current release eligibility. #151 must check the current
catalog/trust/profile at the native-loader boundary, authenticate persisted
bytes before any unsafe loader call, and preserve runtime/active-use ownership
across eviction. Recovery, incompatibility and portable fallback behavior belong
to that integration. #150 introduces no native deserialization or unsafe-code
exception.

Source: [producer and process ownership](../../crates/latent-wasmtime/src/aot/supervisor.rs),
[worker protocol](../../crates/latent-wasmtime/src/aot/protocol.rs),
[sandbox](../../crates/latent-wasmtime/src/aot/sandbox.rs), and
[local output seal](../../crates/latent-wasmtime/src/aot/seal.rs).
