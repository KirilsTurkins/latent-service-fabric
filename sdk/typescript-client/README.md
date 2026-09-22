# TypeScript client

The browser-safe package root exposes the shared
[eight-operation profile](../profile/README.md) as `profile`. Its obsolete
root-level invocation models, `LatentClient` and guest-context scaffolding have
been removed during alpha. Import request, response and publication types from
`profile`. The separate
`@latent/sdk/node` entry implements that profile with a bounded Node.js HTTP/2
Protobuf client. It is intentionally unavailable through a browser export
condition. Do not bundle the Node transport, client bearer token, management
RPCs or provider credentials into an application.

## Node.js

Use Node.js 24.19.x, the checked-in lockfile and TypeScript 7.0.2. The selected
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

### Maintained guest example

After the operator admits/deploys the maintained Rust HTTP/blob guests with
their matching provider bindings and grants, run the language-native example:

```sh
node sdk/typescript-client/examples/provider-client.mjs \
  http://127.0.0.1:9080 tests /home/operator/.config/latent/client-token \
  node-http-001 http generic guest-http http://localhost:8080/allowed
node sdk/typescript-client/examples/provider-client.mjs \
  http://127.0.0.1:9080 tests /home/operator/.config/latent/client-token \
  node-blob-001 blob generic guest-blob
node sdk/typescript-client/examples/provider-client.mjs \
  http://127.0.0.1:9080 tests /home/operator/.config/latent/client-token \
  node-http-001 status
```

Use the actual service/route, approved URL and client token file. The example
requires Linux x86-64, an effective-user-owned 0700 parent directory and a
0600 regular single-link file with no newline. It walks directory descriptors,
rejects symlinks/special files, bounds reads and checks opened-file identity
before/after reading. This deliberately narrow example profile is not the
node's complete protected-configuration API. It never reads an ambient token.

The example sends supported WIT-value bytes through `Invoke`; only the guest
may call HTTP/blob with node-held provider credentials. It prints bounded
outcome JSON and decimal guest results (`2201` for the controlled HTTP fixture,
`4` for the maintained blob guest), not arbitrary application output. `cancel`
in place of `status` sends an explicit application cancellation with the same
known ID. No invocation is automatically replayed on an uncertain response.

The separate-node participant is `tests/provider-workflow.mjs`; it exercises
the same request builder plus all eight profile operations. Its real-node
execution uses the shared real-node workflow, with receipts retained by PR #366.
The example's RPC timeout is explicitly 5,000 milliseconds, matching the
qualified node's execution/transport ceiling rather than the generic SDK default.

## Browser boundary

Browser application traffic belongs on the approved shared HTTP ingress and
its explicit origin/authentication policy, never on the node management
listener. The Node package is not a privileged RPC proxy, Angular renderer,
credential broker or new browser authentication mechanism. The maintained
Angular build/rendering path remains owned by the web profile.

The maintained [Angular browser companion](../../examples/browser-boundary/client/application.ts)
calls only `POST /api/greeting` on its own origin. It omits credentials, rejects
redirects, copies at most 256 response bytes and uses one 3-second local deadline.
The existing Angular fixture supplies rendering/hydration; the client entry alone
injects the browser fetch function. No Node SDK import or generic RPC proxy enters
the bundle. This is an anonymous application example, not browser user login.

The controlled-peer suite, native provider workflow and browser test are separate
evidence. Linux passes 20 transport tests and all 18 real-provider assertions,
with nine retained activations and four physically closed upstream holds. The
[actual browser evidence](../../docs/testing/sdk-browser-application.md) additionally
proves the real web WIT component, exact public route, omitted cookies/credentials,
rejected management paths and hydration/navigation through shared HTTP ingress.
Its controlled Node SSR output is not production Angular Wasm SSR qualification;
that remains #226/#236. Exact-head CI and central review remain required.

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
