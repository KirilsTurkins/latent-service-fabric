# Private Cargo dependency programme

`tools/qualify_rust_private_dependencies.py` prepares two ordinary, unrelated
private registry crates with a real transitive edge and `include_str!` resource.
An owned HTTPS sparse registry serves their actual Cargo archives. Its ephemeral
public CA bundle is explicitly selected; machine trust stays unchanged. Only
the controlled native lock update and resolution stages receive a synthetic
registry token. No application startup or build script discovers permissions.

The normal Rust authoring `resolve` and `review-lock` commands must accept the
original graph. Native Cargo's lock and captured vendor checksum must match each
published archive. Fresh missing-token, wrong-token and untrusted-certificate
attempts must fail without changing accepted inputs, exposing credentials or
authorizing an automatic replay. An untrusted CA must fail before an HTTP request.

Before compilation, the registry and its request owners stop, its listener must
refuse connections, and the original archives, registry private key and native
acquisition cache are removed. Missing/tampered transitive resource bytes and a
changed CA bundle must fail the ordinary verified-input reader; exact restoration
recovers the accepted closure. Two normal offline component builds then use the
captured graph. Source, SDK and compiler materials remain attributable; equal
component bytes across attempts are not assumed as reproducibility evidence.

The first private component is signed alongside the four exact companion builds
from the preceding maintained qualification. The enforced node must run the
actual private/transitive/resource greeting plus its existing declared-error,
fresh-activation, denial, trap, memory/fuel, deadline, cancellation, disconnect and
ownership programme. Companion recovery/HTTP cases establish their own component
boundaries; they do not qualify arbitrary behavior in either private crate.
Normal clean shutdown must retire the node and provider owners.

```sh
python tools/qualify_rust_private_dependencies.py \
  --prepared-qualification /prepared/rust-capsule-dependencies \
  --output /outside-checkout/rust-private-dependencies
```

The existing Rust workflow runs this after its complete public dependency and
approved-generator programme, with the same pinned tools and frozen native
products. All previous commands and the workflow's 35-minute limit remain.
Artifacts retain bounded source/recipe/graph identities, failed-stage outcomes,
redacted peer observations and actual node receipts. Private keys and registry
credential values are excluded from artifact selection. A checked-in programme
is not proof that its current hosted run passed. The Rust runtime/port and HTTP
client qualifications remain separate owners.

## Installed Rust HTTP toolkit

On November 24 an installed Linux source-candidate toolkit built a captured
application with Waki 0.5.1, Golem WASI HTTP 0.2.0 and two outside crates. The
compiler ran offline with no source checkout. It required explicit approval
for the 16 captured executable inputs before building the 966,033-byte
component. The controller packaged the resulting bytes and preserved the
compiler observation.

The installed-node check ran four signed calls across two tenants and
refused two calls before guest entry. A second run of the same package
exercised both crate aliases, real 404 responses and repeated requests. All
16 signed calls returned their expected results. Each tenant observed ten
requests, zero mutations and closed connections. Each private crate used its
57-byte embedded price card to check the successful domain response. Both nodes
shut down cleanly. The receipt records the component, package and both runs.
[Installed package and execution record](evidence/sdk-private-library-invocations-2026-11-23.json)
