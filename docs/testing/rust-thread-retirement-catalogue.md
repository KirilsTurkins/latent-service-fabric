# Rust root-retirement catalogue integration

This continues the [root-drain notification repair](rust-thread-root-drain.md)
on PR #1371. It does not qualify signed ThreadPool execution or close #743 or
#689. The original guest, grants, 32 MiB/five-second limits and eight Native
owners remain unchanged.

## Authenticated original inputs

Compiler run [41219448914](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41219448914)
at `72707ee61ce4784f7c866f2835f474554df8d922` passed 34 native controls and the
emitted guard/dispatch controls, built the repaired sysroot and unchanged
application, then refused the previous catalogue before normal encoding and
the mandatory 76 library controls. This remains failed compiler evidence.

Its retained artifact `13049262956` is 52,711,306 bytes with 116 members and
SHA-256 `1fb393cb5c05aa72852be342449bb0c12cff6923f32f76c79af6ac18f953c5ca`.
The original core is 261,403 bytes with SHA-256
`8cd26a5f34ec90f23af43dfcb21b0b619b369ed2199a5368a24572bb96cbf177`.

The unchanged parser independently reproduces the complete saved graph from
all 15 actual Rust libraries. There are 1,221 definitions, 5,246 references and
11 roots, without unresolved referents, body mismatches or decode failures.
Compared by unique function symbol with actual relocation spans separated,
only `executor_root::progress_all` changes nonrelocation function bytes. Its
body grows from 1,389 to 1,407 bytes and has exactly one direct call to
`executor_root::changed`, at relocation offset 816. Compiler object placement
also changes, so the complete graph is regenerated rather than hand-patching
one index. No reference is omitted or accepted as an arbitrary relocation.

The complete original-body image is 176,189 bytes with SHA-256
`eca9883441a2e8ef0b4ea721c53932866d117503382c6e8805cb7d7661fd1b8b`.
Both native and Python catalogue checks require exactly 5,246 references.
The existing native tamper control additionally requires the unique original
notification edge; every previous body/import/global/dispatch mutation remains.

The temporary read-only source export and subsequent exact-blob reproduction
were review transport only. Hosted review run
[41229626101](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/41229626101)
verified all 239 source identities against immutable Git source `72707ee`,
reobserved the full graph and produced ten files identical to independent local
Python generation. Artifact `13052882748` has SHA-256
`39d05789f283693344a36c1519a6526e6164beff1eb06c84a79ef2345350f3f2`.
Only pre-reviewed blob hashes were stored; no workflow changed a branch ref or
promoted signed origins. The temporary workflow and helper are removed by this
integration; no automatic catalogue generator is installed in the runtime.

## Source-projected component, not an encoder receipt

The retained synchronous core plus the existing public-WIT metadata adaptation
produces the 247,234-byte source core with SHA-256
`e976d80b529cdc91e5a6f2255d4aeb8db6412a690b039578c75a7dbd76363c22`.
All 18 imports preserve their identities, signatures and order. The existing
4,422-byte encoder shell, adapters, producer merge and consumed WIT metadata
are unchanged. Applying the same projection to the previous compiler core
reconstructs its actual hosted normal component byte-for-byte.

The candidate current normal component is 250,281 bytes with SHA-256
`0d66c4828a608e9ec0048205ac6f38539e417f62dbdaeb6b7bdc245aa1c073c8`.
This is a source-projected expectation, not fabricated hosted encoding. The
origin manifest explicitly keeps `hostedConfirmation`, native proof and all
runtime qualification flags false. Its `beforeRootRetirementRepair` object
preserves the complete previous origin without rewriting historical outcomes.
All previous receipt assertions remain, alongside exact new candidate checks.

Twelve focused Python catalogue/graph/callback/result checks pass. The existing
compiler owner must now independently derive the native core, run the actual
encoder, verify the normal component and pass all 76 library controls. Its
strict shell and recomputed-main comparisons are unchanged. The ordinary native
producer also runs on this runtime branch, retaining its original 200 controls
and 91 stages; successful output is not selected by the signed consumer until
its exact source, event, artifact and product identities have been reviewed.

The old signed compiler/native inputs remain unchanged in this integration.
A matching producer and all five successful signed calls with physical
retirement/accounting evidence are still required. Merge conflicts and broader
issue acceptance criteria are not resolved by source fixture integration.
