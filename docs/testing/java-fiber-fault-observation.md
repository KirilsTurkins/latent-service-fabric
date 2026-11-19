# Original Java fiber fault observation

## Retained signed failure

PR #2156 originally retained an unresolved signed Java failure in run
`44518163237`, job `135539652265`. Component preparation and mode 0 passed;
mode 1 failed with `GuestTrap: unreachable-code`. The 205/28 model and six-model
field-closure receipts passed before that failure, not the signed programme.

The temporary read-only, PR/branch-scoped workflow introduced in `a6c9069`
replayed this exact component without javac, TeaVM, compiler-model controls or an
emitter. Run `44534309764`, job `135595569073`, verified its original inputs,
compiled the unchanged Rust harness with the existing default-off
`java-checkpoint-gc-trap-diagnostic` feature, and reproduced the signed failure.
Mode 0 returned 42 and retired its Store/broker resources. Mode 1 trapped after
6,149,082 fuel with a 9,620,542-byte observed peak.

Artifact `14535637264`, SHA-256
`a2db6c5a19d74aae13bef08db999fb96ea1cdd8f761ea60c8c421c5df40c98e2`,
retains the original compiler receipt, verified-input receipt and numeric log.
The seven captured frames are:

```text
LSF-JAVA-GC-FAULT:0:883:13736115:1
LSF-JAVA-GC-FAULT:1:74:7005740:66
LSF-JAVA-GC-FAULT:2:37:16815:141
LSF-JAVA-GC-FAULT:3:263:10389855:12698
LSF-JAVA-GC-FAULT:4:262:10377021:351
LSF-JAVA-GC-FAULT:5:880:13732899:73
LSF-JAVA-GC-FAULT:6:900:13737659:3
```

The exact retained component's name section maps these through
`teavm_printString`, `ExceptionHandling.printStack`,
`ExceptionHandling.throwException`, `Activation.invoke` and dispatch/export
wrappers. This identifies the final uncaught-exception reporting path, not the
initial exception's cause. The observer's historical GC name is not evidence of
a GC fault. Closed ambient logging, strict wire validation, original successful
result expectations and physical-retirement assertions are unchanged.

The temporary workflow, its two contracts and dedicated staging helper/tests
were retired after collecting the evidence. A known-bad immutable component must not become a permanent success
gate for newly compiled guests. This removes neither the ordinary Java authoring
workflow nor its signed test. Its result still has to pass on the repaired guest.

Commit `a6c9069` retains the data-only verifier used for the observation.
It checked the original run/job/stages, artifact identity, whole-archive hash and
four member sizes/hashes. It staged only component, source, WIT and original
compiler receipt, and required the source to equal the checked-in fixture. It
refused missing, changed, duplicated and symlinked inputs. It neither compiled
nor executed the guest or rewrote a receipt into runtime qualification.
The original fixed archive expires on December 3, 2026; replacing it requires
reviewed provenance, not weakened bounds or hashes.

## Native linear-stack diagnosis and hardening

A separate unsigned replay of the unchanged retained main core with mock host
ports reproduced the same seven function-relative trap locations. It exposed an
`IllegalArgumentException` from the strict unit-result boolean decoder during
worker cleanup. The first queued-work settlement returned an allocation at
address 8 containing the invalid boolean byte 40.

In that local diagnostic, the native linear stack started at 613,760 with a
65,536-byte reservation, giving a floor of 548,224. Worker cleanup observed stack
pointers around 544,512, below that floor and inside the static-data/allocator
region. This is evidence of native stack overrun in the diagnostic execution;
mock imports do not establish original host-ledger or signed-node qualification.

Both guarded activation link paths now select `-Wl,--stack-first`. LLD places
this downward-growing stack before static data, so the observed kind of overflow
hits the linear-memory boundary instead of overwriting allocator state. The
stack remains 65,536 bytes and maximum memory remains 67,108,864 bytes. Ordinary
non-fiber compilation, optimization level, compiler identities, sealed source
checks, guest source and host resource ceilings remain unchanged. Both modified
link owners are already included in the source-bound compiler recipe, so their
change invalidates the previous prepared-input identity.

This is fail-closed stack-layout hardening, **not a claim that the original
signed programme now fits its native stack**. The underlying stack pressure,
all twelve signed calls and subsequent Java stages still need qualification.
There is no larger stack budget, silently accepted wire error or disabled check.

## Standalone layout witness

The small C/JavaScript witness is independent of Java and has no host imports.
It executes an in-budget frame returning 42, then an oversized frame. With the
old layout the oversized frame returns and changes static marker bytes. With
stack-first it traps and leaves every marker byte unchanged. Both builds use the
same 64 KiB stack and 64 MiB maximum memory.

Run explicitly from the repository root with Clang/LLD and Node installed:

```sh
out="$(mktemp -d)"
for layout in baseline protected; do
  extra=""
  if [ "$layout" = protected ]; then extra="-Wl,--stack-first"; fi
  timeout 30s clang --target=wasm32 -nostdlib -O2 \
    -Wl,--no-entry -Wl,--export-memory -Wl,-z,stack-size=65536 \
    -Wl,--max-memory=67108864 $extra \
    tools/tests/fixtures/java-linear-stack/probe.c -o "$out/$layout.wasm" || exit 1
done
timeout 10s node tools/tests/fixtures/java-linear-stack/observe.js \
  "$out/baseline.wasm" "$out/protected.wasm"
```

The local witness passed with Clang 17 and Node 22.16.0. That is native Wasm
layout evidence, not the pinned Java compiler cohort or signed runtime evidence.
Compiler-free recipe tests check both guarded link commands and unchanged
budgets; the existing non-fiber command preservation test also remains in place.

The development merge hold and stopped scheduled compiler-model qualification
are not lifted by this investigation or the layout hardening. Wasmtime 48.0.8
security remediation is separately tracked in PR #2187; no advisory exception is
introduced here.
