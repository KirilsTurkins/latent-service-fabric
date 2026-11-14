# Rust source-proof compatibility in the TypeScript integration branch

## Failure and scope

The general Rust CI for the TypeScript integration stack stopped in
`latent-component-threading`, not in the signed Fetch probe. At integration
base `d61c36d91837103a3349b4abad3755ecd9699ab4`, the all-feature library run
had 81 passing cases and four failures with
`rust-child-admission-reencode-failed` (or the enclosing verification assertion).

The parser/encoder source-profile update to 0.262.0 exposed a historical
intermediate representation: Rust root wrapping moves original allocator and
post-return bodies to appended function indices, but preserves their name-row
order. That order is no longer monotonic. The next transform's default name-map
iterator rejects it. Executable code validation is not the failing boundary.

Sorting the names is not a compatible repair. These derived bytes participate
in the complete authenticated component comparison. The normal and historical
catalogues, their fixed component images, and their expected digests must stay
unchanged; dependency rollback is also unnecessary.

## Implementation boundary

`rust_objects::derive_source_core_with_limits` uses a private admission entry
point only after authenticating the original object graph, deriving the fixed
wrappers, and checking the original root/System stack reservation. The public
`transform_owned_thread_admission` entry point keeps the ordinary strict parser.
There is no guest option or runtime profile flag selecting the private path.

Only function-name rows and the outer function indices of local/label maps use
the raw syntax-checked iterator. They retain their original row order and remap
only the same function referents as before. Each map has a fallibly allocated
uniqueness table bounded by the inspected original function count; duplicate
and out-of-domain indices fail. Inner local/label maps and all other name kinds
keep current parser checks. Truncated rows, integer overflow, incomplete maps,
and trailing data still fail. No executable-validation failure is converted
into admission.

The original preimage check, module-size limit, current executable validator,
fixed admission-body verification, raw-creation escape checks, and full component
byte comparison remain in force. The new bookkeeping is transient source-proof
work, not a guest activation allocation or a new accounting ledger. Runtime
qualification and canonical-creation receipt flags remain false.

## Regression evidence

Six focused regression tests exercise preserved function/local/label order and
referents, identical public/private results for ordered inputs, duplicate and
out-of-domain rejection, strict inner/other index spaces, malformed raw rows,
and unchanged preimage/executable-shape rejection. Existing complete normal,
historical, and combined-preview source proofs are exercised without editing
any golden image or expected digest.

Both local runs and repository-locked CI with Rust 1.97.1 completed with:

| Configuration | Result |
| --- | --- |
| Default library | 90 passed; no failures or skips |
| All features | 91 passed; no failures or skips |
| Combined preview without legacy catalogue | 95 passed; no failures or skips |

These counts describe observed executions; they are not an inventory gate.
The local all-feature negative control reproduced the original 81-pass,
four-failure result before the fix. Local execution used the source crate from
retained synthetic merge `4f7458d80bc72a9e92da8aae5fba777cb62134c7` in an isolated
workspace. The affected preimages match the integration branch. Its encoder
0.262.0 source was reconstructed from cached 0.261.0 and the two upstream file
changes, with both resulting Git blob hashes verified against upstream. This is
source identity, not a claim that the local crate archive had the registry
package checksum.

The independent [locked CI run](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/43245556205)
(job `131277130099`, 2026-11-12) downloaded `wasmparser` and `wasm-encoder`
0.262.0 from the registry using the unchanged repository lockfile. It checked
exact edit preimages and postimages, formatted the changed source, and ran all
three configurations successfully. It then pushed implementation commit
`9540f93f9213678ed2bcded4878caf4aa7447977` to
`feat/typescript-runtime-745` and removed the temporary repair workflow. The
executed source is the implementation committed at that revision; the run's
initial checkout was staging commit `6644e7471cd72fc2e992016a343bf17dab348c42`.

```sh
cargo test -p latent-component-threading --lib --locked
cargo test -p latent-component-threading --lib --all-features --locked
cargo test -p latent-component-threading --lib --features rust-http-combined-preview-diagnostic --locked
```

This repair removes a reproduced source-proof CI blocker. It does not establish
full workspace success, modified SpiderMonkey/Store lifetime qualification,
failed-decommit custody, complete quarantine ownership, physical cross-tenant
reuse, or completion of #745. No dependency pin, runtime budget, golden source,
or capability grant is changed.
