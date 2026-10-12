# Approved C source and header generation

Run a generator as a separate reviewed authoring step. Ordinary C builds keep
arbitrary configure, shell and compiler hooks disabled. The approved stage can
produce a fresh subtree of `.c` and `.h` files under `src`; it cannot replace
existing sources, SDK files, libraries or compiler inputs.

Create a request outside captured source, or under the project's excluded
`target` directory:

```bash
python3 tools/c_capsule.py generator-request ./my-c \
  --candidate ./my-c/target/generator-request.json \
  --tool /absolute/path/header-generator --tool-version 1.0 \
  --inputs /absolute/path/generator-inputs --destination src/generated
```

Review the exact request's source, SDK, tool, arguments, input digests and
limits. Then approve that request digest explicitly:

```bash
python3 tools/c_capsule.py generate ./my-c \
  --candidate ./my-c/target/generator-request.json \
  --expect sha256:<reviewed-request-digest>
```

The stage uses the existing Linux namespace executor. Network access and
inherited credentials are absent; approved inputs are read only. Limits remain
at most 60 seconds and 1 MiB of process output. An unsupported containment host,
changed request, source or tool, failed command, unconfirmed cleanup, binary
output or path collision prevents adoption. The failed attempt stays in the
private authoring directory without automatic replay.

Successful generation records the exact output bytes in
`c-generated-inputs.json`. Normal build, dependency status, test and watch
validation reject missing or changed generated files. They consume captured
files offline without executing the original tool again. Include a generated
header from ordinary source, for example `#include "generated/value.h"`.

Generated source receives the same compiler, Wasm target, final-import,
invocation budget and operator authority checks as other application source.
Generation does not grant runtime capabilities or certify library support.
