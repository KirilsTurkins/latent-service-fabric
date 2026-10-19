"""Same-SDK signed boundary experiment; never current-head Fetch qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))

from tools import qualify_typescript_fetch_runtime as fetch
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file

TESTED = 'ba62bf8f266e589971a03e496b18b8f2cb5e5d85'


def typed_refusal_source(source: dict[str, bytes]) -> dict[str, bytes]:
    """Only this private experiment imports HTTP directly; the real fixture does not."""
    marker = b'    if (mode === 4) return await requestCopyReady(url);'
    require(source['main.ts'].count(marker) == 1, 'fetch-boundary-exact-probe-dispatch')
    probe = b'''import * as diagnosticHttp from 'latent:http/streaming@0.3.0';
async function typedInvalidUrl() {
  try {
    const upload = await diagnosticHttp.open({method: 'get', url: 'invalid', headers: [],
      bodyLength: 0n, bodyMediaType: undefined, idempotencyKey: undefined, timeoutMillis: undefined});
    await diagnosticHttp.abortUpload(upload);
    return 'typed-invalid-url-accepted';
  } catch (error) {
    const payload = error && typeof error === 'object' && 'payload' in error ? error.payload : null;
    return payload && typeof payload === 'object' && 'tag' in payload && payload.tag === 'invalid-url'
      ? 'typed-invalid-url-ready' : 'typed-invalid-url-other';
  }
}
async function typedOpen(url: string) {
  let stage = 'open';
  try {
    const upload = await diagnosticHttp.open({method: 'get', url,
      headers: [{name: 'x-client', value: 'ordinary-global'}], bodyLength: 0n,
      bodyMediaType: undefined, idempotencyKey: undefined, timeoutMillis: undefined});
    stage = 'abort';
    await diagnosticHttp.abortUpload(upload);
    return 'typed-open-ready';
  } catch { return stage === 'open' ? 'typed-open-refused' : 'typed-abort-refused'; }
}
'''
    return {**source, 'main.ts': probe + source['main.ts'].replace(marker,
        marker + b'\n    if (mode === 5) return await typedInvalidUrl();'
                 b'\n    if (mode === 6) return await typedOpen(url);', 1)}


def numeric_fields(path: Path, fields: set[str]) -> dict:
    value = json.loads(read_file(path, 8192))
    require(isinstance(value, dict) and set(value) == fields and all(
        type(number) is int and 0 <= number < 2**64 for number in value.values()),
        'fetch-boundary-numeric-budget-fields')
    return value


def run(probes: Path, native: Path, engine: Path, splicer: Path, tools: Path, output: Path) -> dict:
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.same-sdk-fetch-boundaries.v1',
        'qualification': False, 'currentHeadQualification': False, 'status': 'incomplete',
        'sdkTestedCommit': TESTED, 'helper': file_identity(Path(__file__)), 'probes': [],
        'actualInvocationBudgets': {}}
    original_source = {name: read_file(probes/name, 65536) for name in ('main.ts', 'default-client.ts')}
    source = typed_refusal_source(original_source)
    record['probeSource'] = {name: {'sha256': digest(raw), 'bytes': len(raw)}
                            for name, raw in original_source.items()}
    record['applicationSource'] = {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in source.items()}
    record['applicationDerivation'] = 'private-typed-error-and-success-resource-import-probes-only'
    original_project, original_call, original_connect = fetch.project, fetch.call, fetch.connect
    services = []

    def project(directory):
        app = original_project(directory)
        for name, raw in source.items():
            (app/'src'/name).write_bytes(raw)
        lock = json.loads(read_file(app/'sdk-lock.json'))
        lock['template']['sourceDigest'] = digest(source['main.ts'])
        (app/'sdk-lock.json').write_text(json.dumps(lock, indent=2)+'\n', encoding='utf-8')
        fetch.validate(fetch.snapshot(app))
        return app

    def connect(*args, **kwargs):
        configured = json.loads(read_file(args[3]))
        execution = configured['execution']
        require(isinstance(execution, dict) and set(execution) == {
            'maximumCpuFuel', 'maximumWallTimeMillis', 'maximumLogBytes'} and all(
            type(value) is int and 0 <= value < 2**64 for value in execution.values()),
            'fetch-boundary-node-execution-fields')
        record['actualNodeExecutionLimits'] = execution
        service = original_connect(*args, **kwargs)
        services.append((service, file_identity(args[1])))
        return service

    def invoke(client, target, template, function, arguments, activation, **kwargs):
        require(activation in {'fetch-runtime-denied', 'fetch-http-denied', 'fetch-entry',
            'fetch-request-ready', 'fetch-promise-ready', 'fetch-request-copy-ready',
            'fetch-typed-invalid-url', 'fetch-typed-open', 'fetch-json', 'fetch-http404', 'fetch-fresh'},
            'fetch-boundary-activation-name')
        row = original_call(client, target, template, function, arguments, activation, **kwargs)
        fields = set(json.loads(read_file(ROOT/'examples/echo-contract/deployment.json'))['spec']['resources'])
        record['actualInvocationBudgets'][activation] = numeric_fields(
            client.directory/(activation+'-budget.json'), fields)
        return row

    def call(client, target, template, function, arguments, activation, **kwargs):
        if activation == 'fetch-json':
            require(len(services) == 1, 'fetch-boundary-single-node')
            probe = fetch.Probe(*services[0])
            for name, mode, expected in (('promise-ready', 3, 'promise-ready'),
                    ('request-copy-ready', 4, 'request-copy-ready'),
                    ('typed-invalid-url', 5, 'typed-invalid-url-ready')):
                row = invoke(client, target, template, function, [mode, arguments[1]], 'fetch-'+name)
                record['probes'].append({'name': name, 'mode': mode, 'entry': row})
                write_json(output/('probe-'+name+'.json'), record['probes'][-1])
                fetch.require_result(row, expected, 0)
                fetch.retire(client, probe, target, output, name)
        row = invoke(client, target, template, function, arguments, activation, **kwargs)
        if (activation == 'fetch-json' and row['exitCode'] == 4 and row['processReaped'] is True
                and row['response']['outcomeKnown'] is True
                and row['response']['error']['code'] == 'guest-trap'):
            # Preserve the original failed JSON row and its mandatory assertion.
            # Only after actual failed-activation cleanup, one legal diagnostic
            # open/abort may charge the original one-outbound grant. It never
            # substitutes for JSON success or changes the real peer assertions.
            record['originalJsonFailure'] = row
            fetch.retire(client, probe, target, output, 'failed-json')
            opened = invoke(client, target, template, function, [6, arguments[1]], 'fetch-typed-open')
            record['probes'].append({'name': 'typed-open', 'mode': 6, 'entry': opened})
            write_json(output/'probe-typed-open.json', record['probes'][-1])
            fetch.require_result(opened, 'typed-open-ready', 1)
            fetch.retire(client, probe, target, output, 'typed-open')
        return row

    try:
        head = run_bounded_result(['git', 'rev-parse', 'HEAD'], ROOT, build_environment(output), 10, 4096)
        require(head.returncode == 0 and head.stdout.decode().strip() == TESTED,
                'fetch-boundary-original-sdk-source')
        # All compiler/engine/native validation is the original qualifier's.
        # Only the outside-checkout application's two source files differ.
        with patch.object(fetch, 'project', project), patch.object(fetch, 'connect', connect), \
                patch.object(fetch, 'call', call):
            result = fetch.qualify(output/'attempt', tools, engine, splicer, prepared=native)
            record['originalFiniteGate'] = result['status']
        record['status'] = 'observed'
    except Exception as error:
        record['failureClass'] = type(error).__name__ if type(error).__name__ in {
            'WorkflowError', 'ValueError', 'KeyError', 'TypeError', 'OSError'} else 'Other'
    finally:
        record['applicationSourceUnchanged'] = original_source == {
            name: read_file(probes/name, 65536) for name in source}
        require(record['applicationSourceUnchanged'], 'fetch-boundary-probe-source-drift')
        write_json(output/'observation.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('probes', 'native', 'engine', 'splicer', 'tools', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(*(getattr(args, name).resolve() for name in
        ('probes', 'native', 'engine', 'splicer', 'tools', 'output')))))
