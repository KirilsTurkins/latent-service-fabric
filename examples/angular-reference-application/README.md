# Angular reference application

This is the maintained application for [the build-to-browser delivery
ticket](https://github.com/KirilsTurkins/latent-service-fabric/issues/236).
It uses the pinned Angular 22.1.6, TypeScript 6.0.3 and Node 24.19.0 build
toolchain in [the renderer profile](../renderer-profile/package.json).
The resulting component is the server, not a resident Node.js process.
Actual protected native preparation and browser acceptance are separate gates;
a successful package build alone does not authorize execution.

## Build

From the repository root, with the repository's pinned Rust, Wasm, JavaScript
and Python tools installed and the renderer profile's locked dependencies
restored, build `latent` and run:

```sh
python3 tools/build_angular_package.py \
  --input-root examples/angular-reference-application \
  --toolchain-root examples/renderer-profile \
  --cli target/debug/latent \
  --target-root target/angular-reference \
  --output target/angular-reference/build01 \
  --cargo-target-dir target \
  --repository https://github.com/KirilsTurkins/latent-service-fabric
```

Use a fresh output directory. The builder records the application, toolchain,
component, client files, provenance and SBOM identities. Publication must use
that exact output and the separately configured publisher and builder trust.
Never turn `trustEvaluated: false` or `executionAuthorized: false` from local
inspection into an admission claim.

## Routes and authority

| Route | Contract |
| --- | --- |
| `/`, `/about` | Public SSR, Angular hydration, counter and Home/About navigation |
| `/account` | Account content only for the runtime-sealed `user` principal; public-origin requests are not authenticated users |
| `/failure` | Declared application failure with HTTP 422, not a runtime trap |
| `/data` | One broker-mediated GET of `http://127.0.0.1:19090/message` |
| `/denied` | GET of port 19091, outside the reference binding's allowed origin |
| `/slow` | GET of `/slow` on port 19090 for activation cancellation and recovery |
| `/offline` | Prerendered asset, with no renderer activation |

The selected [scoped HTTP backend profile](../../docs/runtime/angular-backend-profile.md)
requests one asynchronous provider call; it does not grant that call. An
operator must configure a consumer binding for `angular-reference`, allowing
only the owned port-19090 backend. The runner must own and close the fixture
listener and refuse an already-occupied port rather than use an unrelated
service. No provider credential is accepted in application source or browser
state. Only a bounded JSON `message` field is projected into public hydration;
other backend fields are discarded.

Home/About navigation uses Angular component state and the browser History
API, not an Angular Router dependency. Modified link clicks retain normal
browser behavior. The server renders each route before JavaScript runs, and
hydration is required to reuse that DOM rather than replace it with CSR.

## Qualification status

The observed Linux build succeeds with the scoped backend component and all
six client/prerender outputs. Both adapter feature builds and all 13 focused
Python build/profile tests pass on Linux without skips. These results do not
yet establish signing, T1 admission, live provider authorization, browser
hydration, canary/rollback, cold/warm costs or zero-idle reclamation. Those
acceptance receipts must come from the actual reference delivery and the
Phase 3 resource and final-gate campaigns, not this source README.
