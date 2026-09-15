# Observed Angular application builds

The maintained builder compiles actual Angular 22.1.6 server and browser code,
embeds the server in the qualified JavaScript component, composes the fixed
public async adapter, and assembles a componentless `ssr-package`. It implements
[#234](https://github.com/KirilsTurkins/latent-service-fabric/issues/234) for the
[closed renderer profile](../runtime/angular-renderer-profile.md). This is a
trusted developer-plane build operation with finite process ownership; it does
not start a node, publish a package, sign evidence or authorize execution.

## Build an application

Provision Python 3.13, the repository's exact Rust and wasm-tools versions, the
`wasm32-unknown-unknown` target, and Node 24.19.0. The approved tooling root must
have the exact [qualification package and lock](../../examples/renderer-profile/package.json).
Install those tools explicitly; application dependency installation and npm
lifecycle hooks are not part of the recipe:

```sh
npm --prefix examples/renderer-profile ci --ignore-scripts --no-audit --no-fund
cargo build --locked -p latent
python3 tools/build_angular_package.py \
  --input-root examples/angular-application \
  --toolchain-root examples/renderer-profile \
  --cli "$PWD/target/debug/latent" \
  --target-root "$PWD/target/angular-build" \
  --output "$PWD/target/angular-build/hello" \
  --cargo-target-dir "$PWD/target" \
  --repository https://example.com/source
```

Cargo dependencies must already be available in the approved cache; the adapter
build uses `--locked --offline`. The example repository URL is an asserted public
source label, not a claim that source was fetched from that address. The source
revision is the exact selected-input inventory digest. The caller must select a
fresh output directory under the explicit scratch root, separate from application
source. Nothing overwrites an existing package.

The result contains `inputs/`, the immutable OCI-layout `package/`,
`observation.json` and `build-summary.json`. The summary reports exact package,
SBOM and ordered web-output identities, `trustEvaluated: false` and
`executionAuthorized: false`. Build children have exited and their owned scratch
has been reclaimed before the result directory becomes visible. Failed builds
remove their owned scratch and staged results.

## Supported source and output contract

[`angular-build.json`](../../examples/angular-application/angular-build.json)
conforms to the [closed build schema](../../schemas/angular-build.schema.json).
It selects explicit TypeScript, HTML and CSS under `server/`, `client/` and
`shared/`, two TypeScript entries, explicit public assets and exact routes. It
cannot select application commands, compiler plugins, arbitrary dependencies or
tsconfig/Babel/environment substitution. Unlisted files, including `.env` and
application `package.json`, are not captured. Do not put secrets in selected
sources or assets.

The fixed compiler recipe permits the declared Angular and RxJS imports and
captured relative modules. It rejects dynamic imports, native modules, ambient
process/worker/interval APIs, triple-slash reference directives and uncaptured
template/style references. Client and shared code cannot import server code or
read server templates/styles. The bundler also checks the final module graph;
templates are checked earlier because Angular inlines them before bundling.
These checks define a conservative authoring profile, not a JavaScript security
sandbox. Final component validation and the runtime resource boundary remain
mandatory.

The generated browser entry has the content-addressed path
`/client/<full SHA-256>/main.js`. The supplied server's
`__LSF_CLIENT_ASSET__` marker is replaced with this path before the HTML leaves
the fixed wrapper. Public assets contain the browser graph and explicitly named
`public/` inputs. Server code is retained only in the private renderer; source
and bundle inventories are private package metadata. Source maps are disabled.
The web deployment/serving integration must bind documents and asset requests to
their selected publication; this build-time content hash alone is not deployment
authorization or a revocation policy.

Routes may select server rendering, client documents or explicitly supplied
prerender HTML. Supplied prerenders are validated and inventoried as inputs;
the builder does not claim to have rendered them. `render()` must return the
closed status/header/HTML shape. Every render has fresh module and activation
state under the [generic-cell runtime](../runtime/angular-renderer-runtime.md).

| Resource | Builder profile |
| --- | --- |
| Build duration / individual tool | 1,800 seconds aggregate / at most 300 seconds |
| Tool stdout plus stderr | At most 4 MiB per invocation |
| Source files / individual source / source total | 256 / 1 MiB / 16 MiB |
| Supplied public assets / generated browser entries | 126 / one |
| Individual asset / asset tree | 8 MiB / 16 MiB |
| Portable path / path segment | 220 / 64 ASCII characters |
| Routes / web manifest | 128 / 64 KiB |
| Renderer component | 32 MiB |
| Returned or supplied HTML | 128 KiB |
| Returned JSON hydration data | 32 KiB aggregate; at most 64 script tags |
| Installed npm tree observation | 40,000 entries / 1 GiB file bytes / 8 MiB inventory |
| SBOM inventory | 1,024 entries / 1 MiB |

The installed tool tree, executable identities, recipe and lock identities are
observed before work and checked again after work. Node children receive a
private home and a small environment without signing keys, bearer tokens, npm
configuration or arbitrary Node options. Tool execution reuses the existing
Python process owner on Linux and Windows, including timeout/cancellation
cleanup. Deliberate session escape, supervisor termination and hostile-source
OS isolation remain outside that trusted-build helper's guarantees.

## Evidence and reproducibility

The existing web predicate now supports the separately approved build type
`https://latent.dev/build/angular-component/v1`. The old supplied-file assembly
recipe keeps its original wire representation. Approval for that assembly recipe
does not authorize the Angular recipe. The Angular observation binds the exact
final component and profile digest, JS embedding, compiled async adapter,
adapter source, public/private WIT, actual server/client bundles, npm lock and
installed tree, Cargo lock, tool executables, source inventory and recipe.

The package-bound SBOM uses actual output bytes, installed npm manifests checked
against the lock, and the adapter's actual Cargo JSON units with existing
bounded manifest/lock attribution. Duplicate installation aliases collapse only
when their attribution is identical. Registry archive digests remain declared
archive identities; observing a cached manifest does not prove that archive's
contents. The embedded JS engine, transitive runtime closure and native tool
dependencies are not claimed complete. `dependencyCompleteness` remains
`declared-inputs-incomplete`, and `hermetic` remains false.

Ordinary builds report `reproducibility: not-checked`. Add
`--verify-reproducible` to run two complete builds from the same captured input
bytes and require exact final package equality. A mismatch fails with
`Angular byte reproducibility failed; no package was published`, removes both
staged results and emits no successful observation. ComponentizeJS's initializer
and fresh build-path behavior have not established byte reproducibility for this
profile. Package assembly is deterministic for identical supplied output bytes;
that does not make compilation reproducible. No compiled bytes, timestamps,
receipts or evidence are rewritten to make a comparison pass.
Two actual builds of the maintained example failed this byte-equality check
during #234 validation; both staged results were reclaimed. A policy requiring
reproducibility rejects the ordinary `not-checked` observation.

An unsigned observation grants nothing. A separately approved builder signs it
after tool cleanup, and publisher, builder, SBOM and tenant verification must
all succeed against the actual package. The native execution T1 gate remains
closed until [#226](https://github.com/KirilsTurkins/latent-service-fabric/issues/226)
supplies the sealed web-publication execution projection and proves enforced
admission, isolated native preparation and restart with these actual artifacts.

## Required conformance

Renderer-related PRs build the actual example through this adapter. Existing
workspace harnesses then verify structural/package limits, real publisher and
builder signatures, SBOM policy, tampering, wrong-tenant rejection and admission
restart. A generic-cell test renders Alice/Bob with fresh state, rejects excessive
hydration data and proves recovery. Headless Chrome loads that exact client and
the actual generic-cell HTML, proves the original DOM is reused, checks escaped
text and clicks the signal-backed counter. Test harnesses are selected from the
current Cargo build inventory; these gates do not rebuild the Rust workspace.

These are finite conformance fixtures, not throughput or memory benchmarks.
Generated packages and HTML remain temporary CI/local output. No large binary
or benchmark report is committed.
