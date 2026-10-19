# Varied Rust dependency graph qualification

The `dependency-matrix` job in Rust capsule authoring advances #683's varied
coordinates, feature and target selection, offline capture, resources and
catalogue-independence requirements. It reuses the same run's five identity
checked native products and observed companion packages. It does not compile a
second host runtime or grant application capabilities.

The programme generates two independent package-name/version families at run
time. Each has a `#![no_std]` core with binary resources, a transitive
`#![no_std]` library using `alloc`, and a normal `std` facade with UTF-8 resources
and a fresh-activation static-state check. A native-only dependency must be
present in the full graph and absent from the selected wasm graph. Each family
is captured twice: normal root/dependency defaults, then explicit root features
with defaults disabled, alternate dependency features and a changed local
`[patch.crates-io]` preimage. The old reviewed candidate must refuse the changed
graph. Missing and tampered transitive CAS objects must refuse before a compiler
is invoked; restoring their exact bytes must recover the original valid lock.

Normal Cargo authoring, resolve, exact lock review and offline component build
run through `rust_capsule.py` in a staged root containing only its declared
compiler recipe and manifest/deployment seeds. Optional qualification fixtures,
reference data, repository metadata and documentation are absent. The generated
coordinates must occur in neither those recipe bytes nor the pinned SDK bytes.
The compiler still requires the original SDK, toolchain and binding locks. There
is no production package-eligibility catalogue to replace with a fabricated
test file. The exact minimal recipe inventory and every actual build's recipe
inventory are retained and rechecked.

Outside originals are physically removed before each ordinary build. The second
explicit native authoring step restores only this programme's same owned source
fixture, changes the declaration, resolves and reviews it, then removes those
originals again. This follows the maintained distinction between native editor
operations that require manifests and offline compilation from captured CAS.

All four resulting components are separately signed, admitted and invoked on
the enforced node. Three non-ASCII/resource-dependent calls per component must
match its exact selected graph, including a warm repeat that requires fresh
guest state. A baseline greeting or an earlier graph's component cannot satisfy
these expectations. Exact publication/generation, zero outbound requests,
physical client reaping, provider idle observations and the existing tutorial,
fault and shutdown checks remain required. No deadline, capability, signing or
pass criterion is relaxed.

Run with the same-run public `rust-git-prepared` artifact:

```bash
python3 tools/qualify_rust_dependency_matrix.py \
  --prepared-qualification "$RUNNER_TEMP/rust-dependency-matrix-prepared" \
  --output "$RUNNER_TEMP/rust-dependency-matrix"
```

Focused Python controls verify source generation, exact inventories, real CAS
refusal/restoration, malformed/forged observations and the default-off Rust-only
selector. They do not execute Cargo, components or the node. Only the hosted
programme's successful source-bound receipt establishes the four signed runs.
This is dependency-library `no_std`/`alloc` support inside the existing `std`
component envelope; it does not claim an alternative freestanding component
runtime, private Git authentication, production publisher identity, clean-host
reproducibility or complete #683 acceptance by itself. Prior private-registry,
approved executable containment/recovery and reviewed three-stage watch receipts
remain separate evidence with their own source identities.
