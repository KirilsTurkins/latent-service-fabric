# Captured npm dependencies

Use `typescript_capsule.py add PROJECT PACKAGE --version EXACT_VERSION` or `--path LOCAL_PACKAGE` to edit the ordinary root `package.json`, then generate and review a native npm v2/v3 `package-lock.json`. Keep them separate from `vendor/lsf/sdk/typescript-guest/tools/package-lock.json`, which pins the SDK compiler. Package coordinates identify provenance; no application catalogue entry is required.

Create/update the native lock in a separate fetch step with lifecycle scripts disabled, then capture and review the selected closure:

```powershell
python tools/typescript_capsule.py add ./my-typescript '@jridgewell/trace-mapping' --version 0.3.31
python tools/typescript_capsule.py lock ./my-typescript
python tools/typescript_capsule.py resolve ./my-typescript --candidate ./npm-candidate.json
$candidate = 'sha256:' + (Get-FileHash -LiteralPath ./npm-candidate.json -Algorithm SHA256).Hash.ToLowerInvariant()
python tools/typescript_capsule.py review-lock ./my-typescript --candidate ./npm-candidate.json --expect $candidate
python tools/typescript_capsule.py dependencies ./my-typescript
python tools/typescript_capsule.py build ./my-typescript --tools ./reviewed-typescript-tools --output ./my-typescript/target/build-1 --repository https://github.com/example/application
```

`add`, `update` and `remove` edit only application declarations and preserve the accepted lock and SDK. Versions are exact; `--section` selects dependencies, development, optional or peer declarations. `lock` explicitly regenerates the native lock in a private fetch attempt with ignored lifecycle scripts, executable links disabled and strict peer resolution. It observes direct and transitive local inputs, mirrors their relative layout, rejects SDK/project overlap and unobserved local selections, and rechecks source, tools and registry policy before atomic native-lock replacement. Native failure leaves the previous lock intact. This step does not accept a captured closure: run `resolve`, inspect its fresh candidate and explicitly `review-lock` afterward.

The project-owned explicit runtime profile is inherited by direct resolution as well as the CLI. An explicit conflicting capture profile fails before a native command. Candidate profile selection retains its current qualification state; it does not establish Promise, timer or networking support.

Capture uses pinned Node 24.19.0 and the observed npm CLI in an owned directory and empty home/cache. It runs native `npm ci` with ignored scripts, disabled executable links and strict peer resolution. Relative local dependencies keep their native layout in an owned mirror; absolute file paths are relocated only for that fetch attempt, with original and selected declaration digests retained. Local original source bytes, original integrity-checked package archives, the selected regular module tree, exact physical transitive/peer/optional edges and platform selection are captured separately. Unsafe archive entries and unobserved links fail even when npm has expanded the package. Directory dependencies containing bundled `node_modules` currently require an explicitly packed native archive so their original input boundary is complete.

New captures select each dependency from the observed installed packages, walking the nearest package's ancestors as [Node 24.19.0 specifies](https://nodejs.org/download/release/v24.19.0/docs/api/modules.html#loading-from-node_modules-folders). A lock entry alone cannot satisfy a required dependency or peer. Genuinely omitted optional dependencies and optional peers retain an unselected edge; [`optionalDependencies` replaces a same-name `dependencies` declaration](https://docs.npmjs.com/cli/v11/configuring-npm/package-json/#optionaldependencies). Resolution never fills a missing edge from a sibling package or ambient/global installation. Missing required or peer packages fail before a candidate or accepted capture is replaced. Existing accepted captures keep their original identity; resolve and review a new candidate to obtain this installed-graph observation.

The default module recipe uses neutral ESM output with the native `exports`/`imports` order and import/require/default branches. Static CommonJS `require` is supported for captured modules. `--condition <name>` records explicit custom conditions; the recipe does not force a browser branch. Reachable dynamic module/code loading and native addons fail concretely. A reachable standard runtime module reports the missing operation/profile until its maintained implementation is installed. Bundling does not qualify pending Promise exports, timers, Node processes, or network authority; `spidermonkey-public-sync-v1` remains the current selected profile.

The builder typechecks ordinary application imports against the captured tree, bundles immutable JSON/text/binary assets and records exact reachable source digests, selected files, module conditions and an external source map. Application initializers cannot observe clock/entropy through the recipe's guarded standard intrinsics during snapshot creation. This guard is a current profile control, not qualification of all clock/entropy APIs or arbitrary metaprogramming. Fresh activation/runtime semantics retain their separate component gates.

Captured builds require the maintained Linux namespace profile. The builder stages the complete reviewed SDK compiler, records native helper/loader bytes, and isolates Node, bundling and component initialization without network, ambient home or inherited registry/signing credentials. Captured source/module/compiler mounts are read-only during application initialization; bounded commands reap owned descendants. No application package plugin or install script is executed by this recipe. [Explicitly approved generators and script launchers](typescript-generators.md) capture TypeScript source in a separate isolated stage; capture alone does not authorize execution. The boundary targets a trusted single-user build host and does not claim hardened multitenant or fully hermetic execution.

For private registries, pass the same explicit `--registry-config` to `lock` and `resolve` with `{"registries":[{"scope":"@private","url":"https://registry.example.com","authorizationEnv":"LSF_PRIVATE_NPM_AUTH"}]}`. Credentials reach only that explicit resolver; ordinary compilation consumes verified objects and does not read project/home npm configuration. An update, removal, lock edit, selected condition/profile change, missing object or altered dependency invalidates relevant input identities and requires capture/review again.

On Linux, the policy can additionally select `"tlsTrust":{"caFile":"trust/roots.pem"}`. The project-relative public PEM bundle is limited to 512 KiB and 256 certificates; keys, extra data, aliases and infrastructure paths are rejected. Only the native npm child receives an owned bundle through [`cafile`](https://docs.npmjs.com/cli/v11/using-npm/config/#cafile), with [`strict-ssl`](https://docs.npmjs.com/cli/v11/using-npm/config/#strict-ssl) retained. Machine trust and Node loader settings are unchanged. Include all public roots required by the explicitly selected registries in this bundle. This explicit profile refuses on non-Linux resolver hosts.

Both native lock and capture recheck the source CA, owned copy, strict-verification setting and trust helper recipe. Capture includes the CA as a native lock input and records its logical path, size, digest and `npm-linux-explicit-registry-ca-v1` identity. Offline verification rejects changed trust bytes while preserving the accepted lock. Use the same policy for `lock` and `resolve`; keep the policy and credentials outside the project. Source controls pass with modeled native boundaries; authenticated private TLS acquisition and signed lifecycle qualification remain pending.

A registry policy may select one default registry and one entry per explicit
scope. Repeating either selector fails with `npm-registry-scope-ambiguous` before
native lock generation or capture dispatch, even when the repeated endpoints
match. One default plus distinct scopes remains supported; rejected policies
preserve the accepted closure, native locks and SDK bytes.

The required TypeScript CI qualifier uses these normal add/lock/resolve/review commands and checks that update/removal invalidates the accepted graph until exact reviewed declarations are restored. It adds an external developer-owned conditional ESM/CommonJS module using real `@jridgewell/trace-mapping` transitives and immutable UTF-8 JSON/text/binary resources, removes the original external sources, compiles the reviewed closure, and sends the result through the existing signing/admission/node workflow. Exact-head passing receipts are required before claiming that qualification. Native Node tests are controls; additional async/runtime, generator, private-feed, snapshot-effect and full denial/recovery matrices remain separate acceptance work.

The [native authoring control](../testing/evidence/npm-native-authoring-2026-10-16.json) records exact Windows Node/npm and source inputs for a direct/transitive local graph, exact review and offline verification after the original locations become unavailable. It does not qualify an emitted component or a Linux network namespace. The normal signed component gate remains separate.

The delivered signed-watch programme runs in the existing TypeScript developer-tools lane using the shipped Python, recipe and verified compiler archive in a fresh unprivileged account. It captures two outside ESM packages, removes their original directories before compilation, requires output42, then changes both versions and requires43 after native lock/capture/exact review. Removal requires the dependency-free result. Each changed graph must pass the normal recipe-trust boundary and refuses the previous component-bound signature; each new signed test workspace requires fresh explicit fixture consent. Exactly three deployments and normal reaped shutdowns are required. A failed or uncertain down is fenced before dispatch and is never replayed. Only a bounded public receipt is uploaded; private signing/workspace state stays on the ephemeral runner. The default synchronous runtime profile and all original workflow budgets remain unchanged. Watch scenarios retain the validated template's separate deadlines: the maintained node ceiling is 120 seconds because cold compilation is charged to the activation, while the portable guest deadline is five seconds. This maintained programme requires its own actual passing hosted receipts before it supplies watch qualification.

The maintained private-registry campaign uses previously unknown scoped parent and transitive packages,
two exact versions, required peers, a Linux-selected then platform-excluded optional package,
conditional exports, ESM/CJS, UTF-8 and binary resources. Conditional export keys retain native order.
The peer and selected optional package contribute observable values; a missing required peer must refuse.
It exercises normal add,
lock, resolve, digest review, update and remove; missing/wrong authentication, untrusted TLS, changed
archive integrity, missing/tampered captured objects and changed public CA inputs must refuse while
preserving the accepted lock. Credentials and the owned HTTPS peer are removed before offline builds.
The campaign reuses the preceding exact native five-product bundle and four companion capsules.
Both initial offline builds must preserve source, recipe, compiler and selected module inputs and
pass signed execution independently. Wizer retains owned temporary argv/home paths in its image;
byte-identical component reproducibility remains unclaimed. The campaign
retains the original normal tutorial/fault/HTTP programme, and adds three fresh signed calls per phase
and for the separately signed initial offline rebuild
with selected-revision, process-reaping, physical-owner and provider-idle checks. Source controls and
the local HTTPS peer are checked. Pinned esbuild/Node controls pass both conditional branches and
all selected resources in twelve fresh processes; these controls do not qualify npm acquisition or
an emitted component. Native capture, offline components and signed execution remain
pending until its retained hosted `latent.npm.private-dependencies.qualification.v1` receipt passes.
This finite campaign does not close generator, watch/recovery or the full #685 acceptance by itself.
