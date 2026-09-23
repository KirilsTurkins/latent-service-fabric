"""Authenticated C newcomer workflow using distinct CLI and node processes."""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
import time

from tools.build_process_signals import owned_cancellation
from tools.c_guest.compiler import SDK, safe_output
from tools.phase2_operator_process import Client, read_json, require, stopped_record, write_json, write_selected_deployment
from tools.phase2_operator_scenario import NODE_ID, configure_node, connect, receipt

MEDIA = 'application/vnd.latent.wit-values.v1+json'


def process_memory(node) -> dict:
    # Only this runner's reserved, unreaped process is observed. Missing kernel
    # counters are explicit absence, never a fabricated zero measurement.
    try:
        path = Path('/proc') / str(node.owner.process.pid) / 'status'
        data = path.read_bytes()
        require(len(data) <= 16384, 'owned-process-status-bound')
        values = {}
        for line in data.decode('ascii').splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] in ('VmRSS:', 'VmHWM:') and parts[2] == 'kB':
                values['rssBytes' if parts[0] == 'VmRSS:' else 'peakRssBytes'] = int(parts[1]) * 1024
        return {'available': bool(values), **values}
    except (OSError, UnicodeError, ValueError):
        return {'available': False}


def idle(client) -> dict:
    end = min(client.deadline, time.monotonic() + 5)
    while True:
        inventory = client.call('node', 'get', NODE_ID)['data']['inventory']
        cells = inventory['cellCapacity']
        require(bool(cells), 'node-cell-inventory-missing')
        if all(int(cell['active']) == 0 and int(cell['queueDepth']) == 0 for cell in cells):
            require(all(int(cell['quarantined']) == 0 and cell['available'] == cell['total']
                        for cell in cells), 'node-cell-not-reusable')
            cache = inventory['cacheSummary']
            require(cache['available'] and int(cache['preparing']) == 0, 'node-cache-not-idle')
            quotas = inventory.get('quotas')
            if quotas is not None:
                require(all(int(quotas['usage'][name]) == 0 for name in
                            ('activeActivations', 'queuedActivations', 'reservedCpuFuel', 'reservedMemoryBytes')),
                        'node-activation-reservation-leak')
            topology = inventory['topology']
            require(topology['available'] and topology['complete'], 'node-topology-unmeasured')
            for entry in topology['entries']:
                if entry['ownership'].endswith('SERVICE_RESIDENT'):
                    require(int(entry['configuredCount']) == 0, 'per-service-resident-owner')
            return {'cells': cells, 'cache': cache, 'topology': topology, 'quotas': quotas,
                    'processMemory': process_memory(client.node)}
        require(time.monotonic() < end, 'node-idle-deadline')
        time.sleep(0.01)


def payload(value: dict) -> object:
    data = value['data']['payload']
    require(data['encoding'] == 'base64' and data['mediaType'] == MEDIA, 'C-output-format')
    raw = base64.b64decode(data['data'], validate=True)
    require(len(raw) <= 65536 and data['byteLength'] == str(len(raw)), 'C-output-bound')
    return json.loads(raw)


def expected(name: str, inputs: list) -> list:
    if name == 'greeting':
        result = 'Hello, ' + inputs[0] + '!'
    elif name == 'word-count':
        import re
        result = str(len(re.findall(r'[^ \t\n\r\v\f]+', inputs[0])))
    else:
        value = inputs[0]
        result = {'total-cents': str((1500 if value['express'] else 500) + 2 * int(value['grams'])),
                  'currency': 'EUR', 'eta-days': 1 if value['express'] else 5}
    return [{'ok': result}]


def invoke(client, name: str, case: dict, values: list, category: str, ordinal: int) -> dict:
    path = client.directory / f'input-{name}-{ordinal}.json'
    write_json(path, values)
    codes = {'success': (0,), 'declared-error': (3,), 'invalid-wire': (2, 4)}[category]
    start = time.perf_counter_ns()
    value = client.call('invoke', '--service', name, '--contract', f'examples:{name}/api@1.0.0',
        '--function', case['function'], '--activation-id', f'c-{name}-{ordinal}', '--input', path, codes=codes)
    elapsed = (time.perf_counter_ns() - start) // 1000
    if category == 'success':
        require(value['category'] == 'success' and value['outcomeKnown'], 'C-success-category')
        require(payload(value) == expected(name, values), 'C-exact-typed-result')
    elif category == 'declared-error':
        require(value['category'] == 'declared-error' and value['outcomeKnown'], 'C-declared-category')
    else:
        require(value['category'] in ('local-error', 'platform-failure'), 'C-malformed-call-category')
    print(f'PASS C node invocation: {name} {ordinal} {category}', flush=True)
    return {'category': value['category'], 'endToEndMicros': elapsed}


def exercise(client, binary: Path, directory: Path, fixture: Path) -> dict:
    metadata = read_json(fixture / 'fixture.json')
    require(metadata['formatVersion'] == 1 and metadata['tenant'] == 'tests', 'C-fixture-profile')
    cases = read_json(SDK / 'projects/cases.json')
    config = configure_node(directory, fixture, 'tests')
    start = time.perf_counter_ns()
    node = connect(client, binary, directory, config, 'tests', 1)
    startup = (time.perf_counter_ns() - start) // 1000
    records = {}
    try:
        before = idle(client)
        for name in ('greeting', 'word-count', 'shipping'):
            source = fixture / name
            client.call('package', 'inspect', source / 'package')
            client.call('--tenant', 'tests', 'package', 'verify', source / 'package',
                '--evidence-index', source / 'evidence/index.json', '--evidence-root', source / 'evidence',
                '--policy', fixture / 'policy.json')
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-publish-' + name,
                '--expected-generation', '0')['data']
            require(published['release']['digest'] == metadata['components'][name]['componentDigest'], 'C-publication-digest')
            selected = write_selected_deployment(source / 'deployment.json',
                client.directory / (name + '-selected.json'), published['operation']['publication']['id'])
            snapshot = client.call('deployment', 'get', name, '--operation-snapshot', codes=(6,))['data']
            start = time.perf_counter_ns()
            applied = receipt(client.call('deployment', 'apply', selected, '--operation-id', 'c-apply-' + name,
                '--expected-generation', '0', '--expected-state-version', snapshot['stateVersion']), 'c-apply-' + name)
            preparation = (time.perf_counter_ns() - start) // 1000
            calls = []
            case = cases[name]
            groups = [('success', case['success']), ('declared-error', case['declaredError']),
                      ('invalid-wire', case['invalidWire']), ('success', case['success'][:1])]
            for category, values in groups:
                for inputs in values:
                    calls.append(invoke(client, name, case, inputs, category, len(calls)))
                    idle(client)
            snapshot = client.call('deployment', 'get', name, '--operation-snapshot')['data']
            client.call('deployment', 'delete', name, '--operation-id', 'c-delete-' + name,
                        '--expected-generation', snapshot['deployment']['generation'],
                        '--expected-state-version', snapshot['stateVersion'])
            absent = client.call('deployment', 'get', name, codes=(6,))
            require(absent['category'] == 'not-found', 'C-deployment-not-removed')
            records[name] = {**metadata['components'][name], 'calls': calls,
                'deploymentApplyMicros': preparation, 'routeGeneration': applied['routeGeneration'],
                'idleAfterRemoval': idle(client)}
        client.node = None
        node.stop()
        shutdown = stopped_record(node)
        require(shutdown['reaped'] and shutdown['record']['clean'], 'C-node-not-cleanly-reaped')
        return {'formatVersion': 1, 'startupMicros': startup, 'before': before, 'projects': records,
                'shutdown': shutdown, 'timingScope': 'CLI/control end-to-end, not guest-only CPU',
                'memoryScope': 'whole owned node process; cache ownership separately reported'}
    finally:
        client.node = None
        node.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = safe_output(args.output)
    output.mkdir(parents=True)
    client_dir, node_dir = output / 'client', output / 'node'
    client_dir.mkdir(); node_dir.mkdir()
    with owned_cancellation() as cancellation:
        client = Client(args.cli.resolve(strict=True), client_dir, cancellation, time.monotonic() + 180)
        result = exercise(client, args.node.resolve(strict=True), node_dir, args.fixture.resolve(strict=True))
        write_json(output / 'receipt.json', result)
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
