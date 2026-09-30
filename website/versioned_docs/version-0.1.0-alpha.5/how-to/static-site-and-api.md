# Serve a static site and a TypeScript API

Build a page with a **Check status** button. LSF serves the HTML, CSS and browser
JavaScript from a static publication. The button calls a TypeScript capsule on
the same host; that capsule asks an approved HTTPS backend whether it is available.
You can release the site and the API independently.

## Build the API

Complete [developer setup](../start/developer-setup.md) and
[workspace setup](../start/development-workspace.md) with TypeScript and a fresh
workspace named `test-static-api`. Keep the `dev` command and setup variables
from those guides. Install Node 24 for the small example preparation command.

From the repository's `examples/static-api` directory:

```sh
dev init "$Project" --bundle "$Bundle" --template "typescript/greeting" --template-sha256 "$GreetingTemplate"
node prepare-project.mjs "$Project" "${Project}-api"
dev trust --workspace "$Workspace" --project "${Project}-api"
dev build --workspace "$Workspace" --project "${Project}-api"
```

Set `$Workspace` to `test-static-api` in your setup. The preparation command copies
your greeting project into a new API project, keeping the SDK and compiler choices
from your installed developer tools. Read `app/src/main.ts` and `app/src/status.ts`
in the new project before running `dev trust`.

The API requests one fixed URL, `https://status.backend.test:8443/health`.
A successful backend response becomes `{"status":"available"}`. The API never
returns the backend's response body, cookies or credentials.

## Open the complete example

Run the launcher from the repository root **inside the Linux backend that owns
the workspace**, as the same user. On Windows, open that workspace's WSL terminal;
the installed developer frontend continues to handle builds from your usual editor.
The backend needs Python 3, Node 24 and OpenSSL. Keep local port 8443 free.

```sh
python3 tools/static_api/demo.py --workspace test-static-api --disposable-test-keys
```

The first start prepares the capsule's native code and can take a little longer
than later requests. Open the local URL printed by the launcher and click
**Check status**. The page should say **Service is available.**

The launcher creates a separate temporary node, signs your completed capsule and
the site with disposable test keys, and publishes them independently. It also
starts a small local HTTPS backend. Its certificate is trusted explicitly, and
its credential lives in the node's private configuration. Nothing is published
to a registry or another machine. This temporary example stops after ten minutes
or when you press **Ctrl+C**.

Edit the page in `examples/static-api/site/` and run the launcher again to see a
new static publication. To change the API, edit your API project, run `dev build`
again, then restart the launcher. The site and capsule remain separate packages.

## Understand the route and credential boundaries

The `/api` prefix belongs to the API. The broader `/` prefix serves the static
site and its SPA fallback. `/api/missing` returns an API error; it never returns
the page's HTML. The API accepts GET and HEAD. Other methods are denied without
contacting the backend.

The native HTTP provider authorizes the exact upstream origin, GET method and
`/health` path. It verifies TLS, injects the approved `status-upstream` credential,
and follows no redirects. The browser cannot choose a customer, destination,
credential or forwarded identity. Browser cookies are ignored by this public
status example and are not forwarded upstream. Platform operator and invocation
tokens belong to LSF's control and invocation interfaces; do not put them in the
page or use them as application sessions.

The upstream call has a 1.5-second deadline and a budget of one outbound request.
A denied policy or an exhausted budget sends no request. A failed or redirected
backend response becomes a fixed unavailable message. When the browser disconnects,
the host cancels and releases the outstanding call. A lost response after dispatch
can have an uncertain outcome; the example never repeats that operation silently.

## Use the pattern with your own backend

Replace the fixed URL in `app/src/main.ts`, then rebuild with `dev build`. Your
operator must separately approve the matching destination, TLS roots, credential
reference, method and path in the
[standalone provider configuration](../reference/standalone-providers.md).
An SDK import or a successful build grants no network access.

For a maintained deployment:

1. Supply your organization's publisher and builder evidence for the capsule.
   Publish it with `latent release publish-package`, then select that exact
   publication in its deployment.
2. Package and publish the browser files using the
   [static release workflow](../operations/static-release-workflow.md).
3. Apply a provider-binding policy using the descriptor from the node's `ready`
   record, and grant only the intended service, publication and browser principal.
   Follow [capability provider operation](operate-capability-providers.md).
4. Apply the API's `/api` GET/HEAD and rejection routes before the site's `/`
   routes. Pin API triggers to the deployed revision and generation using the
   [HTTP trigger reference](../reference/http-triggers.md).
5. Use verified HTTPS ingress and reconcile both GET and HEAD when changing a
   publication. Follow the [route-set release guide](../operations/static-route-sets.md)
   for uncertain outcomes and explicit rollback.

The example's generated test identities and local backend are for learning only.
Keep production credentials in the node's protected store. This public availability
API does not implement login, customer entitlements, application sessions or
confidential response forwarding. A protected application must design and test
those decisions explicitly, for example using its own session cookie and a
narrowly authorized authentication service. Paths on one origin are not customer
security isolation.
