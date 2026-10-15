# C library ingestion qualification

`tools/qualify_c_library_ingestion.py` separates explicit source acquisition from
offline component qualification. It reuses the ordinary C builder, captured
compiler namespaces, source/static-archive fixture, signed node workflow and
adversarial object/generator controls. It does not rebuild the native workspace
for every application. Supply the five immutable ordinary/default native
products and their completed build receipt from the maintained native capture.
Development-test-node or outbound-stream products are rejected.

On the pinned Linux compiler host, acquire the exact parser and independent
developer library/resource closure into a fresh outside-checkout directory:

```bash
python3 tools/qualify_c_library_ingestion.py capture --output /work/c-library-capture
```

Capture removes the original developer source/header/resource bytes after
placing them in the verified store. Run the second command on the same private
compiler host with external networking disabled, keeping loopback available for
the normal node's controlled HTTP provider. The selected compiler binaries and
Zig sysroot must already be installed at their maintained pinned versions:

```bash
python3 tools/qualify_c_library_ingestion.py execute \
  --inputs /work/c-library-capture --output /work/c-library-execution \
  --native-directory /work/ordinary-native --native-tuple /work/ordinary-native/native-tuple.json \
  --zig /tools/zig/zig --wit-bindgen /tools/wit-bindgen --wasm-tools /tools/wasm-tools
```

Execution first checks every captured project before selecting native products
or dispatching compilation. It builds the five existing C authoring scenarios,
rebuilds the library application from the closed inputs, and executes the normal
signed-node workflow. It then builds the same source library into a verified Wasm
static archive under a different dependency identity, builds/signs the resulting
capsule and runs the same node controls. The original target, SDK and guest
budgets remain in force. Existing adversarial controls cover actual wrong-target
objects, duplicate symbols, stale checkpoint profiles, missing/tampered closure,
archive bounds and isolated generated-header behavior.

Each failure retains `FAILED.json` and its original stage; use a new output for
another attempt. `qualification.json` is written only after both node workflows,
the object/generator controls and final source/tool/native integrity checks pass.
Raw private signing material and temporary credentials are not public evidence.
The result distinguishes source and static executions, component identities,
offline byte equality, physical node/provider cleanup and native input sources.

This selection does not qualify installed frontend dependency watch/update/remove,
C pthread scheduling or default socket clients. Those remain separate acceptance
requirements. The complete existing C authoring and generated-library CI owners
remain required; this helper does not replace them or their direct SDK controls.
