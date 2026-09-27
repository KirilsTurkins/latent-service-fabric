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

The integrated deployment walkthrough is being completed in issue
[#632](https://github.com/KirilsTurkins/latent-service-fabric/issues/632). Building
this source alone does not configure ingress, TLS trust, capability policy,
credential injection or publication signing. This example is a public status
endpoint; it does not implement application sessions or a confidential user API.
