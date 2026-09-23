# Standalone Go capsule qualification

This is developer evidence for #547, separate from the beginner
[Go authoring guide](../component-development/go-authoring.md). Completion
requires the complete real-node and printed-guide gate at the final PR head.
No partial observation below authorizes a release or replaces human newcomer
review #345.

## Compiler and implementation decisions

The selected profile pins componentize-go 0.4.3 at
`148dba505f8c6c64ad84db777cfde5e34e25098b`, its bindings generator at
`4f9a02d74cec9257c14ba9b160fa787a3523fd0b`, Go 1.27.1 with the `wasiOnIdle`
async scheduler patch, and wasm-tools 1.254.0. The Linux compiler archive is
verified against `4b4fcbbab5b5b0a45433112aa51c64a54007b24f1efd05b67018ca2cf8633e2c`.
The exact reviewed Go module is included in every editable project; generated
imports and exports come from the authoritative staged WIT, twice, with exact
binding-drift rejection. Ordinary stock Go and TinyGo are not this profile.

The retained upstream probe compiles the current host ABI, including async
imports and exports. Its ordinary adapter imports ambient WASI; that result is
not deployable in LSF. The selected source overlay checks the exact runtime
preimages, keeps the maintained scheduler, and forwards clocks and entropy to
explicit LSF imports. The composed component is rejected if ambient WASI
imports remain. No GOROOT or shared module cache is edited. The compiler probe
checks UTF-8, embedded NUL, full-width signed/unsigned integers, records, lists,
results, traps and fresh state. It is not signed admission evidence.

The SDK exposes eight typed capability families with explicit affine owners.
Aliases share consumed/borrowed state; pending owners cannot be reused, and
terminal calls invalidate them even on failure. No finalizer, retry worker or
background drain substitutes for explicit release. The fixed four-goroutine
recovery example exercises scheduler/channel reclamation under whole-Store
fuel, wall-time, memory and cancellation bounds. Dormant deployments retain no
guest heap or Go process. Read the SDK's
[supported-language boundary](../../sdk/go-guest/README.md#ownership-concurrency-and-cancellation)
before choosing dependencies or host APIs.

## Retained implementation validation

[Run 35921398035](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35921398035),
PR head `7753d224080d5ff87cac89dc27ebb5744a4e77f0`, built all five standalone
projects and nine actual Go capability components. All ten admitted
provider/ownership cases passed in 153.52 seconds: buffered/streaming HTTP,
blobs, secrets, events, local services, randomness, metrics, signature checks
and cancellation cleanup. Its source-input receipt is
`sha256:b5d59fa0879afc90ca4157e483f411acae41897e714dd27fedfac4334cea014f`.
These successful stages are not complete ticket qualification.

That run reached enforced admission, rejected the unsigned package, published
the signed packages and deployed four of the initial five. Preparing the fifth
deployment exceeded the finite admission clock lease while checking several
distinct packages. The retained control result is explicitly uncertain;
read-only receipt lookup remained unknown and complete audit pages were
retained. No mutation was retried or treated as successful. Authenticated
managed preparation now renews the same finite durable lease before each
distinct package read. Each read still occurs once, failures publish nothing,
and all grant/currentness checks remain at commit. Invocation, recovery,
historical replay and cache reads do not receive this control-only renewal.
A deterministic regression covers renewal failure before the second read,
unchanged durable bytes, no retry and cancellation of the private preparation.

Earlier failed runs remain evidence: [35918139823](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/35918139823)
passed nine SDK cases but the child service lacked its own exact-principal
clock grants. The fixture now scopes those grants to the child publication and
service identity, without changing production authorization. Other retained
attempts identified runtime entropy input charges, secret-owner pending counts,
and cold child compilation exceeding an explicitly short test budget. Correct
ownership accounting and finite profile budgets replaced those assumptions.

The new node/guide run and measured startup, active memory, cache, dormancy and
cleanup results remain required. Only `qualification.json` with `status:
passed`, complete node/guide receipts and successful exact-head CI may approve
merge. `BUILD-COMPLETE.json` and `SDK-BUILD.json` alone cannot do so.

## Reproduction and delivery boundary

Install the exact Linux tools from the beginner guide, then use a fresh output
directory outside the checkout:

```sh
python3 tools/qualify_go_capsules.py --output /tmp/my-fresh-go-qualification
```

The gate retains source inventories, actual build observations, generated
bindings, package inspection, all owner tests, signed enforced-node receipts,
27 completed node cases, active/idle resource samples, 5/9/17 dormant
populations and the six unchanged printed Bash steps. Failed attempts retain
`QUALIFICATION-FAILED.json` and bounded logs. CI also archives its exact source
and command-contract input. Final PR and issue comments bind the successful
receipt to the exact Git source and merged revision.

This is finite single-node experimental qualification, not 100k-scale sizing,
throughput, transactional state, clustering, a complete transitive SBOM or a
hermetic/reproducible build claim. Source repository labels are operator
assertions. All six authoring tickets, the Phase 3 gate and human newcomer
review remain separate; runtime release publication stays on hold pending
explicit maintainer approval.
