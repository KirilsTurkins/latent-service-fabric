# Approved Java source generators and annotation processors

Java compilation disables annotation processing with `-proc:none`. A captured
JAR does not authorize its processor, compiler extension, Gradle/Maven plugin
or build script to execute. To generate source, select a separately reviewed
executable or processor launcher and capture an exact approval request:

```bash
python3 tools/java_capsule.py generator-request "$PROJECT" \
  --tool "$REVIEWED_LAUNCHER" --tool-version "$TOOL_VERSION" \
  --inputs "$CAPTURED_TOOL_INPUTS" --destination src/generated \
  --candidate "$PROJECT/target/generator-request.json"
```

The private input directory should contain the selected processor JARs and
their transitive tool dependencies, source inputs, configuration and toolchain
identity. Use the pinned JDK for a Java processor launcher. All required public
host tools must already be provisioned; this command does not install them.
The launcher uses `/inputs` read-only and writes Java source beneath `/outputs`.
For example, an explicitly reviewed launcher can invoke the pinned `javac`
with `-proc:only`, an explicit `-processor` and `/inputs` processor path,
`-s /outputs`, and an owned class-output path beneath `/tmp`.

Review the exact request bytes, including executable/input digests, arguments,
version, SDK/source/descriptor identities, destination and finite limits.
Approve the reported `requestDigest` explicitly:

```bash
python3 tools/java_capsule.py generate "$PROJECT" \
  --candidate "$PROJECT/target/generator-request.json" --expect "$REQUEST_DIGEST"
```

Repeated `--arg=VALUE` options select launcher arguments. The existing Linux
Bubblewrap executor denies network and inherited home, credentials and signing
keys, exposes only read-only host sysroots, selected tool/inputs and owned
output/tmp, and limits each process to 60 seconds and 1 MiB of diagnostic output.
Existing input/archive, output and application-source limits also apply. Hosts
without working unprivileged namespaces fail closed.

Only successful, physically reaped executions producing portable Java source
paths enter a fresh direct child of `src`. Binary, resource, linked, empty or
over-limit output is rejected before adoption. The command never replaces an
existing source directory or SDK input. Changing the selected tool, input,
source, captured dependency selection or SDK requires a fresh request and
approval. Failures retain private execution/cleanup evidence under
`target/java-dependency-authoring` and are never replayed automatically.

`java-generated-inputs.json` records the exact tool/input/execution identities,
receipt digest and each generated file's path, digest and size. Normal
build/test/watch verifies the captured files and records that material in build
provenance. The original launcher and input paths are unnecessary for subsequent
offline builds, and annotation processing remains disabled there. Generated
source still goes through the ordinary pinned TeaVM C/component recipe and
normal final WIT/engine-profile checks; generating it is not component or runtime
qualification. TeaVM extension services and application build-script injection
remain rejected.
