# Scoped Angular render data

The `scoped-http-get-v1` profile lets an Angular server renderer fetch one
bounded HTTP response through the activation's capability broker. The
[reference application](../../examples/angular-reference-application/README.md)
uses it for allowed and denied backend requests. The decision is recorded in
[ADR 0042](../../adr/0042-bound-angular-render-data-through-the-capability-broker.md).

## Signed authority selection

The closed Angular build input optionally selects
`"backendProfile": "scoped-http-get-v1"`. Omitting the field, or selecting
`"none"`, retains the context-only renderer. The profile is copied into the
signed web manifest; a non-Angular renderer cannot select it. Package projection
requests the exact asynchronous `latent:http/client@0.2.0` import and one
outbound call. Structural validation checks that import before execution.

This is a request for authority, not a grant. The existing binding, policy,
provider configuration, currentness, deadline and budget checks remain the
authority boundary. The application receives no provider credential, socket,
connection pool, filesystem path or ambient JavaScript networking API.

## Application contract

An optional server `prepare(request, context)` returns `null` or `{url: string}`.
The fixed Rust adapter rejects unknown fields, more than 4 KiB of plan JSON,
empty URLs, URLs larger than 2 KiB and control characters. It performs at most
one GET through the broker, with no caller-selected headers, body or retry.
The requested 2,000 ms timeout does not extend the activation deadline.

Server `render(request, context, backend)` receives `null`, or one of:

```json
{"outcome":"response","status":200,"body":"bounded UTF-8 application data"}
```

```json
{"outcome":"failure","code":"permission-denied"}
```

The adapter admits at most 4 KiB of UTF-8 response data to JavaScript. Other
responses become closed failure categories, never raw transport diagnostics.
The application chooses what public data to render; the existing HTML and
hydration limits apply independently. The browser is not given node authority.

The private composition interface permits one prepare followed by one render,
or one context-only render. Reusing a renderer Store is rejected. Async provider
work belongs to the activation; this adds no dormant application process,
thread, listener or provider pool.

## Selected publication and binding

The deployment binding compiler checks the sealed web layout, renderer digest
and publication identity. The scoped profile requires exactly one explicit HTTP
grant, using the existing `bounded-http-v1` provider and `send` operation. A
context-only renderer cannot acquire that grant. Existing resource restrictions,
policy decisions and provider configuration still determine whether a call runs.

The host reserves `guest.lsf.web-publication` for the selected web execution.
It removes any caller-supplied value and supplies the publication only when the
prepared release and publication match the resolved web revision. The extra
metadata entry is charged before transferring context ownership. The existing
context disclosure policy still applies; this is not a new WIT interface.

The private renderer adapter passes this identity to the fixed wrapper, which
validates its canonical shape and emits the immutable client URL under
`/_lsf/assets/<publication>/client/`. This avoids embedding a publication's own
digest in its capsule. Context-only qualification fixtures without a selected
publication retain their relative asset URL; they are not evidence of native
publication-bound browser delivery.

## Earlier validation milestones

The initial signed-profile admission unit, exact async import structural unit, both
Wasm adapter feature builds, closed-input schema cases and executable shipped
JavaScript ordering cases passed locally. The initial Windows Python run had
three environment skips. The subsequent Linux run, with the locked tool tree
and Python requirements installed, passed all 13 tests without skips. The
Linux native CLI/node build and strict all-feature node Clippy check also passed.

The [maintained reference application](../../examples/angular-reference-application/README.md)
has an earlier observed Linux package build with the scoped backend feature:
package `sha256:5e302eeed8f98721fcefe9e65692da55952e3b8ef6618c7b1a2432505e398e98`,
SBOM `sha256:f6f1c076e172d711ae9e6f7379e64c4bbcfb6a6e56ead177e86420a30131eef0`,
and six web outputs totaling 24,416,192 bytes. The build inspection explicitly
reports `trustEvaluated: false` and `executionAuthorized: false`. It proves
packaging and structural validation, not protected native execution or browser
delivery. The application includes public and sealed-user views, a declared
failure, bounded allowed/denied backend plans and hydration navigation.

The subsequent publication-bound asset change passed eight Linux owned-context
tests, two web-binding tests, the Wasm adapter feature check and twelve executable
build-wrapper/backend-bridge Python tests with no skips. It changed the locked
renderer profile identity, so the earlier package is historical evidence, not a
substitute for rebuilding and qualifying the current profile.

The later [complete reference qualification](../testing/angular-reference-workflow.md)
passed signed application delivery, allowed/denied provider calls, authenticated
content, cancellation/recovery, real-browser hydration/navigation, canary and
rollback under the protected native profile. A fresh execution is retained in
the [repository validation review](../phase-3-gate-review.md#repository-execution-review-september-23).
[Resource measurements](../testing/phase3-resource-renderer.md) retain their own
host and profile limits. These results do not establish arbitrary Angular or
Node compatibility, build reproducibility or completion of the human guide review.
