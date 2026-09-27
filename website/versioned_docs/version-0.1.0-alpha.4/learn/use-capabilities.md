# Use capabilities in your capsule

A capsule can calculate a result from its input without any outside access.
To request an HTTP page, store an object or read a secret, it asks the node for
a **capability**. The node checks the application's permission before doing that
work. This keeps a program's authority separate from the language it is written in.

Start with [Creating a capsule](../component-development/creating-a-capsule.md).
This page explains the next design and testing steps when you add an external
dependency to your own project. For a ready-made source demonstration of HTTP
and storage, see the [provider integration exercise](../development/provider-source-walkthrough.md).

## Choose the operation your application needs

| Your application needs to | Capability | SDK and behavior reference |
| --- | --- | --- |
| Request an HTTP service | Buffered HTTP | [HTTP requests](../runtime/outbound-http.md) |
| Stream a large HTTP body | Streaming HTTP | [Streaming HTTP](../runtime/streaming-http.md) |
| Store and read immutable data | Blob storage | [Immutable blobs](../runtime/local-blobs.md) |
| Call another capsule | Local service calls | [Local invocation](../runtime/local-service-invocation.md) |
| Read a named secret | Secrets | [Secrets](../runtime/local-secrets.md) |
| Report measurements | Custom metrics | [Metrics](../runtime/custom-metrics.md) |
| Read time or obtain randomness | Clocks or random bytes | [Guest SDK reference](../component-development/guest-sdk.md) |

Each language's guest SDK wraps these typed interfaces. The [guest SDK reference](../component-development/guest-sdk.md)
links the Rust, C, TypeScript, Go, Java and C# APIs and explains how to release
their resources. This is different from the client SDK used by a separate
application to call your capsule.

## Import a capability and handle its result

For example, a capsule that needs buffered HTTP imports this interface in its
WIT world, alongside its own exported functions:

```wit
import latent:http/client@0.2.0;
```

Add the matching maintained WIT dependency and use your language's HTTP wrapper
from the guest SDK. Handle its success and error results. A request can fail
because the destination is denied, the service is unavailable, or a resource
limit was reached. Do not treat those results as an empty successful response.

Three things must agree before the request can run:

1. The node has an HTTP provider installed.
2. Your deployed capsule has a grant for that capability.
3. The grant permits the requested destination, method and path within its budget.

Importing the interface does not grant internet access. Likewise, a blob handle
is not an arbitrary filesystem path, and a secret name is not permission to read
every secret on the node.

## Test the project in a disposable workspace

Continue using the same `dev` commands as the capsule tutorial. Create a fresh
`test-` workspace for a project with capability tests, install its language tools,
and review its recipe. Then build it:

```bash
dev trust --workspace "$Workspace" --project "$Project"
dev build --workspace "$Workspace" --project "$Project"
```

For local tests, the developer toolkit can supply explicit HTTP, blob, secret,
metric, local-service and event fixtures. Your project must contain a fixture
configuration and scenarios that declare the fixture they need. Describe them
using the [fixture format](../reference/developer-test-fixtures.md), including
inputs and expected results for your own exported functions. The greeting
template alone does not become an HTTP application by enabling a fixture.

With an HTTP project's fixture saved at `tests/http-fixture.json`, prepare the
stopped node **before its first deployment**:

```bash
dev prepare-test --workspace "$Workspace" --consent-test-fixtures --admission signed-fixture --fixtures "$Project/tests/http-fixture.json"
```

This explicitly permits a disposable test setup and binds its selected build.
Start foreground `up` in a second terminal as shown in the capsule tutorial,
then deploy and test in your working terminal:

```bash
dev deploy --workspace "$Workspace"
dev test --workspace "$Workspace" --environment node
dev logs --workspace "$Workspace"
```

Check both allowed and denied cases. A denied destination should produce the
expected error without contacting it. After a valid request, check the actual
typed answer too; a successful connection alone is insufficient. Signed fixtures
expire after 30 minutes and do not authorize a changed build. Use a fresh
disposable workspace for either change.

## Configure a persistent node

Development fixtures are for repeatable local tests. To connect to a real service,
use [standalone provider configuration](../reference/standalone-providers.md)
and [provider operations](../how-to/operate-capability-providers.md). Keep provider
credentials in protected node configuration, outside source files and capsule
packages. Grant only the destinations and operations the application needs.

A lost response can leave an operation's outcome unknown. Use the original
operation's recovery path instead of sending the request again. See
[developer recovery](../how-to/developer-commands.md#inspect-and-recover).

## Stop your test node

```bash
dev down --workspace "$Workspace"
dev status --workspace "$Workspace"
```

Expect the workspace to be stopped. The [cleanup guide](../how-to/developer-commands.md#stop-and-remove-workspaces)
explains how to retain its data or purge the exact disposable workspace.
