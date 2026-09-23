# C capsule authoring implementation journal

This is developer validation evidence for issue #545, not the newcomer guide.
Start with [C capsule authoring](../component-development/c-capsule-authoring.md)
and [C ownership](../component-development/c-ownership.md) for supported commands.

## Boundaries established

The implementation compiles actual C source against the pinned WIT-generated
bindings, validates its real component, derives typed contracts from the resolved
WIT, captures actual source/tool identities, and uses existing package, SBOM,
publisher, builder, tenant and deployment admission. No local observation is
called an authenticated builder attestation. No ambient filesystem/network WIT
or grant constructor is added. The C client SDK remains a different product.

All nine capability profiles share their WIT and runtime assertions with the
Rust peers. Native ownership tests compile against actual generated headers,
with only host imports supplied as test doubles; real signed runtime tests are
separate evidence. The node walkthrough starts distinct authenticated CLI/node
processes and publishes the actual newly compiled teaching packages.

## Problems found by execution

1. The initial hosted runner's Python did not match the existing owned-build
   process requirement. Pinning Python 3.13.5 fixed this without removing the
   guard. Compiler/generator versions and executable identities remain checked.
2. Current buffered HTTP and streaming HTTP can coexist under version-qualified
   generated C names. Aliases now derive only from actual generated declarations,
   and every capability/profile lock detects changes. WIT identity is untouched.
3. Generated aggregate cleanup omitted certain aliased nested lists/options.
   Explicit result visitors now clean HTTP bodies/headers/options, all three
   service outcomes, streaming metadata and secret version/media/bytes. Native
   allocation tracking plus AddressSanitizer/UndefinedBehaviorSanitizer verifies
   ownership, double-close behavior and zeroization before free.
4. Debug sections dominated the first small reactor builds. Explicit release
   debug stripping reduced the teaching components to approximately 3.3–4.1 KB;
   this is observed output size, not a general compression/performance promise.
5. The signing exporter initially missed shared test support and used the wrong
   release-digest accessor. Actual Rust compilation exposed both mistakes.
6. Copying the echo deployment left its unlimited wall-time request wider than
   the authored manifest's finite 5000 ms. Real deployment admission rejected it;
   the exporter now requests the same finite ceiling. Admission was not weakened.
7. The walkthrough initially reused an exclusively created input filename. It
   now creates a distinct owned input for each invocation, with a regression
   test; exclusive-file semantics remain intact.
8. Status topology uses the stable lowercase `service-resident` and
   `activation-scoped` vocabulary. The final assertions check presence and zero
   counts, with negative regression tests, rather than passing on an unmatched
   uppercase suffix or empty inventory.
9. One generator download returned an upstream HTTP 500. Retrying the same
   verified installer succeeded; no checksum or release identity was bypassed.
10. The complete first teaching walkthrough passed before a subsequent rustfmt
    check rejected import ordering. A successful execution step is not presented
    as an entirely green workflow. Formatting and lints are separate gates.

## Executed witnesses before final integration

On September 23, 2026, [run 35869949352](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35869949352)
passed the actual paired C/Rust signed guest suite and exact builder-policy
profile tests. [Run 35873136590](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35873136590)
passed native ownership sanitizers, fresh project builds and current binding
identity qualification. The per-run source SHA is authoritative; later source
edits require qualification again.

In [run 35875490990](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35875490990),
all 20 teaching calls passed through the authenticated separate-process node:
successful UTF-8 and full-width integer results, declared application errors,
malformed wire inputs and successful reuse after errors. All three deployments
were removed; the node reported clean teardown and was reaped. The workflow then
failed its formatting step, not the teaching scenario.

| Project | Observed component bytes | First CLI invocation, microseconds | Deployment apply, microseconds |
| --- | ---: | ---: | ---: |
| greeting | 3605 | 122239 | 65678 |
| word-count | 3368 | 106595 | 30044 |
| shipping | 4110 | 121940 | 30003 |

That run recorded startup at 36001 microseconds and subsequent CLI calls around
14.5–20.2 milliseconds. These are single-run CLI/control end-to-end observations,
not guest CPU, isolated cold-prepare benchmarks, percentiles or production SLOs.
Whole-node RSS was 55,218,176 bytes initially and 76,640,256 bytes after removing
all three deployments. This includes node runtimes, allocator retention and the
shared compiled cache, not just C linear memory. The templates' 4 MiB linear
memory ceiling is a different measurement.

At final idle in that witness, the shared cache retained three entries with
11,083 source bytes, 80,912 compiled-image bytes and 83,619 metadata bytes. The
single execution cell was available, with no active/queued activation or quota
reservation. Service-resident processes, threads and listeners were zero. The
clean shutdown record independently reported no live stores, instances, host
states, buffers, cancellation probes, leases or quota reservations, with owned
workers joined. Cache retention is not falsely called zero idle memory.

The final required contracts gate repeats qualification on its actual checked-out
source and retains `target/contracts/c-authoring/qualification.json` and
`node-receipt.json`. It additionally builds a separate fault capsule for actual
trap, bounded linear-memory exhaustion, fuel termination and fresh guest state
after failures. Those cases are not copied into user templates. Cancellation,
async returned-result races and deadline propagation also remain covered by the
native state-machine and signed capability tests. A missing or failed receipt
is a failure, not an absent-means-passed observation.

## Review and remaining profile limits

A newcomer review remains a merge review gate: use new output directories,
create a project without editing a fixture, change a WIT signature, observe the
stale binding-lock rejection, implement the regenerated C export, rebuild and
run the documented node path. The reviewer should be able to explain source
repository assertions, separate publisher/builder approval, exact publication
selection, grants and retained-frame cleanup. Record the actual reviewer and
result on the pull request. Automated execution is not human review sign-off.

The initial qualified authoring host is Linux x86-64. The project metadata
adapter requires one source file per versioned WIT package and supports its
explicit primitive/list/tuple/option/result/named record/variant export profile.
Enum/flags/future/stream and resource-valued application exports are explicitly
rejected for this initial profile; resource-valued platform imports are supported
through the generated ABI. C ownership guards are non-copyable by convention,
not a language-level memory safety proof. A secret helper wipes its owned bytes,
not arbitrary application copies or registers. Host teardown, not a callback
after invalidation, contains a fatal trap.

Build observations retain conservative non-hermetic, incomplete declared-input
and not-checked reproducibility claims. Compiler caches/sysroots are not a proven
closed build environment. The events test uses a bounded TLS protocol peer; it
is not evidence about live external broker availability. The measurements above
are not a density/load campaign. No new per-service runtime, sidecar, listener,
thread, execution pool or warm resident guest is required by this implementation.
