# Scoped Angular render data

This is the implementation milestone for the reference application in
[#236](https://github.com/KirilsTurkins/latent-service-fabric/issues/236), not
its final browser or resource qualification. The decision is recorded in
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

## Validation milestone

The signed-profile admission unit, exact async import structural unit, both
Wasm adapter feature builds, closed-input schema cases and executable shipped
JavaScript ordering cases pass locally. The Python run has three environment
skips: Windows symlink creation and two checks requiring the installed Angular
tool tree. These are not substitutes for the required Linux build gate.

Actual signed application delivery, allowed/denied provider calls, authenticated
content, cancellation/recovery, real-browser hydration/navigation, canary and
rollback remain required before #236 closes. The native T1 qualification is
owned by #226; measured plateaus and retained end-to-end evidence by #239/#240.
