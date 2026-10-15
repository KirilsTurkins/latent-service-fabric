# latent-ingress

Protocol adaptation and concrete bounded buffered HTTP application values. The HTTP module owns finite exchange collection, canonical request/response conversion, browser-boundary validation, delivery and an optional immutable public response cache. It does not open a listener.

Authenticated application authority comes from the trusted host/selected route, never from forwarded identity fields, cookies or a guest-supplied response header.

## Responsibilities and architecture

| Source | Responsibility |
| --- | --- |
| [src/lib.rs](src/lib.rs) | Generic ingress request/response, principal extraction and routing ports. |
| [src/http.rs](src/http.rs) | HTTP error and shared exchange-owner exports. |
| [src/http/bounded.rs](src/http/bounded.rs) | Closed typed decoding after raw lexical/frame bounds. |
| [src/http/body.rs](src/http/body.rs) | Canonical base64 body representation distinct from list<u8> semantics. |
| [src/http/cache.rs](src/http/cache.rs) | Opt-in immutable public response cache published only after successful delivery. |
| [src/http/transaction.rs](src/http/transaction.rs) | Direct typed transaction application routes over existing exchange ownership. |

## Execution and ownership

1. The node listener admits a bounded exchange and selects exact configured application/route authority.
2. Collect and validate canonical method/path/headers/body and browser request constraints.
3. Invoke the ordinary activation or transaction owner, preserving original admission and deadline.
4. Validate returned status/headers/body and deliver under the original exchange reservation. Cache publication requires successful Delivery::finish, not merely a guest return.

## Integration boundaries

Listener/socket management lives in `latentd`; durable HTTP trigger selection lives in the control catalog. Static assets and Angular rendering share the edge but have distinct publication/execution semantics. The browser boundary rejects unapproved origin/CORS/cookie behavior, and guest headers cannot override host security policy. A transport disconnect and application cancellation remain separate events.

## Dependencies and build

Direct workspace dependencies: [latent-core](../latent-core/README.md), [latent-activation](../latent-activation/README.md), [latent-identity](../latent-identity/README.md), [latent-triggers](../latent-triggers/README.md).

Consumers with normal workspace dependency edges include [latentd](../../apps/latentd/README.md), [latent-wire](../latent-wire/README.md), [latent-control-store](../latent-control-store/README.md). Optional features still gate the selected graph; target-specific and test edges are also declared in the manifests.

Use [Cargo.toml](Cargo.toml) for external dependencies, target gates and test/build edges; [the workspace manifest](../../Cargo.toml) and [the toolchain guide](../../docs/development/toolchain.md) own current pins. Dependency presence does not install a runtime service.

## Tests and verification

The [package entry point](src/lib.rs) and the module links above are the source map. [The workspace package guide](../../docs/development/workspace-packages.md) explains feature/target selection, generated inputs and the registered test workflow.

Inspect a registered suite from the repository root without building or running it:

```sh
python3 tools/test.py explain --suite latent-ingress.lib.latent-ingress
```

Use `list --output json` to find the remaining package targets. Follow the suite's recipe, platform and prerequisites for preparation, discovery and execution; a registration or compile-only check is not a passing execution/qualification result.

Representative source tests (not a complete coverage inventory):

- [`public_document_exception_requires_opt_in_complete_metadata_and_safe_anonymous_method`](src/http/browser/tests.rs)
- [`browser_origin_is_exact_and_never_accepts_null_lists_siblings_or_forwarding`](src/http/browser/tests.rs)
- [`fetch_metadata_and_mutation_rules_fail_closed_without_cors_or_cookie_authentication`](src/http/browser/tests.rs)
- [`cookie_count_bytes_duplicates_and_identity_encoding_are_bounded`](src/http/browser/tests.rs)

Integration targets: [tests/http.rs](tests/http.rs).

## Related documentation

- [Shared HTTP application ingress](../../docs/reference/http-ingress.md)
- [Bounded HTTP response cache](../../docs/reference/http-response-cache.md)
- [Scoped HTTP trigger routes](../../docs/reference/http-triggers.md)
- [Browser and hydration boundary: same-origin-v1](../../docs/security/browser-boundary.md)
- [Direct transaction HTTP binding v1](../../docs/development/transaction-http-v1.md)
- [ADR-0035: Bound HTTP application values and delivery ownership](../../adr/0035-bound-http-application-values-and-delivery-ownership.md)
- [Workspace package index](../README.md)
- [Architecture index](../../ARCHITECTURE.md)
