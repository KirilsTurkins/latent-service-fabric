# Developer test fixtures

Use fixtures to make a capability test repeatable in a disposable development
workspace. The project supplies its component source, typed inputs and expected
results. `dev prepare-test` configures the selected stopped node before its first
deployment. It does not add capability calls to the application for you.

For the development sequence, see [Use capabilities](../learn/use-capabilities.md).
This reference describes the fixture and scenario files. These are test inputs;
configure real production services through [standalone providers](standalone-providers.md).

## Select a fixture

Save a JSON object with one or more supported top-level entries and pass its path
to `--fixtures`. Select `--admission signed-fixture`, a workspace starting with
`test-`, and `--consent-test-fixtures`. The installed language tools supply the
test signer. Both the fixture and accepted build are fixed for this disposable
workspace; use another workspace after changing them or after the signature expires.

| Entry | What the test uses | Complete source example |
| --- | --- | --- |
| `http` | Actual buffered HTTP provider with a private controlled local peer | [HTTP fixture example](../../tools/dev_http_fixture_probe.py) |
| `blob` | Actual node-local immutable blob provider | [Blob fixture example](../../tools/dev_blob_fixture_probe.py) |
| `secrets` | Actual provider with generated private test secrets | [Secret fixture example](../../tools/dev_secret_fixture_probe.py) |
| `metrics` | Actual custom-metric provider with selected descriptors | [Metric fixture example](../../tools/dev_metric_fixture_probe.py) |
| `localService` | An explicitly built and signed companion capsule | [Local-service fixture example](../../tools/dev_local_service_fixture_probe.py) |
| `events` | An authenticated bounded protocol peer, not a live NATS broker | [Event fixture example](../../tools/dev_event_fixture_probe.py) |
| `clock` | Explicit guest test-clock readings; the node's own clock is unchanged | [Clock fixture example](../../tools/dev_clock_fixture_probe.py) |

These linked source examples also generate their application and scenario files.
Their source-based integration conductors are for work on LSF itself; they are
not additional downloadable templates in `dev init`. Use their configuration
shapes when authoring equivalent tests for your own project.

## HTTP configuration

For a project that sends an empty-body GET request to
`http://127.0.0.1:18753/example`, this fixture returns HTTP 200 with body `Hello!`:

```json
{
  "http": {
    "port": 18753,
    "exchanges": [
      {
        "method": "GET",
        "path": "/example",
        "requestBody": "",
        "status": 200,
        "responseBody": "SGVsbG8h"
      }
    ]
  }
}
```

Bodies are canonical Base64. The fixture allows up to 16 distinct method/path
pairs, with at most 32 KiB per body. Methods are GET, HEAD, POST, PUT or DELETE;
redirect responses are not supported. Choose an unused unprivileged port.
The node owns the local peer and generates its private provider credential.
An occupied port fails; another listener is not stopped.

The scope permits only the selected origin, methods and paths. Include a denied
path or denied-capability case in your scenarios as well as the successful call.
An HTTP fixture is classified as `controlled-peer`; blobs, secrets, metrics and
local services use `real-provider`; a clock override uses `test-adapter`.

## Bind a scenario to its configuration

`tests/scenarios.json` uses `schemaVersion: latent.dev.scenarios.v1`. Each case
names the service, contract, function, input file and expected result. Its
`requires` list identifies the environment support it needs, and its `fixtures`
list binds the exact configuration file to that case. The HTTP requirement is
`buffered-http-fixture`; the grant is `latent:http/client@0.2.0`.

For example, add the following fields to an HTTP scenario whose ordinary input
and expected answer already match your capsule:

```json
{
  "requires": ["buffered-http-fixture"],
  "fixtures": [
    {
      "id": "http",
      "kind": "controlled-peer",
      "identity": "sha256:REPLACE_WITH_CONFIGURATION_DIGEST",
      "configuration": "tests/http-fixture.json"
    }
  ],
  "execution": {"grants": ["latent:http/client@0.2.0"]}
}
```

This is a fragment, not a complete scenario file. Compute the configuration
identity from the exact file bytes. **On Windows**, in the working terminal:

```powershell
'sha256:' + (Get-FileHash -LiteralPath (Join-Path $Project 'tests/http-fixture.json') -Algorithm SHA256).Hash.ToLowerInvariant()
```

**On Linux:**

```bash
printf 'sha256:%s\n' "$(sha256sum "$Project/tests/http-fixture.json" | cut -d' ' -f1)"
```

Set the scenario's identity to that result. Keep line endings and all other bytes
unchanged after calculating it. The runner rejects changed or uninitialized
fixtures rather than silently using a different service.

The `execution.deniedCapabilities` list can select a subset of the case's
`grants` for an explicit denial test. Set the expected error category and payload
to the actual contract: some capsules translate a host denial into an application
result, while others return a platform failure. Do not rewrite the expected
category simply to hide an unrelated failure.

## Run and inspect

Use [Developer commands](../how-to/developer-commands.md) to build, prepare, start,
deploy and test. `dev test --environment node` checks every required selected
case. The report records the actual environment and fixture runtime; unsupported
required cases fail. A portable test never replaces a requested node test.

`dev down` closes the node's owned fixture processes and connections and retains
workspace data. Use explicit workspace purge when finished. Inspect uncertain
cleanup and recover the original operation before retrying work.
