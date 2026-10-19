# Explicit Go source generators


Go builds never run `go generate` automatically. To run a reviewed executable
before a build, create an exact request with its tool version, input directory,
arguments and a fresh destination beneath `src`:

```bash
python3 tools/go_capsule.py generator-request "$PROJECT" \
  --tool "$REVIEWED_GENERATOR" --tool-version 1 \
  --inputs "$GENERATOR_INPUTS" --destination src/generated \
  --candidate "$PROJECT/target/generator-request.json"
```

Inspect the private request and approve the reported `requestDigest` explicitly:

```bash
python3 tools/go_capsule.py generate "$PROJECT" \
  --candidate "$PROJECT/target/generator-request.json" --expect "$REQUEST_DIGEST"
```

The selected executable runs only in the existing Linux Bubblewrap namespace,
with read-only inputs, a fresh output directory, no inherited credentials or
network, and at most 60 seconds and 1 MiB of process output. Arguments can be
selected with repeated `--arg=VALUE` options. Each request binds the exact tool,
input files, current source, SDK and destination; changing one requires a new
request and approval. The executor does not install or provision tools.

Only successful, reaped executions producing Go source files are adopted into
the new destination. Existing source and SDK files are retained. The
`go-generated-inputs.json` record binds each generated file and the execution
receipt. Subsequent normal builds verify these files and retain the generator
material identity without rerunning the executable or requiring its original
input paths. Editing generated files requires a new captured generation record.
Failed attempts retain private evidence under `target/go-dependency-authoring`;
deadline and output failures retain their cleanup status and are never replayed
automatically. Frontend recipe and dependency review requirements still apply.

## Maintained signed qualification

The opt-in `--approved-generator` selection on
`tools/qualify_go_capsules.py` requires `--application-dependencies`; it does not
change the normal application build or implicitly run `go generate`.
The maintained fixture uses the ordinary request and exact approval commands
above. Wrong approval and changed selected inputs must refuse before execution
or source adoption. The approved generator checks that the parent environment,
an owned host-only file and the parent's loopback listener are unavailable in
its existing namespace, then writes one Go source file from the selected input.
Cleanup must be confirmed before adoption. The original generator and input
file are removed before component compilation.

The generated function uses request text to derive a numeric result from its
UTF-8 byte length and returns the selected nonce and text. Three additional
signed component calls must return those exact values, including a Unicode
case where byte and rune counts differ. Every call binds the full selected
global route/revision tuple and must be reaped, idle and free of outbound,
child-call or effect consumption. The original 27 cases and all existing fault,
HTTP, admission and shutdown checks remain mandatory.

Both ordinary offline builds retain the same source/SDK identities and exact
`go-generator-inputs` digest and size in their signable build observations.
Source controls model the process boundary and verify the real request,
approval, adoption and later source validation. They do not establish actual
namespace execution or emitted-component compatibility. Only a successful
exact-source hosted qualification supplies those results. This is a finite
generator/dependency slice for #678/#686; both broader tickets remain open.
