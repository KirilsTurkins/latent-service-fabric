# Renderer dependency handoff

Source fix: `3a49274dcd381c0d79a85ba58db5b611365c9376`, following the consolidated dependency staging source `09d21a96638ad8dfec4a93dace6f9fed258174f1`. This branch is a durable handoff ref for the existing #802 delivery. It has no separate pull request.

The original locked install succeeded, but componentize-js 0.23.0 could not resolve its bare Preview 2 shim import after jco 1.35.0 placed the shim in nested dependency folders. The fix declares exact `@bytecodealliance/preview2-shim` 0.26.0 at the renderer root and records componentize-js's actual 0.23.0 version. The weval 0.5.0 override and every existing execution/profile bound remain unchanged. The lock change hoists the same shim version without changing other package versions.

The corrected clean locked install, Angular AOT/bundles and Component Model build passed. The 24,563,333-byte component has no imports. Wasm-tools 1.254.0 validates it; jco 1.35.0 transpiles it and executes two actual Angular renders with call counts `[1, 2]`. The production adapter's private renderer also builds and validates. Fourteen maintained renderer/security cases passed with one original Windows symlink-privilege skip. CI inventory validation preserved 88 baseline commands, 275 current required blocks and 143 delegated owners; this is local inventory validation, not hosted CI.

The build ran under owned process deadlines (360 seconds for install/main build, 180 seconds for transpile, 300 seconds for the private component, 90 seconds for actual render), a 1 MiB output limit and Node's 2 GiB old-space limit. The old-space setting is not a total-memory or hostile-code sandbox claim. Files were built before the source fix was committed; the preserved source digests bind the identical committed bytes.

Original failure metadata is retained separately from passing observations. This public handoff contains only versions, digests, bounded outcomes and the closed missing-package reason. It contains no credentials, private stores, raw environment or bulk generated artifacts.

No new native Wasmtime execution, browser hydration, installed-bundle, signed admission, T1/T2 or release qualification was performed. Docker was unavailable. The immutable native renderer compatibility identity still includes its existing componentize-js 0.22.0 token; this boundary and the stale current runtime guide version table were reported to the coordinating agent without changing them in this follow-up. Existing original/private evidence remains in the local handoff evidence directory and is not published here.
