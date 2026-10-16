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
