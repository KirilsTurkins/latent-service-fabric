# Static site and a TypeScript API

This example has two independently publishable parts: `site/` contains browser
files, and `capsule/` handles a small public availability API. The API makes one
host-owned HTTPS request to a fixed upstream. It returns a fixed status message;
it never returns upstream response bodies, cookies or credentials.

Complete [developer setup](../../docs/start/developer-setup.md) and
[workspace setup](../../docs/start/development-workspace.md), selecting
TypeScript and a fresh disposable workspace. Keep that terminal's `dev` command
and setup variables. With Node 24 installed, run from this example directory:

```sh
dev init "$Project" --bundle "$Bundle" --template "typescript/greeting" --template-sha256 "$GreetingTemplate"
node prepare-project.mjs "$Project" "${Project}-api"
dev trust --workspace "$Workspace" --project "${Project}-api"
dev build --workspace "$Workspace" --project "${Project}-api"
```

Review `app/src/main.ts` before trusting the build. Its upstream origin, method,
path and deadline are application source, never values chosen by browser input.
Trusting a build does not authorize an outbound connection or publish anything.

The source tests cover response filtering and rejection before dispatch:

```sh
node --test status.test.mjs
```

Next, follow [Serve a static site and a TypeScript API](../../docs/how-to/static-site-and-api.md).
The example launcher uses your completed build, publishes both parts separately,
and opens a local site with a working button. It creates temporary test identities,
a protected native node and a local TLS upstream, then removes its own temporary
state on exit. Your developer workspace stays available for editing and rebuilding.

The fixed upstream is `https://status.backend.test:8443/health`. Only the native
provider holds its credential. The capsule forwards no browser headers and returns
only a fixed public availability message. Application sessions and confidential
user APIs need their own authentication and authorization design.
