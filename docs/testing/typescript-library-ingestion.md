# TypeScript library ingestion qualification

The [16 October 2026 evidence](evidence/typescript-dependency-ingestion-2026-10-16.json)
records actual npm artifacts compiled through the maintained TypeScript, esbuild,
Jco and ComponentizeJS recipe and invoked on the ordinary enforced-admission
node. The explicit network acquisition captures `@jridgewell/trace-mapping`
0.3.31 and its selected `resolve-uri` and `sourcemap-codec` transitives. A new
developer-owned local module imports that library through CommonJS and exposes
an ESM entry point with declaration, JSON, UTF-8, text and binary resources.
It needs no catalogue registration or LSF dispatch change. Its `prepare` script
would fail if run; acquisition disables lifecycle execution.

The original local package is deleted after capture. Normal compilation runs
with Docker networking disabled and uses the reviewed closure and exact pinned
compiler. The signed component returns `Hello, SDK!`, the declared empty-name
error and `Hello, Ada!`. A module-global counter rejects reused activation state.
Unsigned publication is denied. Missing and tampered original transitive archive
bytes are denied before compilation; exact restoration preserves the accepted
lock. Complete cell, topology, queue and quota observations return idle after
every invocation, and normal shutdown retires runtime owners.

The [qualifier](../../tools/qualify_typescript_dependencies.py) separates explicit
acquisition from offline compilation and execution. Use the pinned Node 24.19.0,
wasm-tools 1.254.0, compiler lock, working Bubblewrap namespaces and an exact
ordinary native tuple. Acquisition uses normal native npm resolution:

```bash
python tools/qualify_typescript_dependencies.py \
  --resolve-only --output "$QUALIFICATION"
```

Carry that captured output into a network-disabled host, retaining the exact
source recipe and compiler inputs, then run:

```bash
python tools/qualify_typescript_dependencies.py --offline \
  --output "$QUALIFICATION" --tools "$TYPESCRIPT_TOOLS" \
  --native-directory "$NATIVE" --native-tuple "$NATIVE/native-tuple.json"
```

All 98 recipe files match their Git objects and the qualifier records its own
bytes before and after execution. This gate covers `spidermonkey-public-sync-v1`.
It does not qualify the native Promise/import engine, a publisher-authenticated
installation, private registry credentials, installed update/remove/watch,
generator-emitted components or memory/fuel/cancellation recovery. Those remain
separate acceptance work in #685 and its runtime dependencies.

The maintained TypeScript workflow now also runs this integrity programme after
its preceding maintained dependency qualification. `--prepared-qualification` may
select only that successful, exact-source observation with its five frozen native
products; stale source, incomplete results and changed products fail explicitly.
The original explicit `--native-directory` plus `--native-tuple` route remains
available. The two selection routes cannot be combined.

This added hosted gate performs missing/tampered original-transitive denials,
then two normal builds from the same captured closure in separate fresh compiler
workspaces. Compiler namespaces deny network access. It signs and executes the
first build, verifies fresh module state and normal owner retirement, and retains
the second build receipt without claiming reproducibility. Both pinned compiler
inputs and captured source remain unchanged. All original workflow commands and
its 75-minute deadline remain. The historical evidence above records the earlier
single-build qualifier; a newly added hosted gate is not an assertion that its
current run passed.
