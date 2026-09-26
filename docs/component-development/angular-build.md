# Build your first Angular application

Build a small website with a greeting and a counter button. Angular produces
the page on the server, then makes the counter interactive in the browser.
LSF packages the server program and browser files together so you can deploy
them as one application.

This tutorial builds the application. Continue with
[running and updating the application](../learn/build-and-deliver-angular.mdx)
to publish it to a node and open it in a browser.

## 1. Prepare your tools

Use the source checkout from [Run your first node](../start/first-node.md).
You also need Node 24.19.0 and npm 11.19.1. These examples use Angular 22.1.6;
the repository's dependency lock selects the matching Angular compiler.

Run these commands from the repository root in your Linux terminal:

```bash
set -euo pipefail
umask 077
export CARGO_TARGET_DIR="$PWD/target"
npm --prefix examples/renderer-profile ci --ignore-scripts --no-audit --no-fund
cargo fetch --locked
cargo build --locked -p latent
```

The npm command installs the build tools. `cargo fetch` downloads the Rust
dependencies needed by the application builder. This can take a few minutes
the first time.

## 2. Make your own copy of the example

```bash
APP="$PWD/target/my-angular-app"
test ! -e "$APP"
cp -R examples/angular-application "$APP"
```

Open the new folder in your editor. The files you will work with are:

| File | What it does |
| --- | --- |
| `shared/app.ts` | Defines the greeting, counter and button |
| `server/main.ts` | Produces the initial HTML page |
| `client/main.ts` | Makes the existing page interactive in the browser |
| `angular-build.json` | Lists the source files, entry points and routes to include |
| `public/offline.html` | A ready-made HTML page served at `/offline` |

For example, these lines in `shared/app.ts` display the counter and increase it
when the reader clicks the button:

```typescript
template: '<h1 id="greeting">Hello {{name}}</h1><button id="count" (click)="increment()">Count {{count()}}</button>'
```

```typescript
count = signal(0);
increment() { this.count.update(value => value + 1); }
```

`signal(0)` starts the counter at zero. Updating the signal lets Angular update
the displayed number. These are Angular TypeScript files. If you are building
a client in Rust, Go, C, Java or C#, follow the
[client SDK guide](../learn/use-a-client.mdx) instead.

## 3. Change the greeting

In your copy of `shared/app.ts`, change `Hello {{name}}` to
`Welcome {{name}}`. Leave the other files as they are for this first build.

The app uses the request's caller name for `name`. The server puts that value
into the initial page, and the browser picks up the same value when it starts.

## 4. Build the application

```bash
python3 tools/build_angular_package.py \
  --input-root "$APP" \
  --toolchain-root "$PWD/examples/renderer-profile" \
  --cli "$PWD/target/debug/latent" \
  --target-root "$PWD/target/angular-build" \
  --output "$PWD/target/angular-build/welcome" \
  --cargo-target-dir "$CARGO_TARGET_DIR" \
  --repository https://github.com/KirilsTurkins/latent-service-fabric
```

The command compiles the server and browser code and writes the finished
package to `target/angular-build/welcome/package`. It also creates an
`inputs` folder containing the compiled files. You can inspect the build summary
if a build fails, but you do not need to copy identifiers from it.

The output path must be new. For another build, choose a name such as
`target/angular-build/welcome-second`. Editing the source does not change a
package you already built.

## 5. Run it and try the button

Continue with [Build an Angular application and deliver it through LSF](../learn/build-and-deliver-angular.mdx).
That guide covers the node, publication and browser steps. Building the files
alone does not start a web server.

When the app is running, the initial page contains the greeting and
`Count 0`. Clicking the button changes the text to `Count 1`, then `Count 2`.
The browser keeps the server's initial page and attaches the button behavior
to it; this is called **hydration**.

## If you get stuck

| What you see | What to do |
| --- | --- |
| Node or npm version error | Use the versions listed in step 1 and rerun the dependency installation |
| Missing offline Cargo dependency | Run `cargo fetch --locked` from the repository root, then build again |
| Output directory already exists | Choose a fresh output name; keep the previous build if you still need it |
| A new source file is not included | Add it to `sources` in your copy of `angular-build.json` |
| An unsupported import or dependency is rejected | Start with the example's dependencies; the current builder accepts the documented Angular profile |

The current builder supports the selected server, client and shared files in
this example. Converting a larger Angular CLI application may require changes
to its dependencies and entry points. Keep server credentials out of browser
and shared source files.
