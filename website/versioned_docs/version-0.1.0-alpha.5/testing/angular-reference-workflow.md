# Actual Angular reference qualification

The complete maintained Angular reference workflow passed on Linux x86_64 with Node.js 24.19.0 and Chromium 153.0.8010.52. The [unaltered run 29 receipt](../evidence/angular-reference-2026-09-20/run-29.json) records real shared-ingress HTTP delivery, two separately observed Angular builds, signed publication, isolated native preparation, browser hydration that reuses the original server DOM, subsequent client navigation, scoped provider calls, denied authority and cancellation recovery.

The runtime binaries were built at `79c295f7c6fcf671c6724db7b08ff8311563a884`; the browser runner was at `9ba4c3fcc7a96c93bf9b2d16d95642baa387bbd8`. The intervening tracked changes affect only browser qualification and source-snapshot tooling/documentation, not runtime sources. Exact binary, compiler, Node.js, browser, package, source-snapshot, observed-build and immutable-asset digests are in the receipt. The receipt SHA-256 is `deebbe1adb9ab649341a7d4117383a895a0d870e65f967a995028544f0b888d1`.

## Observed behavior

- Public pages include success, declared application failure, allowed provider access and permission denial. Static assets are delivered before any renderer preparation.
- An anonymous browser receives a real HTTP 401 for authenticated content. Separate Alice and Bob browser contexts hydrate only their own server-projected content, including escaped `Alice<unsafe>` text. Both contexts retain interactive counters, exact client-asset digests and no direct node-catalog access.
- A pinned in-flight render survives canary promotion; the old browser retains its original revision and assets. Revocation, clean restart on the same ingress port, authenticated native-cache hits and rollback all pass.
- Three node incarnations stop cleanly and are reaped. The controlled provider peer is reaped, all four held requests close or release, 124 CLI process lifetimes complete, and temporary outputs are removed. The final node snapshot has zero active/queued activations and zero reserved CPU fuel and memory bytes.

This bounded run uses the shared Docker Desktop host. Reproducibility is explicitly **not checked** and dependency completeness is **declared-inputs-incomplete**. It does not certify full #239 resource coverage or the #240 Phase 3 gate.

## Retained attempts

| Attempt | Observed outcome |
| --- | --- |
| [25](../evidence/angular-reference-2026-09-20/run-25.json) | Failed browser hydration after rollback; restart and cache-hit checks had passed |
| [26](../evidence/angular-reference-2026-09-20/run-26.json) | Failed after diagnostic-only console observations accidentally entered the strict browser error list; corrected without changing the original page-error/asset checks |
| [27](../evidence/angular-reference-2026-09-20/run-27.json) | Public browser and rollback passed; Chromium reported its navigation exception for an actual HTTP 401, which the harness did not yet observe correctly |
| [28](../evidence/angular-reference-2026-09-20/run-28.json) | Actual anonymous 401 passed; account assertion incorrectly expected the raw principal instead of the maintained application's projected display name |
| [29](../evidence/angular-reference-2026-09-20/run-29.json) | Complete public/authenticated browser, provider, lifecycle and owned-cleanup workflow passed |

All raw bytes are retained with SHA-256 sidecars. No failed attempt is counted as a successful full run.

## Reproduction

Use `tools/build_angular_reference.py` for the maintained two-build application, then the ignored `phase3_reference_fixture::export_actual_angular_reference_fixtures` fixture export and `tools/run_angular_reference_workflow.py`. The runner requires the actual CLI, node, compiler, build fixtures, pinned Node.js, Chromium and installed toolchain paths. The framework and runtime support boundary is documented in [Angular builds](../component-development/angular-build.md); broader measurements remain in the Phase 3 resource methodology.
