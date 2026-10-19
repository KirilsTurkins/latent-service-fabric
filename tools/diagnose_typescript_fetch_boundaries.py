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


def run(probes: Path, native: Path, engine: Path, splicer: Path, tools: Path, output: Path) -> dict:
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.same-sdk-fetch-boundaries.v1',
        'qualification': False, 'currentHeadQualification': False, 'status': 'incomplete',
        'sdkTestedCommit': TESTED, 'helper': file_identity(Path(__file__)), 'probes': []}
    source = {name: read_file(probes/name, 65536) for name in ('main.ts', 'default-client.ts')}
    record['applicationSource'] = {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in source.items()}
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
        service = original_connect(*args, **kwargs)
        services.append((service, file_identity(args[1])))
        return service

    def call(client, target, template, function, arguments, activation, **kwargs):
        if activation == 'fetch-json':
            require(len(services) == 1, 'fetch-boundary-single-node')
            probe = fetch.Probe(*services[0])
            for name, mode in (('promise-ready', 3), ('request-copy-ready', 4)):
                row = original_call(client, target, template, function, [mode, arguments[1]], 'fetch-'+name)
                record['probes'].append({'name': name, 'mode': mode, 'entry': row})
                write_json(output/('probe-'+name+'.json'), record['probes'][-1])
                fetch.require_result(row, name, 0)
                fetch.retire(client, probe, target, output, name)
        return original_call(client, target, template, function, arguments, activation, **kwargs)

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
        record['applicationSourceUnchanged'] = source == {
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
