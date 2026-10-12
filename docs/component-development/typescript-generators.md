# Approved TypeScript source generators and scripts

Dependency capture and ordinary builds keep package lifecycle scripts and
application compiler/bundler plugins disabled. To generate TypeScript source,
select a reviewed executable or script launcher in a separate explicit stage:

```bash
python3 tools/typescript_capsule.py generator-request "$PROJECT" \
  --tool "$REVIEWED_LAUNCHER" --tool-version "$TOOL_VERSION" \
  --inputs "$CAPTURED_TOOL_INPUTS" --destination src/generated \
  --candidate "$PROJECT/target/generator-request.json"
```

Capture the selected script, tool dependencies, configuration and source inputs
in the read-only input directory. Select any launcher arguments with repeated
`--arg=VALUE` options. Required public host tools must already be provisioned;
this stage does not install packages, discover hooks, select scripts from
`package.json`, or enable plugins inside the ordinary component compiler.

Review the exact executable/input digests, version, arguments, current source,
reviewed dependency selection, SDK/descriptor identity, destination and finite
limits in the private request. Approve its reported `requestDigest` explicitly:

```bash
python3 tools/typescript_capsule.py generate "$PROJECT" \
  --candidate "$PROJECT/target/generator-request.json" --expect "$REQUEST_DIGEST"
```

The existing Linux Bubblewrap namespace denies network and inherited home,
credentials and signing keys. It exposes read-only host sysroots, the selected
tool as `/tool`, read-only `/inputs`, fresh writable `/outputs` and owned `/tmp`.
Each execution has at most 60 seconds and 1 MiB of process diagnostic output;
the existing input/output and application-source limits also apply. Hosts
without working unprivileged namespaces fail closed.

Only successful, reaped executions producing portable `.ts` source files enter
a fresh direct child of `src`. Binary, linked, empty, resource or over-limit
output is rejected before adoption. Existing source and SDK files are never
replaced. Changing selected tool/input/source/dependency/SDK bytes requires a
new request and approval. Failed attempts retain private execution and cleanup
receipts under `target/npm-dependency-authoring` without automatic replay.

`typescript-generated-inputs.json` binds each generated file and its exact
tool/input/execution identities and receipt digest. Normal build/test/watch
verifies those source bytes, includes the record in build materials, and reuses
them offline without the original launcher or input paths. The ordinary pinned
TypeScript/component recipe still typechecks and inspects the final module,
WIT and selected engine profile. Generation does not qualify pending Promise
exports, standard-runtime operations or a new network/filesystem capability.
The current ordinary-value profile and default script denial are retained.
