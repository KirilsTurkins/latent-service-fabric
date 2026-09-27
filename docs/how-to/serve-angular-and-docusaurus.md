# Serve Angular and Docusaurus sites

This guide prepares a client-only Angular application and a bilingual Docusaurus
site for static publication. Readers can navigate lazy routes, change themes and
switch languages after the files are served by an LSF node.

Use a current development build of the native CLI and node for this profile.
The `allowStaticStyleHashes` option is newer than `0.1.0-alpha.4`.
These examples use Angular **20.3.32**, PrimeNG **20.4.0**, Aura/Lara themes
**1.2.5** and Docusaurus **3.10.2**. Other versions and plugins need their own
browser checks.

## Build the examples

Use a Linux build workspace with Node 24.19 and Python 3.13 or newer. On Windows,
open your WSL2 terminal and run the commands inside that workspace. From the
repository root, install the pinned build dependencies:

```sh
npm ci --prefix examples/framework-compatibility --ignore-scripts
```

Locate your native `latent` executable and an installed Chromium or Chrome
executable. Run the following command with their absolute paths:

```sh
python3 tools/build_framework_sites.py --cli /path/to/latent --chrome /path/to/chrome --output target/framework-sites
```

Use the Linux executables in that workspace and enclose paths in quotes if they
contain spaces. The output directory must be new; choose another name when
repeating the build.

The command creates four packages: `angular-root`, `angular-mounted`, `docs-root`
and `docs-mounted`. Each directory contains a `package` ready for the
[publisher verification and publication workflow](../component-development/packaging.md),
plus its selected public inventory. No publisher credentials are needed to build.
Publishing still requires your organization's approved publisher and builder
evidence; this command does not create those approvals.

## Choose the mount before building

| Example | Static trigger mount | Application configuration |
| --- | --- | --- |
| Angular root | `/` | `APP_BASE_HREF` is `/` |
| Angular mounted | `/app` | `APP_BASE_HREF` is `/app/` |
| Docusaurus root | `/` | `baseUrl` is `/` |
| Docusaurus mounted | `/docs` | `baseUrl` is `/docs/` |

Use separate hostnames for the two root examples. You can place `/app` and
`/docs` under one hostname when both applications are trusted to share a browser
origin. URL paths do not isolate browser credentials, storage or scripts.

Configure Angular's base path through `APP_BASE_HREF` and generate asset URLs for
that mount. Keep its HTML free of `<base>` elements. Configure Docusaurus through
`baseUrl` and let the generator produce localized links and lazy chunk URLs.
The maintained Docusaurus plugin uses portable runtime chunk names, replacing
the generator's default naming convention that contains `~`.

Select SPA fallback for Angular and directory indexes with no SPA fallback for
Docusaurus. The supplied inventory files already select these policies. Apply
both GET and HEAD triggers using the [route-set workflow](../operations/static-route-sets.md).
A request to `/docs/guide` should redirect to `/docs/guide/`.

## Allow the reviewed Angular styles

PrimeNG and Angular create style elements at runtime. In the node configuration,
set this field inside the existing `httpIngress` object, then restart the node:

```json
{
  "allowStaticStyleHashes": true
}
```

The Angular packages contain the exact reviewed style identities for these
components and themes. Both the signed publication and the operator setting
are required. The default is false, which returns 403 for HTML requesting these
styles. This setting grants no permission for inline scripts, style attributes,
foreign resources or base-element overrides.

When adapting your application, first move your own inline scripts and static
styles to ordinary files. For deterministic runtime styles, review their exact
content before including their identities in `styleHashes` in the static input.
The fixture's `reviewed-styles.json` covers its home/order views and Aura/Lara
button themes only. Do not copy it as a generic approval for another application.
Keep runtime style generation deterministic; arbitrary per-user CSS needs a
separately reviewed strategy.

Docusaurus needs no style-hash opt-in in this example. Its build transformation
moves owned bootstrap code into external scripts and the hidden SVG-symbol style
into a stylesheet **before** packaging. It rejects other inline style attributes
and event handlers so that you can correct them in the application source.

## Check the published application

Open the Angular home page, select **Order 42**, confirm the order, switch between
Aura and Lara, and reload the order URL directly. Open the handbook, follow its
release guide, change the color theme and select German. Repeat these steps at
the configured mounted paths. All required scripts, styles and lazy chunks
should succeed without CSP errors in the browser's developer tools.

| Symptom | Action |
| --- | --- |
| Angular HTML returns 403 | Check the node's explicit style-hash setting and current publication eligibility. |
| A style is blocked after a component/theme change | Review the new exact CSS and rebuild the signed inventory; avoid copying hashes blindly from an error message. |
| The build reports an unreviewed inline attribute | Move it into an owned stylesheet or component code, then rebuild. |
| A lazy chunk returns 404 | Match build-time base paths to the trigger mount and include all generated chunks. |
| A generator filename is rejected | Configure portable names in the generator; do not silently drop required files. |

Packaging checks file structure, identities and limits. It cannot prove every
browser interaction works. The repository's native Chromium workflow exercises
these examples, including denial of unapproved injection. Repeat the browser
steps for your own plugins and interactions after publishing.
