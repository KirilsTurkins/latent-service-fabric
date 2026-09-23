# TypeScript guest SDK

This work implements issue #546 on a separate guest-authoring path. It is not
the Node client transport and does not enable an unrestricted Node or browser
runtime inside an activation.

The runtime boundary preserves full-width WIT integers as `bigint`, explicit
option/result cases, Unicode scalars, byte arrays and nominal resource owners.
Each invocation owns its scope; calls outside that scope fail. Owned arguments
move once, borrowed arguments retain their owners, and resource destructors are
not retried. Primitive blob handles require explicit asynchronous close or seal.
Secret helpers zero their owned byte array; application-created copies retain
their own lifetime. Host grants and budgets remain authoritative.

## Validation status

The local runtime tests exercise JavaScript value and ownership behavior using
a deliberately synthetic broker. They are not native async, provider, signed
admission or real-node evidence. The general component adapter and its native
qualification must pass before this SDK is described as a supported execution
profile or issue #546 is closed.

Compile and test the runtime with the reviewed TypeScript compiler:

```sh
node examples/renderer-profile/node_modules/typescript/bin/tsc \
  --target ES2022 --module NodeNext --moduleResolution NodeNext --strict \
  --lib ES2022 --outDir target/typescript-guest-runtime \
  sdk/typescript-guest/runtime/*.ts
printf '{"type":"module"}\n' > target/typescript-guest-runtime/package.json
LSF_TYPESCRIPT_RUNTIME="$PWD/target/typescript-guest-runtime" \
  node --test sdk/typescript-guest/tests/runtime.test.mjs
```

The compiler is a build-time tool only. Guest code has no ambient clock, random,
network, process, filesystem, browser DOM, timer or worker authority. Application
module loading and native async qualification are separate build checks.
