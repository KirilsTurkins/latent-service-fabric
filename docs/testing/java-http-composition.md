# Signed Java domain and ordinary HTTP adapter regression

This maintained synthetic fixture qualifies the development source recorded by
its `latent.java-http.qualification.v1` receipt. It does not require the reporting
application, its secrets, or an email-provider account. The alpha.4 report remains
historical: runtime/SDK `2d6cc2eafc0a17dfe573be4252fa49835bebbbd6`, application head
`80793e79392696f47cc7ec739a0139368c06ab53`, actual CI checkout
`d38e168c7bfc270e5e257f6b2c3b591dca24e104`, first HTTP status 503. The historical
private application has not been reexecuted by this fixture.

## Reproduction and allocation decision

The domain exports a list of a 13-field record, including UTF-8 strings and a
full-width unsigned 64-bit sequence. This is a small real Java component with
retained WIT and generated bindings. Its signature needs more conservative host
space when the lifting allowance increases. `hostcall_fuel` bounds Component
Model value transfer; it is distinct from activation guest CPU fuel.

Signature planning retains checked addition/multiplication and the existing
proof: `fixed + lifting_fuel * max(4, ceil(largest_inline_element / sizeof(Val)))`.
Type-node, name, collection, depth, decoded-value, encoded input/output and
lifted-value bounds remain finite. Preparation validates uncalled exports and
host import types. No value is lifted to discover that its host allocation is
unsafe. Stores and canonical results remain invocation-owned; rejection and
cancellation reclaim physical owners before returning a reusable cell.

Installing HTTP ingress now installs a separate buffered-web codec profile.
Actual `latent:web/application@0.1.0` component exports select it. Every other
component uses the service profile, including a broker-authorized child running
on the same HTTP node. A signed manifest must agree with the actual surface.
Selecting the web profile adds no capability grant. A component containing both
web and typed exports would need to satisfy the web proof for its whole surface;
this fixture deliberately retains an isolated typed child.

| Profile | Lifting allowance | Lifted-value bound | String bound |
| --- | ---: | ---: | ---: |
| Service values v1 | 128 KiB | 16 MiB | 256 KiB |
| Buffered web values v1 | 2 MiB | 64 MiB | 512 KiB |

Both complete codec profiles, the profile-selection revision and all revised
limits participate in compiler/prepared/authenticated native-cache identity.
The native-cache restart regression changes a buffered-web bound while retaining
the source, signing key and catalog; the old image cannot reach the loader.
The former globally widened HTTP policy's rejection is retained through the
ordinary managed preparation owner using the identical signed Java bytes. A
separate disposable node selects the closed `developmentPreparation` profile,
which requires explicit consent, loopback and local experimental isolation and
rejects HTTP ingress, renderers and isolated AOT. The authorized activation tree
records the actual configured bound, required allocation, fixed bytes, lifting
fuel, multiplier and profile identity; public Invoke stays redacted. This
development fixture preserves the historical receipt and does not recreate the
unavailable reporting application.

## Executable qualification

Install the pinned [contributor toolchain](../development/toolchain.md), including
Java, Gradle, WASI SDK and the current binding generators. Prepare the same
executables used by the Java authoring owner:

```bash
cargo --config .cargo/managed-guest.toml build --locked -p latent -p latentd --bins \
  --features latentd/development-test-node \
  -p latent-packaging --example package --example capsule_contracts \
  -p latent-policy --example capsule_authoring
python3 tools/qualify_java_http_composition.py \
  --output /tmp/lsf-java-http-composition-unique \
  --wasi-sdk /opt/wasi-sdk-29.0-x86_64-linux
```

Choose a new absolute output each time. The owner captures the actual checkout,
compiler inputs, independent component/package/source identities and generated
bindings. It signs only after both builds finish, using disposable short-lived
demo trust, admits through the real enforced supply-chain verifier, and executes
the identical components under former-global, current standalone and current
HTTP-enabled node profiles. The optional development feature is compiled into
these qualification executables solely for the consented reproduction.
Compilation receives no signing keys. Failed attempts keep their original
`BUILD-FAILED.json`, `QUALIFICATION-FAILED.json`, node receipts and bounded logs.

To exercise the delivered native `latent-dev` frontend against this same running
standalone node, add `--native-frontend /absolute/path/latent-dev` and
`--native-frontend-build-receipt /absolute/path/build.json`. The original native
build receipt must match the binary digest and the four current packaged
preflight resources. The owner freezes declarations from the original signed
OCI layers and independent build metadata, then uses the supported target RPC
to pin the selected publication, deployment generation, engine and provider
policies. It retains native positive, finite negative, former-profile allocation
and original-policy-change checks before asserting their outcomes. These
read-only observations grant no execution authority. Provisioned workspace
qualification uses its separate native installer owner.

The workflow exercises direct versus composed typed values, selected public
routes, denied/missing grants, full-width values and UTF-8, declared errors and
Java exceptions, malformed/over-limit strings/lists/records, fresh invocation
after rejection, physical cancellation cleanup, canary, stale target, drain and
rollback. The [Java CI owner](../../.github/workflows/java-guest-feasibility.yml)
retains public source/build/outcome artifacts even on failure. A passing build
or the standalone/outbound-HTTP owners alone does not qualify composition.

No release/backport is selected automatically: review this development fix and
its exact-head evidence before deciding a maintenance-release target. Private
application qualification remains a separate optional operator run when the
source and policies are available. No performance or delivery guarantee is made.
