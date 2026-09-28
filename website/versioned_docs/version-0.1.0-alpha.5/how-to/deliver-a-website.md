# Deliver a website

Use LSF to serve an existing frontend build and update it independently of the
node. You will package your site's files, publish them with approved signatures,
select the publication for GET and HEAD, and retain enough information to roll
back. Static requests use the node's shared HTTP listener without starting a
capsule activation.

This workflow uses the released `0.1.0-alpha.5` CLI and ordinary Node/Python
tools. Run it on Linux; on Windows, open your WSL2 terminal. For capsule source
code, use the separate [developer commands](developer-commands.md) instead.

Have these inputs ready before starting the release steps:

| Input | What to use |
| --- | --- |
| Frontend output | The directory produced by your normal website build, often `dist/` or `build/`. |
| Public address | Your hostname and mount path, such as `docs.example.com` and `/docs/`; build the site for that path. |
| Node access | A running node and its protected operator connection profile. |
| Signing authority | Your organization's publisher and builder identities, signing approval and admission policy. The walkthrough explains where each is used. |
| Package transfer | A registry profile and repository if you transfer the package through OCI. |

At the end, visitors can open the site at your chosen address. You will also
have a publication ID and a private route journal to use for the next update
or rollback. Keep those records between CI jobs.

## 1. Install a node and the matching tools

Follow [native installation](../installation.md) for a persistent server, or
[run a container node](../operations/container-runtime.md) on a supported Linux
host. Check authenticated readiness before publishing. A successful image build
alone does not establish that the host kernel or storage supports LSF.

Install Node.js 24 and Python 3.12 or newer. Get the matching release's helper
tools without compiling LSF:

```sh
git clone --branch 0.1.0-alpha.5 --depth 1 https://github.com/KirilsTurkins/latent-service-fabric.git lsf-tools
cd lsf-tools
```

Keep application source, signing keys and private operation journals outside this
checkout. Configure your public hostname and
[application HTTP listener](../reference/http-ingress.md); management remains
private. A container host can use the [local HTTPS edge](../operations/local-https-edge.md)
and [readiness probes](../operations/readiness-probes.md).

## 2. Build and check the site

Build your frontend with its normal build command. Use the
[Angular/PrimeNG and Docusaurus guide](serve-angular-and-docusaurus.md) for the
maintained framework examples, or the
[static inventory reference](../component-development/static-sites.md) for an
existing build. Choose the hostname and mount path before building.

Review the complete public file list and routing. The static profile permits
252 assets, a 256 KiB manifest, 8 MiB per file and 16 MiB aggregate public bytes.
WOFF2 fonts and XML sitemaps are supported. Use a WOFF2-only font build; deployment
metadata and unsupported files need deliberate treatment, not silent omission.

Test the browser behavior as well as the package. Host-controlled CSP applies
to scripts, styles and framework bootstrap. Exact static stylesheet hashes and
public-document navigation each require their documented host opt-in.
Cross-origin credentialed asset access remains unsupported. See the
[browser policy](../security/browser-boundary.md) before relying on a bookmarklet
or another site's ability to read your assets.

## 3. Sign, transfer and publish

Follow [release an existing frontend build](../operations/static-release-workflow.md)
from preparation through publisher/builder approval, signing, local verification,
OCI transfer and native publication. Use your organization's identities and
policies; the example test keys are not deployment credentials.

The resulting publication ID identifies the admitted version of your site.
Keep that ID, its package digest and the original operation receipt in your
private release journal. Publication alone does not change public routes.
The [OCI reference](../reference/oci-registry.md) explains the available registry
authentication and network profiles.

## 4. Select the publication and verify it

Use [route-set reconciliation](../operations/static-route-sets.md) to plan and
apply the GET/HEAD pair. A completed journal means both routes were observed at
the intended publication. The underlying operations remain separate; an
interrupted cutover can temporarily leave different versions selected.

Open the actual HTTPS URL and check a direct deep link, a browser reload, a
missing page and the built site's themes or language switch. Check HEAD as well
as GET. If you enabled public navigation, also follow a link from another site.
The [optional gzip edge](../operations/static-compression.md) reduces transfer
bytes while retaining the documented representation and policy checks.

If your UI calls a backend, follow [static sites with a TypeScript API](static-site-and-api.md).
Keep explicit API routes separate from SPA fallback. Static hosting alone does
not replace an application's authenticated proxy behavior.

## 5. Automate updates and keep recovery possible

Use the [private CI runner workflow](../operations/headless-publication-ci.md)
to operate a container node without exposing management. Update packages and
routes independently of runtime container revisions. After an interrupted
command, recover the original operation before sending another mutation.

Rollback selects an earlier, currently eligible publication through a **new**
route-set journal. Renew expiring evidence before it prevents serving. Plan
[publication capacity](../operations/publication-retention.md), take
[consistent stopped backups](../operations/local-storage-recovery.md), and use
[exclusive ownership handover](../operations/container-handover.md) when changing
the node runtime. Retiring a publication does not delete its committed history.
