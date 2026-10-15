# Contribute to LSF

You can contribute a bug fix, a clearer guide, a test or a new capability. This
page takes you from choosing a change to opening a pull request against
`development`.

## 1. Choose a change

Start with the [open issues](https://github.com/KirilsTurkins/latent-service-fabric/issues)
or the [good first issue queue](https://github.com/KirilsTurkins/latent-service-fabric/issues?q=is%3Aissue%20is%3Aopen%20label%3A%22good%20first%20issue%22).
Read the acceptance criteria and check for an existing branch or pull request.
If someone is already working on the issue, coordinate there before duplicating
the work. For a documentation fix, identify the page, the confusing step and
what the reader should be able to do afterward.
Use the private reporting route in [SECURITY.md](../../SECURITY.md) for suspected
vulnerabilities rather than publishing sensitive details in an issue.

## 2. Prepare your checkout

Install Git and the tools needed for your change from the
[toolchain guide](../development/toolchain.md). Native runtime/process tests use
their declared Linux x86_64 environment. Metadata planning and documentation
checks can run on Windows; [portable component tests](../component-development/portable-tests.md)
cover a smaller boundary and do not qualify the Linux node.

For a new checkout:

```bash
git clone --branch development https://github.com/KirilsTurkins/latent-service-fabric.git
cd latent-service-fabric
git switch -c docs/my-guide-fix
```

Choose a descriptive branch name, such as `fix/cancelled-request-cleanup` or
`feat/my-capability`. If you do not have repository write access, create a GitHub
fork and use its clone URL. Keep `development` as the base of your pull request;
the repository's default `release` branch is not the contribution target.
For an intentional stack, target the actual parent branch and follow the
[stack and final-base rules](../../CONTRIBUTING.md#commit-history-and-evidence).

## 3. Make and check the change

Change the source and update any affected callers, examples and documentation.
For a bug fix, add a focused regression test that demonstrates the failure.
When changing a contract, update its generated bindings and conformance checks.
The [contribution rules](../../CONTRIBUTING.md) describe interface ownership and
resource constraints. Obsolete alpha APIs and compatibility adapters can be
removed when their replacements are adopted, while retaining supported durable
state and recovery contracts. Read the [ADR index](../../adr/README.md) before
changing an invariant; an accepted design is distinct from an implemented and
qualified feature.

Choose checks that exercise your change:

Bare `make` shows the [current command guide](../development/make-commands.md).
Use focused targets while editing; broad workspace/AOT validation has explicit
clean-source and preparation requirements.

| Change | Start here |
| --- | --- |
| Markdown, links or diagrams | [Documentation checks](../development/website.md), [SVG conventions](../svg-style.md). |
| Website layout or code examples | [Website setup and build](../development/website.md), then check the rendered page. |
| Rust logic | [Local test entry point](../development/local-tests.md); prepare and run the affected suite. |
| Timing, cancellation or cleanup | [Deterministic tests](../development/deterministic-tests.md) and [owned test processes](../development/owned-test-processes.md). |
| Runtime, providers or API contracts | The affected integration suite and [validation tiers](../../VALIDATION.md). |
| State, command outcomes or persistent formats | [Installed transactions](../development/installed-transaction-rpc.md), [schema compatibility](../architecture/application-schema-compatibility.md) and [recovery qualification](../testing/installed-transaction-recovery.md). |
| Guest or external client SDK | [Guest profiles](../component-development/guest-sdk.md) and the separate [native client profile](../../sdk/profile/README.md); use each owning generator and execution suite. |
| Test inventories or CI tooling | [Exact suites](../testing/ci-suite-inventory.md) and [scoped command contracts](../testing/ci-command-contracts.md); review changed expectations rather than accepting observed output automatically. |

The local runner's `list`, `explain` and `plan` commands inspect metadata only.
Explicitly prepare the selected suite/case, check its owned inputs, then run it
without an implicit build. Register new cases and intentional ignores in the
shared catalogue. Keep discovery, execution and actual resource cleanup separate.

Edit current prose in `docs/` and decisions in `adr/`; the website reads those
directories directly. Reference runnable examples from their owning projects
through [source extraction](../development/website-examples.md). Use
[Development changes](../start/development-changes.md) for newer source features;
do not relabel them as features of the published toolkit or edit frozen release
snapshots. Retain original evidence when consolidating redundant historical prose.

For repository documentation checks, use the pinned Python environment:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --requirement tools/requirements.lock
python tools/validate_docs.py
git diff --check
```

Expect no documentation errors and no whitespace errors. For an interactive
website change, also follow the website build instructions and open the result;
a link validator cannot tell you whether a guide is understandable.
CI still selects its required `docs`, `website`, `fast` or `full` checks from the
complete change and dependency graph. A local focused pass does not replace that
selection or the independent security checks.
Use the issue's acceptance criteria to select additional tests. Large scale
campaigns and long resource soaks need explicit selection.

## 4. Open the pull request

Review the diff, commit the change, and push your branch to the repository or
your fork:

```bash
git diff
git add docs/path-you-changed.md
git diff --cached
git commit -m "Explain the missing setup step"
git push -u origin docs/my-guide-fix
```

Replace the example file and branch with yours. Open the pull request on GitHub
with **base: development**. Explain the problem, the resulting behavior, the
issue it addresses and the checks you actually ran. Record remaining limitations
or failing checks. Use a draft while required implementation or review is pending.
For a temporary stack, identify the parent PR and use its branch as the base;
restore `development` and run fresh final-base CI after that parent integrates.

Follow the selected CI jobs and fix failures before requesting a merge. The
[CI profile guide](../development/ci-profiles.md) explains why particular checks
run. A passing build does not replace the issue's full acceptance criteria.
Match results to the actual tested commit and environment. Prepared artifacts,
old receipts and a clean website build cannot establish native/application or
packaged acceptance.

## Further contributor references

- [Local tests](../development/local-tests.md): inspect, prepare and run exact suites.
- [Build foundation](../development/build-foundation.md): generated contracts and repository layout.
- [Architecture decisions](../../adr/README.md): the rationale behind interface and runtime choices.
- [Engineering records](../development/engineering-records.md): maintainer acceptance, release decisions and historical reports.
