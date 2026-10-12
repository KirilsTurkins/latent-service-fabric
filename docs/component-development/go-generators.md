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
