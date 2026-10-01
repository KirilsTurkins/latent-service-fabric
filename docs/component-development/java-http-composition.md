# Typed Java domain and generated HTTP adapter

Use `latent.java-http.adapter.v1` to keep a typed Java business contract and
expose explicitly selected operations through shared HTTP ingress. This profile
uses two independently compiled, packaged and signed components. The domain
exports its typed interface; the generated adapter exports only
`latent:web/application@0.1.0.handle` and calls the domain through the admitted
`latent:service/invoke@0.1.0` provider. An additional local-service hop remains
necessary in this supported profile. No latency difference has been measured.

Build and sign each component independently using the
[paired-capsule signing recipe](../operations/paired-capsule-signing.md).
It keeps a distinct ephemeral builder key and exact source/compiler requirement
for each test artifact and calls the runtime's canonical policy constructors.
The recipe identifies its development-only helper separately from released CLI
commands and retains the original publication operation when recovering a lost
management response.

The one-export Java compiler profile is deliberately retained. Components with
both web and business exports would use the web lifting profile for their whole
surface, including uncalled business operations. Separate components preserve
the domain's proved service value limits. The [runtime regression](../testing/java-http-composition.md)
records those independent limits and the earlier reported failure.

## Generate an adapter from an existing domain

Follow the [Java authoring guide](java-authoring.md) to install the pinned
Temurin 25.0.4.1+1, TeaVM 0.15.0 C backend, Gradle 9.1.0, WASI-SDK 29,
wit-bindgen 0.62.0 and wasm-tools 1.254.0. Run the commands from the runtime
checkout using Python 3.13.5. `DOMAIN` is an independent project created with
`tools/java_capsule.py`, containing its authoritative WIT, Java source, descriptor
and captured SDK. `ADAPTER` must be a fresh directory outside that project.

Review an explicit selection file, following
[the executable example](../../examples/java-http-composition/routes.json).
The closed document selects an exact exported contract, local service and
pinned route. Every route declares its literal path, GET or POST method,
operation and client method name. GET accepts parameterless operations; POST
uses a canonical WIT argument array. Declare private operations explicitly in
`privateOperations`: selected routes cannot expose them. Unselected exports
have no generated route. The example excludes administration, publishing and
provider events even though its domain exports all three functions.

```sh
python3 tools/java_http_adapter.py generate "$DOMAIN" \
  --selection routes.json --output "$ADAPTER"
python3 tools/java_http_adapter.py check "$DOMAIN" \
  --selection routes.json --output "$ADAPTER"
python3 tools/java_capsule.py build "$ADAPTER" --output "$ADAPTER_BUILD" \
  --wasi-sdk "$WASI_SDK_PATH" \
  --repository https://github.com/KirilsTurkins/latent-service-fabric
```

Generation invokes the actual pinned WIT parser and C binding generator against
the domain. It checks this Java profile before C ABI generation and verifies
the real generated component type. It creates an ordinary editable independent
Java project with source-bound `http/generation.json`, `http/schema.json`,
`http/client.mjs`, `http/client.d.ts` and a captured selection. Run `check` before
building: changed WIT types, routes, generated files, SDK or recipe require a
fresh generation. Building still validates the final component's actual
imports/exports against the authoritative contracts and signed package.

The generated Java adapter uses the canonical typed WIT payload format; it does
not replace the domain's contract with an opaque JSON contract. The normal fetch
client validates that typed schema, including exact record fields and result
branches. Full-width integers and floating values retain canonical string
representations; `u64` never passes through a JavaScript number or Java double.
UTF-8, NUL, lists, options and nested records remain typed values. The client
accepts an `AbortSignal`, performs one request and bounds input and response
bodies to one MiB. A node may impose stricter limits. Declared results retain
their WIT branch and HTTP 422; platform failures use fixed public responses.
Uncaught Java exceptions remain platform failures, separate from declared errors.

Only an operator can create the exact local-service binding/grant and pinned
HTTP trigger. The generated project contains no keys, grants, provider bindings,
listeners or user-identity forwarding. A types-only dependency adds types to the
build; it does not import a provider or confer host authority. The example's
adapter has two runtime clock imports and one explicit local-service import;
the domain has two runtime clock imports. Both still require their own grants.

## Execute the maintained example

This command creates independent projects, generates and checks the adapter,
compiles both actual Java implementations, packages/signs them with ephemeral
local keys, admits their exact publications and exercises ordinary HTTP ingress
on enforced Linux nodes. `--target` is the Cargo target directory containing
`debug/latent`, `debug/latentd` and the packaging examples. Use a fresh output
directory; it retains failed attempts and their exact source/compiler receipts.

```sh
python3 tools/qualify_java_composition_shapes.py --output "$SHAPES_OUT"
python3 tools/qualify_java_http_composition.py --output "$HTTP_OUT" \
  --wasi-sdk "$WASI_SDK_PATH" --target "$CARGO_TARGET_DIR"
```

The example's typed domain reuses a types-only interface and includes a typed
world. It exercises full `u64`, UTF-8, wide/nested records, declared errors,
exceptions, denied grants, malformed/oversized values, cancellation, a fresh
call after failure and pinned trigger/canary/drain/rollback currentness. The
normal client is the freshly generated module from the observed project. The
generator negative receipts cover explicit private operations, duplicate
routes/client names, a wrong contract version, altered generated source and a
changed domain integer width followed by successful fresh generation.

## Current finite compiler profile

These are restrictions of this Java bridge, not universal WIT restrictions.
Ordinary aliases, shared interface-owned types and world inclusion are supported.
The actual tool qualification minimizes the following cases independently:

| Case | Stage and supported action |
| --- | --- |
| Shared types and aliases | Parser and real C ABI/bindings succeed; retain typed reuse. |
| World inclusion | Parser resolves the included world; one named export remains supported. |
| Multiple named exports | `java-binding-profile`; use a separately generated adapter/domain. |
| Import/export aliases, version or Java naming collisions | `java-binding-profile`; use distinct interface/package names and one unambiguous version. |
| Public own/borrow resources | `java-binding-profile`; keep resource authority in imported freestanding capability operations. |
| Future/stream shapes | `java-binding-profile`; use the supported imported capability profile. |
| Malformed WIT | Parser stage; correct the reported source span. |
| Flattened/incompatible generated C signatures | `java-c-abi`; use the pinned synchronous unflattened ABI recipe. |
| Java/library or native compilation failures | Retained `java-to-c`/C compilation stage; bind against the reachable maintained TeaVM library. |
| Final component imports or signature allocation | Runtime surface/preparation stage; use declared grants and the selected finite value profile. |

The bridge bounds 1,024 types, 128 interfaces, 256 imported functions, 64
exported functions, type depth 32, 1,024 members per type and a one MiB C
header. Shared type memoization cannot hide a deeper graph. C bridge expansion
is bounded to 16,384 traversals; each generated binding file is at most four
MiB. Project/source snapshot limits are 4,096 entries, four MiB per file and
32 MiB total. Route selection is at most 64 KiB/64 routes; the generated Java,
WIT and client output is at most one MiB. Public exported resources, resource
constructors/methods, inline/world-owned items, futures/streams and ambiguous
interface aliases/versions remain excluded. Imported resource ownership and
cancellation use the canonical SDK; this workflow introduces no alternate
resource protocol, host threads, JVM or application-owned compiler workaround.
