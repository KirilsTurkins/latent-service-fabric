# Angular patch dependency reconciliation

PR [#982](https://github.com/KirilsTurkins/latent-service-fabric/pull/982)
includes the useful compiler, browser and server updates from
[#983](https://github.com/KirilsTurkins/latent-service-fabric/pull/983) and
[#984](https://github.com/KirilsTurkins/latent-service-fabric/pull/984).
Their bodies and comments were checked; none references an issue to close.
The prior delivered #935 source (`0e258bc167449bdaf631f0e83b135aee73fc6e4e`)
was merged normally before this dependency update.

The installed renderer's seven existing Angular packages now use 22.2.1
together. The published npm manifests require that exact version of their
Angular peers. The authoritative npm 12 lock regeneration and clean
`npm ci --ignore-scripts --no-audit --no-fund` succeeded without peer bypass
flags. No non-Angular lock entry changed. The profile and current input
documentation identify the new patch; historical qualification records retain
their original identities.

Node 24.19.0 built the actual Angular AOT SSR/client bundles and the import-free
24,702,665-byte component. A native renderer rebuilt from this source used
Wasmtime 48.0.5 and the new profile digest. All ten original failure probes,
fresh Store recovery, instance reuse rejection, undersized memory rejection
and final zero live Stores passed. The original 2 billion fuel, 256 MiB memory,
128 KiB hostcall and callback limits remain unchanged. Real Edge 155.0.4283.45
hydration of its native-rendered HTML passed DOM reuse, escaped input, signal
click and zero page errors using the original browser assertions.

The 98 CI-contract, security-baseline and native-loader controls passed on
Linux. The 33 Angular-package/profile controls passed on Windows with one
existing symlink-privilege skip; that exact selected-link control passed on
Linux. Foundation and CI command coverage also passed (88 baseline and 284
current run blocks, 151 delegated owners). Earlier Windows symlink-privilege
failures and the first cached
renderer run remain in local evidence; final native evidence uses the rebuilt
tool and matches the new profile. Compact artifact identities and observations
are retained in [the packet](angular-dependency-reconciliation/2026-10-12.json).

The publication, renderer and security workflow assertions and selectors are
unchanged. These bounded checks establish the dependency update's renderer
behavior; they do not replace hosted publication/runtime lanes or reopen any
historical qualification claim. Close #983/#984 as superseded only after #982
is accepted and its combined source is retained. This PR closes no issue.

The subsequent normal merge of #935 at
`f8f6b9e7be94559bd5c81f0d019bd5f3299aa56f` retains the regenerated command-floor
descriptor golden, all six client models and the Node descriptor. The 25
descriptor/transaction-surface controls, pinned Buf 1.72.0 golden validation,
current six-language generation check, foundation and CI command coverage
passed on the merged source. The Java workflow and its reviewed contract
already agree; all processor, lifecycle, value and diagnostic commands remain.
The renderer/browser packet above records the earlier Angular qualification
source and was preserved unchanged; it is not a rerun of this later merge.
