# Execution security profiles

Phase 3 #280 implements the node selectors defined by
[ADR-0026](../../adr/0026-require-explicit-execution-isolation-profiles.md).
`securityProfile` is an optional, exact string in `node.json`:

| Selection | Trust assumption | Required controls |
| --- | --- | --- |
| `local-experimental-v1` (default) | T0: operator-controlled workloads and preparation | Existing standalone validation; admission and isolated AOT remain explicit independent options. |
| `external-capsule-v1` | T1: hostile component bytes/inputs, trusted node, Wasmtime, host bindings, native loader and OS | Enforced package admission, protected credentials/trust policy/native key, exact Phase 3 ABI and reviewed Wasmtime 47.0.4 baseline, supported Linux x86_64 isolated compilation. |

The compiler and authenticated native-loading subprofiles are observations of
these controls, not additional node selectors. Unknown, null, future, provider,
renderer and fixed execution-host selectors fail. T2 process-compromise
resistance and T3 host/kernel or strong side-channel isolation remain unsupported.
The external profile still executes fresh Wasmtime stores in fixed in-process
cells; it does not certify production or hostile-multitenant deployment.

## Configure and verify

Start with the [standalone configuration](../reference/standalone-node.md),
its [enforced admission](../reference/package-admission.md) and
[isolated AOT settings](../reference/standalone-node.md#optional-isolated-aot-compilation).
Add `"securityProfile": "external-capsule-v1"`. Keep `supplyChain.mode` set to
`enforced` and supply the complete `isolatedAot` object. Omitting either is an
error; neither signatures nor a profile name supplies the other control.

```bash
./target/debug/latentd check-config --config /etc/lsf/node.json
./target/debug/latentd serve --config /etc/lsf/node.json
```

Both commands use the same [protected file policy](protected-configuration.md).
Raw in-memory JSON cannot claim that a credential file was checked. Unsupported
platforms fail instead of using the portable compatibility loader for T1.
`check-config` validates configuration, derived bounds and an existing profile
marker, then probes the actual approved compiler. It creates no catalog, cache,
listener or marker. It is not a dry run of catalog recovery, a grant of execution
permission or a certification that publisher policy will remain current.

The probe checks the executable digest and actual running child, sends only the
bounded compiler bootstrap, verifies the exact engine/sandbox readiness reply,
then closes pipes and kills/reaps its owned child. It sends no component and
signs or deserializes no output. Its monotonic deadline is the smaller of the job
timeout and 30 seconds; filesystem/kernel calls remain in the host TCB. Child
ownership lasts through termination and reap, including on failure. Normal jobs
repeat executable, sandbox, source and authority checks; a successful probe is
never a reusable native-loading proof. See the exact
[Landlock ABI 3/seccomp and hard-limit requirements](trusted-aot.md#linux-sandbox).

A successful check emits one bounded JSON line containing the selected profile,
T0/T1 class, admission mode, protected-file observation, guest/compiler boundaries,
host ABI, runtime version and target. It contains no credential, key, subject,
tenant, path or native proof. The closed
[report schema](../../schemas/node-config-check.schema.json) and
[selector schema](../../schemas/node-security-profile.schema.json) describe the
wire shapes; they cannot establish OS enforcement. Failures use the existing
fixed diagnostic/exit-code convention. Node inventory exposes the effective
`lsf.security.profile`, `lsf.security.admission`, `lsf.security.guest-boundary`,
`lsf.security.compiler` and `lsf.host-abi` attributes.

## Preparation and restart

The runtime factory requires actual enforced admission and native compiler
owners before constructing an external-profile engine or its workers. Local
embedding and Phase 0 constructors cannot bypass that requirement. The exact
selection participates in prepared/native compatibility identity, separately
from mutable tenant grants and credentials. Cold, warm, queued, synchronous and
persistent native-cache paths retain current catalog authority checks. There is
no in-process compilation fallback after a configured compiler fails.

Before opening a new external-profile catalog, startup persists and synchronizes
`dataDirectory/EXECUTION_PROFILE` with the exact bytes
`lsf-external-capsule-profile-v1` followed by LF. Descriptor-anchored creation uses
an exclusive regular file, protected ancestors and a data root that is not group
or other writable. New directories use mode 0700 and the marker uses 0600.
Existing markers must be regular, single-link, protected and exact. Symlinks,
unexpected files, corrupt/truncated content and unsafe permissions fail closed.
`check-config` only reads this requirement. The local profile refuses any marker,
so omitting the selection during restart cannot weaken an external catalog.

There is no configuration reload API; changes require a checked restart. Preserve
the marker together with catalog, admission-generation and clock-floor files in
backups. A crash while first writing the marker can leave startup deliberately
blocked; stop the node and restore a verified complete backup before retrying.
Do not remove the marker to recover under a weaker configuration. Protection
against a privileged operator deleting or rolling back all local storage requires
an independent authority and is not provided by this marker.

## Finite evidence and remaining boundaries

The following reusable checks form the compiler/profile portion of the Phase 3
#238 adversarial matrix and #237 operational guidance. They run on small fixtures
in normal CI. They establish the listed properties, not universal absence of
compiler or sandbox defects.

| Check | Boundary exercised |
| --- | --- |
| `config::tests::security`, `config::isolation::tests`, startup AOT test | Exact selectors, protected-input provenance, unavailable constructors, changed compatibility identity, marker corruption/links/permissions, no fallback or storage creation on failed readiness. |
| `tools/run_security_profile_workflow.py` | Real protected files and approved compiler; rejected check/start configurations; three authenticated Invokes through cold, warm and restarted nodes; observable controls, unchanged storage after checks, downgrade rejection and clean process shutdown. |
| `standalone::start::tests::trust_currentness` | Actual signed packages; malformed package, changed digest, absent publisher proof and wrong-tenant rejection before valid admission; production isolated compiler, readiness child reap, queued/synchronous cold and warm preparation, persistent native reuse after complete reopen, proof expiry, policy expiry and publisher revocation cutting off retained work. |
| `aot_supervisor` | Six readiness outcomes plus 16 retained supervision scenarios: fragmented/malformed readiness, output/diagnostic limits, crash, cancellation, deadlines, active shutdown and kill/reap before refund. A real unrelated guest returns while a compiler is hung and after cancellation/reap. |
| `aot_sandbox` | Actual restricted child entry, denied filesystem/network/descendants, descriptor closure, address-space exhaustion and executable-mapping restrictions, including the exact syscall policy. |
| `isolated_aot`, `native_aot_cache` | Bounded malformed/source inputs, executable mismatch, queued cancellation/revocation, exact native-key/engine binding, tampered output, owner retention and cache recovery. |
| Protected-file, packaging and signing suites | Descriptor/ACL/ownership policy; bounded JSON, component, package, evidence and signature validation before compilation. |

Compiler CPU/address-space limits cover the child only. Parent-side parsing,
signature verification, catalog metadata and native loading retain their separate
byte/work/owner bounds. Guest Store limits do not bound all Wasmtime/embedder
allocations or node RSS. Native deserialization remains a synchronous trusted
node operation. Provider/renderer containment, cross-capability isolation and
Phase 3's integrated completion evidence remain assigned to their owning tickets.
Dormant deployments acquire no process, thread, listener, compiler or guest state.

The [Angular renderer qualification](angular-renderer-profile.md) evaluates a
closed Component Model candidate and a Node compatibility host against these
trust classes. Its T0 fixture does not add a node security selector or certify
T1/T2 support; enforced admission, isolated compilation and the production
renderer adapter remain separate gates.
