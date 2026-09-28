"""No cloud emulator: real HTTP, authenticated CLI, stopped node and full ingress pool."""
import json
import time

from qualification import ROOT

SCRIPT = '/source/tools/container_runtime/qualification_probe_inside.py'


def run(drill, node, volumes, mount):
    source = mount(ROOT, '/source', True, 'bind')
    def adapter(name, node_id, namespace=node):
        return drill.container(name, ['--entrypoint', '/usr/local/bin/python3',
            *mount(volumes['config'], '/etc/lsf', True), *source, drill.args.image, '-I', '/opt/lsf/runtime/probe.py',
            '--node-id', node_id], network='container:' + namespace, memory='128m', pids='16')
    probe = adapter('probe', 'container-qualification')
    drill.docker('start', probe)
    inspection = drill.exec_json(node, '/opt/lsf/release/bin/latent', '--config', '/etc/lsf/client.json',
        '--output', 'json', 'node', 'get', 'container-qualification')['data']['inventory']
    (drill.output / 'probe-input-shape.json').write_text(json.dumps({
        'fields': sorted(inspection), 'http': [row for row in inspection['topology']['entries'] if row['name'].startswith('http-')]}))
    observation = drill.exec_json(node, '/usr/local/bin/python3', '/source/tools/container_runtime/probe.py',
        '--node-id', 'container-qualification', '--check')
    (drill.output / 'probe-check.json').write_text(json.dumps(observation))
    (drill.output / 'probe-start.log').write_bytes(drill.docker('logs', probe)[1])
    initial = drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'ready')
    overload = drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'overload')
    stale = drill.exec_json(node, '/usr/local/bin/python3', '/source/tools/container_runtime/qualification_projection.py')
    drill.docker('kill', '--signal', 'STOP', node)
    try:
        unavailable = drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'unavailable')
    finally:
        drill.docker('kill', '--signal', 'CONT', node)
    drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'ready')
    drill.docker('stop', '--time', '10', node, timeout=15)
    shutdown = drill.exec_json(probe, '/usr/local/bin/python3', SCRIPT, 'unavailable')
    drill.docker('stop', '--time', '10', probe, timeout=15)
    if int(drill.docker('inspect', '--format', '{{.State.ExitCode}}', probe)[1]) != 0:
        raise RuntimeError('probe-shutdown-before-namespace-replacement-failed')
    time.sleep(6)
    drill.docker('start', node)
    drill.ready(node)
    # Docker restart replaces this node's network namespace. Explicitly attach a
    # fresh adapter; the old namespace must never be mistaken for the new node.
    probe = adapter('probe-restarted', 'container-qualification')
    drill.docker('start', probe)
    drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'ready')
    stats = json.loads(drill.docker('stats', '--no-stream', '--format', '{{json .}}', probe)[1])
    drill.docker('stop', '--time', '10', probe, timeout=15)
    if int(drill.docker('inspect', '--format', '{{.State.ExitCode}}', probe)[1]) != 0:
        raise RuntimeError('probe-owned-shutdown-failed')
    wrong = adapter('wrong-node-probe', 'not-the-intended-node')
    drill.docker('start', wrong)
    wrong_identity = drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'wrong-node')
    drill.docker('stop', '--time', '10', wrong, timeout=15)
    unrecovered = storage_failure(drill, volumes, mount, source, adapter)
    result = {'passed': True, 'beforeFirstPublication': initial, 'realIngressSaturation': overload,
              'actualStoppedNode': unavailable, 'wrongNode': wrong_identity, 'staleSuccess': stale,
              'actualShutdown': shutdown, 'unrecoveredStorage': unrecovered,
              'sampledAdapterResources': {key: stats[key] for key in ('CPUPerc', 'MemUsage', 'PIDs')},
              'maximumObservationAgeSeconds': 3, 'cloudQualified': False}
    (drill.output / 'probes.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def storage_failure(drill, volumes, mount, source, adapter):
    bad = drill.volume('unrecovered')
    seed = drill.container('unrecovered-seed', ['--user', '0:0', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE',
        '--entrypoint', '/usr/local/bin/python3', *source, *mount(bad, '/bad'), drill.args.image,
        '-I', '/source/tools/container_runtime/qualification_unrecovered.py'])
    drill.attached(seed, 'unrecovered-seed.json')
    anchor = drill.container('unrecovered-namespace', ['--entrypoint', '/usr/local/bin/python3', *source,
        drill.args.image, '-I', '-c', 'import time; time.sleep(90)'], memory='128m', pids='16')
    drill.docker('start', anchor)
    broken = drill.container('unrecovered-node', [*mount(volumes['config'], '/etc/lsf', True),
        '--mount', f'type=volume,source={bad},target=/var/lib/lsf,volume-subpath=data',
        '--mount', f'type=volume,source={bad},target=/var/cache/lsf,volume-subpath=cache',
        drill.args.image], network='container:' + anchor)
    output = drill.attached(broken, 'unrecovered-node.jsonl', codes=(1,))
    if output.strip() != b'latentd: startup: corrupt-artifact':
        raise RuntimeError('unrecovered-clock-state-failure-not-established')
    probe = adapter('unrecovered-probe', 'container-qualification', anchor)
    drill.docker('start', probe)
    result = drill.exec_json(anchor, '/usr/local/bin/python3', SCRIPT, 'wrong-node')
    drill.docker('stop', '--time', '10', probe, timeout=15)
    return {'passed': True, 'corruptDurableClockStateRejected': True, 'adapterAliveButUnready': result}
