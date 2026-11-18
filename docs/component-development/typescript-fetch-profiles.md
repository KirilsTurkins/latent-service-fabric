# TypeScript Fetch API and profile selection

These profiles supply ordinary `globalThis.fetch`, `Request`, `Response` and
`Headers` before direct and transitive modules initialize. A package using this
API needs no LSF transport, executor, package registration or package-specific
compiler branch. This is a finite buffered API, with separately recorded signed
execution evidence; selecting it does not certify an entire browser or Node API.

Both profiles select the explicit
`spidermonkey-activation-promises-clocks-imports-v1` runtime. Its captured engine
and compiler splicer must agree with the project and dependency inputs.

| Declared WIT import | Automatically selected Fetch backend | Fetched `statusText` |
| --- | --- | --- |
| `latent:http/streaming@0.3.0` | `lsf-fetch-buffered-v1` | Explicit unsupported getter; the contract supplies no reason phrase. |
| `latent:http/phase-timing@0.4.0` | `lsf-fetch-phase-buffered-v2` | Exact observed Latin1 bytes, including empty text and whitespace; unavailable metadata refuses. |

The phase interface imports the original upload/body/chunk resource identities
as types. It needs no callable legacy HTTP provider or grant. An unavailable or
incompatible provider refuses before guest work; no socket fallback occurs.
Neither profile gives Fetch a separate connect/read-timeout option.

## API behavior

| Surface | Finite contract |
| --- | --- |
| Request construction | Absolute HTTP(S) URL; GET, HEAD, POST, PUT, PATCH, DELETE and OPTIONS. Embedded URL credentials and unsupported options refuse. GET/HEAD reject a non-null body. |
| Headers and credentials | Validated ordinary header APIs; iteration and `forEach` observe mutations to the bounded, sorted header list. Reserved authentication/framing fields refuse. Operator credentials stay in the selected provider's protected scope. No ambient browser origin, cookie jar, proxy or Node configuration is inherited. |
| Request bodies | Copied UTF-8 strings, ArrayBuffer/views and supported URLSearchParams. Non-null bodies are one-shot. Unsupported streaming uploads, Blob and FormData refuse. |
| Response bodies | Complete bounded buffering before Fetch resolves; `text`, `json`, `arrayBuffer`, independent buffered clones and the selected buffered reader/cancel interface. A buffered reader supplies no network backpressure or header-first resolution. |
| HTTP status | HTTP 4xx/5xx resolve to responses. Parsing failure remains a parsing error; transport failure retains its typed cause and possible-dispatch uncertainty. |
| Redirects and retries | Finite authorized GET/HEAD follow-ups; cross-origin forwarding removes guest headers. Every call needs its own authority and budget. LSF does not replay failed connections or mutations. |
| Cancellation | Already-aborted signals make no contact. Public rejection preserves the original reason. Accepted I/O, chunks and body owners retain charges until actual retirement; rejection alone is no refund or rollback proof. |
| Timers and root lifecycle | Invocation-local timers, microtasks and accepted work use the selected runtime and original deadline. Root cancellation/deadline and requested timer completion remain distinct. |
| Isolation | Fresh activation/module/client state. Independent tenant HTTP registrations have separate credentials and sealed provider references, with the existing node-wide ceilings. |

The source profile caps a buffered body at 1 MiB, transfer chunks at 64 KiB,
headers at 64 entries/32 KiB, URLs at 2048 characters and outstanding operations
at sixteen per activation. Provider policy, guest memory and the original
deadline impose additional limits. Each header-iterator step re-sorts at most 64
entries and allocates temporary arrays within the original guest memory limit.
These API constants are not measurements of native or kernel memory. The
explicit published-client execution profile uses
64 task slots, 64 queued work slots and 256 native-owner slots; this is no claim
that every compatible package requires that profile or that these are minima.
The phase-client programme additionally declares the uniform initial
`typescript-phase-published-clients-fuel-v1` allowance of two billion fuel units.
The prior one-billion run completed Ky JSON at944,147,189 units and exhausted
that allowance while handling Ky's404 response. That failed run remains failed;
the larger initial allowance passed the signed programme. Ky404 used
1,008,907,090 units, confirming finite completion just above the prior limit. It changes no
shared default, body/owner/memory limit, deadline, grant or helper budget.

## Add a dependency and authorize its work

1. Use the normal [captured npm workflow](typescript-dependencies.md) to declare,
   lock, resolve and review the package and its transitive inputs. Public,
   private-registry and outside-checkout packages follow the same API boundary.
   Package coordinates are evidence inputs, never eligibility criteria.
2. Select the [import runtime](typescript-import-runtime-candidate.md) and one
   typed HTTP import in the application's WIT world. Use ordinary globals and
   library constructors. Keep the captured SDK and backend bytes unchanged.
3. Compile and sign through the existing [TypeScript authoring workflow](typescript-authoring.md).
   Module conditions, source/assets, SDK, automatic backend, compiler and
   component identities enter the build observation. Runtime credentials,
   request identity and live Promise/timer state do not enter the snapshot.
4. The operator separately installs the matching HTTP/runtime providers and
   grants exact publication, method, origin and path authority. Declaration,
   capture and library import supply no grant. Independent tenants use
   [independent HTTP installations](https://github.com/KirilsTurkins/latent-service-fabric/pull/1225).
5. An unsupported runtime module or member reports its technical profile gap.
   Adding a compatible package requires no new LSF release or catalogue entry.

## Select the phase contract for a new project

For a phase-only project, create the project with the import runtime before
capturing its npm dependencies. From the matching LSF checkout, choose a fresh
outside-checkout path for `APP`:

```bash
APP=/absolute/path/to/my-fetch
python3 tools/typescript_capsule.py new "$APP" --template greeting \
  --runtime-profile spidermonkey-activation-promises-clocks-imports-v1
```

Add `import latent:http/phase-timing@0.4.0;` inside the `service` world in
`$APP/wit/world.wit`. The phase interface uses the original streaming HTTP
resource identities. Install its WIT and the checked, type-only legacy
dependency from the captured SDK:

```bash
python3 - "$APP" <<'PY'
from pathlib import Path
import sys
from tools.http_phase_wit import nominal_type_owner

app = Path(sys.argv[1]).resolve(strict=True)
sdk = app / 'vendor/lsf/wit/platform'
dependencies = (
    ('http-phases', (sdk / 'http-phases/package.wit').read_bytes()),
    ('http-v3', nominal_type_owner((sdk / 'http-v3/package.wit').read_bytes())),
)
for name, contents in dependencies:
    target = app / 'wit/deps' / name / 'package.wit'
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as output:
        output.write(contents)
PY
wasm-tools component wit "$APP/wit"
```

The helper refuses a legacy WIT source that differs from this checkout and
removes only its eight callable operations; it retains the original types and
resources. The exclusive writes refuse existing dependency files. If the
application also needs callable legacy HTTP, review that separate import and
grant instead of replacing its dependency with this phase-only projection.
WIT parsing checks the declarations, not a provider or signed execution.

The greeting template starts with `limits.outboundRequests` set to zero. Set a
finite nonzero request budget in `$APP/capsule-project.json` for the intended
calls, within the node and policy ceilings; this budget is not a network grant.
Choose CPU and owner limits that the deployment admits. In particular, the
historical Ky 404 programme required the separately declared fuel allowance
described above, rather than the greeting template's default.

Add Ky through the normal capture workflow, using `--condition browser` on
`resolve` if selecting the browser condition used by the published-client
programme. The application can call `ky.get(url)` normally; no application
transport callback is required. Build with matching source-bound import-engine
and splicer inputs as described in the [import runtime guide](typescript-import-runtime-candidate.md).
The operator must separately enable `providers.httpStreaming.phaseTiming`,
install and bind `latent:http/phase-timing@0.4.0` with profile
`bounded-streaming-http-phase-timing-v1`, and grant the publication only its
required methods, origins and paths. The [phase authority guide](../testing/http-phase-operational-authority.md)
describes the nominal dependency and the distinct operational grant.

The historical signed phase programme includes unchanged Ky's 404 handling;
that receipt is tied to its recorded source and engine. This recipe does not
establish a passing signed result for a newer engine, enable production or
change the legacy profile's unsupported `statusText` behavior.

## Optional public extensions

A library's public Fetch callback remains an ordinary captured guest function.
For example, Ky's optional callback may delegate to `globalThis.fetch`; its
requests still cross the same typed grant and resource checks. The callback
cannot install a privileged provider, read another provider's credential store,
widen a destination grant or keep work alive after retirement. Such extension
evidence is labelled separately from unchanged constructor/default-global runs.

## Execution evidence

Evidence below remains bound to its original source and engine products. The
[active #745 integration ledger](../testing/typescript-runtime-745-qualification.md)
records a later source-owned AbortSignal change whose signed Fetch programme
fails at native fan-out refusal. Do not transfer earlier client qualification
to that changed engine, infer byte-accurate runtime accounting from owner-slot
ceilings, or infer socket/DNS/TLS authority from a Fetch profile. The selected
compiler candidate remains `qualification: unknown` / `apiSupport: not-evaluated`
until separately scoped execution evidence establishes the claimed behavior.

The legacy buffered and published-client programmes retain their own signed
receipts, source identities and finite limits. The current
[phase programme](../development/typescript-fetch-phases.md) requires normal
Ky/Wretch and a captured transitive package, missing grants/provider, exact wire
metadata, public/root cancellation, optional extensions and fresh same-node
tenant reuse. Its expanded thirty-one-outcome execution
[passed run39459627034](https://github.com/KirilsTurkins/latent-service-fabric/actions/runs/39459627034/job/118755383589):
27 guest executions, four pre-entry refusals,31 physical-retirement observations,
14 main-peer and ten tenant-peer contacts. Independent review checked all491
archive members,193 Git material identities, the exact component and both
public-abort charged-owner barriers. Three nodes stopped cleanly; the two
tenants shared one execution cell with separate HTTP credentials and grants.
The [receipt](../testing/evidence/typescript-phase-fetch-signed-2026-10-20.json)
retains the source/native tuple, finite limits and original failed runs separately.
Reference controls and compiler-input `unknown` qualification do not become
signed execution credit or a release declaration.
