# Bounded Angular renderer qualification

This executable Phase 3 #224 fixture supports
[ADR-0037](../../adr/0037-qualify-a-closed-angular-component-renderer-profile.md).
It builds real Angular 22.1.6 SSR and browser bundles, wraps the server in a
Component Model artifact, and exercises it in Wasmtime. It is an
operator-controlled qualification tool; node integration and package delivery
are #233/#234. See the [profile and evidence](../../docs/runtime/angular-renderer-profile.md).

Use Node 24.19.0 and the repository Rust toolchain. From this directory:

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run build
node node-candidate.mjs
cargo build --manifest-path ../../Cargo.toml -p latent-renderer-profile --locked
timeout 480 ../../target/debug/latent-renderer-profile dist/renderer.wasm dist/wasmtime-rendered.html
node hydrate.mjs /absolute/path/to/google-chrome
```

On Windows, use the `.exe` binary and an outer process timeout appropriate to
the shell. Compilation is intentionally outside the invocation fuel/deadline
boundary. Run this trusted fixture under a bounded operator/CI process, not as
an untrusted compilation service. Browser tooling uses an installed Chrome;
it does not download a browser or modify a signed-in browser profile.

`npm run build` executes only this checked-in recipe after an installation that
disables dependency lifecycle scripts. Angular's compiler performs full AOT;
the Angular linker and esbuild produce closed browser-target ESM bundles. The
server's optional `xhr2` import resolves to a deny shim. The component builder
disables all ambient WASI features and rejects any remaining component import.
Generated files live in ignored `compiled/` and `dist/` directories.

The native tool compiles once and creates a fresh Store for each render. It
records setup/render time, fuel and observed linear-memory growth, verifies a
reused-instance negative control, rejects undersized memory, and exercises
fuel, epoch, allocation, exception, result-allocation and callback failures.
Each failure is followed by successful SSR with a new module counter. Counts
reach zero only after Store destruction. The ticker is joined before exit.
No generated Wasm, bundles or bulk timing archives belong in Git.

`hydrate.mjs` serves the exact native-rendered HTML and client bundle through
Playwright's bounded URL fulfillment for `https://renderer.invalid`. It aborts
other URLs and verifies original DOM reuse, escaped input, a working Angular
signal click and absence of page errors. This checks hydration without claiming
LSF's pending HTTP ingress or browser-security integration.

`node-candidate.mjs` evaluates an alternative using one owned child at a time:
two requests in a retained module, a fresh child, a killed/reaped CPU loop, and
a 64 MiB ArrayBuffer under a 32 MiB V8 old-space setting. It records the actual
limitations instead of treating that setting or `node:vm` as a hostile-code
sandbox. The child program is fixed and trusted; it launches no descendants.

CI reuses its existing Rust build and cached npm downloads. It runs this proof
only for renderer/runtime/build-input changes and manual or uncertain changes.
The compact [retained observation](../../docs/testing/angular-renderer-qualification.md)
is feasibility evidence, not a production benchmark or T1/T2 certification.
