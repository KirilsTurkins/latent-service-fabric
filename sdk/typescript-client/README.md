# TypeScript client

The browser-safe package root contains transport-neutral interfaces and the
shared [eight-operation profile](../profile/README.md). The separate
`@latent/sdk/node` entry implements that profile with a bounded Node.js HTTP/2
Protobuf client. It is intentionally unavailable through a browser export
condition. Do not bundle the Node transport, client bearer token, management
RPCs or provider credentials into an application.

## Node.js

Use Node.js 24.19.x, the checked-in lockfile and TypeScript 5.8.3. The selected
node transport is explicitly configured plaintext **numeric loopback**, not a
remote/TLS endpoint or a browser API. Endpoint, tenant and client credential
are mandatory. The transport does not inspect environment variables, cookies,
local storage, proxy settings or credential files. The embedding application
must provision a protected client credential; the node separately owns all
provider credentials.

```ts
import { RpcClient } from "@latent/sdk/node";

async function inspect(endpoint: string, credential: Uint8Array) {
  const client = new RpcClient({ endpoint, tenant: "tests", credential });
  try {
    const page = await client.listPolicies({
      recordKind: 1,
      page: { pageSize: 8 },
    }, { timeoutMillis: 3000n });
    return page.value;
  } finally {
    await client.shutdown();
  }
}
```

All `uint64` fields are `bigint`, including optional zero, generations,
deadlines, audit attempts and resource counters. Use the profile's canonical
decimal helpers at an external JSON boundary; do not cast these values to
`number`. Payloads remain opaque owned bytes. See the complete
[transport and recovery contract](../../docs/reference/typescript-client.md)
before handling invocation, cancellation or mutation failures.

## Browser boundary

Browser application traffic belongs on the approved shared HTTP ingress and
its explicit origin/authentication policy, never on the node management
listener. The Node package is not a privileged RPC proxy, Angular renderer,
credential broker or new browser authentication mechanism. The maintained
Angular build/rendering path remains owned by the web profile.

The current controlled-peer suite is **not** real-node/provider or browser
qualification. Phase 3 #230 remains open until the separate real-node SDK
workflow and public-ingress browser example are integrated and evidenced.

## Reproducible checks

```sh
npm --prefix sdk/typescript-client ci --ignore-scripts
npm --prefix sdk/typescript-client run test:semantic
npm --prefix sdk/typescript-client run test:transport
```

The normal SDK validator runs both suites. Protocol data is generated from
the selected authoritative `.proto` files, not handwritten endpoint JSON:

```sh
python tools/generate_node_rpc.py --protoc /path/to/locked/protoc --check
```

Use the repository's locked `protoc-bin-vendored` 3.2.0 compiler
(`libprotoc 31.1`); omit `--check` only to regenerate. Source identities normalize
checkout line endings, and tests verify all eight service/method/message
signatures. The pinned Protobuf runtime consumes compiled descriptors without
runtime file loading or protocol compilation.
