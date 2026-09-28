"""Real TLS edge and native trusted-peer qualification, with no cloud substitution."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'container_runtime'))
from qualification import Drill

ROOT = Path(__file__).resolve().parents[2]
INSIDE = '/source/tools/trusted_edge/qualification_inside.py'


class EdgeDrill(Drill):
    def run(self):
        compression = self.args.compression
        volumes = {key: self.volume(key) for key in ('config', 'work', 'data', 'cache', 'edge')}
        def mount(source, target, readonly=False, kind='volume'):
            return ['--mount', f'type={kind},source={source},target={target}' + (',readonly' if readonly else '')]
        source = mount(ROOT, '/source', True, 'bind')
        native = mount(self.args.release_directory.resolve(), '/native', True, 'bind')
        seed = self.container('seed', ['--user', '0:0', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE',
            '--entrypoint', '/usr/local/bin/python3', *source,
            *sum((mount(volumes[key], '/' + key) for key in volumes), []), self.args.image,
            '-I', '/source/tools/trusted_edge/qualification_seed.py', 'fresh-edge-volumes'])
        self.attached(seed, 'seed.json')
        producer = self.container('inputs', ['--user', '10001:10001', '-e', 'TMPDIR=/work', *source, *native,
            *mount(volumes['config'], '/config'), *mount(volumes['work'], '/work'), *mount(volumes['edge'], '/edge'),
            self.args.frontend_image, '/source/tools/trusted_edge/qualification' + ('_compression' if compression else '') + '_inputs.mjs'])
        self.attached(producer, 'inputs.json')
        mounts = [*mount(volumes['config'], '/etc/lsf', True), *mount(volumes['work'], '/work', True),
                  *mount(volumes['data'], '/var/lib/lsf'), *mount(volumes['cache'], '/var/cache/lsf')]
        node = self.container('node', [*mounts, *source, self.args.image])
        self.docker('start', node); self.ready(node)
        publications = self.exec_json(node, '/usr/local/bin/python3', INSIDE, 'publish')
        compression_inside = '/source/tools/trusted_edge/qualification_compression_inside.py'
        if compression:
            self.exec_json(node, '/usr/local/bin/python3', compression_inside, 'publish')
        def probe(name):
            result = self.container(name, ['--entrypoint', '/usr/local/bin/python3',
                *mount(volumes['config'], '/etc/lsf', True), self.args.image,
                '-I', '/opt/lsf/runtime/probe.py', '--node-id', 'container-qualification'],
                network='container:' + node, memory='128m', pids='32')
            self.docker('start', result); return result
        def edge(name):
            result = self.container(name, [*mount(volumes['edge'], '/etc/lsf', True), self.args.edge_image],
                network='container:' + node, memory='384m' if compression else '192m', pids='32')
            self.docker('start', result); return result
        def client(name):
            result = self.container(name, [*source, *mount(volumes['edge'], '/etc/lsf', True), self.args.frontend_image,
                '/source/tools/trusted_edge/qualification_client.mjs'], network='container:' + node, memory='192m', pids='32')
            value = json.loads(self.attached(result, name + '.json'))
            assert value['passed'] and {row['path']: row['sha256'] for row in value['records']} == {
                row['path']: row['sha256'] for row in publications.values()}
            return value
        adapter = probe('probe'); listener = edge('edge')
        initial = client('client')
        def compressed_client(name, mode='normal', *arguments):
            result = self.container(name, [*source, *mount(volumes['edge'], '/etc/lsf', True), self.args.frontend_image,
                '/source/tools/trusted_edge/qualification_compression_client.mjs', mode, *arguments],
                network='container:' + node, memory='256m', pids='32')
            value = json.loads(self.attached(result, name + '.json'))
            assert value['passed']
            return value
        compressed_initial = compressed_client('compression') if compression else None
        idle = self.exec_json(node, '/usr/local/bin/python3', INSIDE, 'idle')
        resources = json.loads(self.docker('stats', '--no-stream', '--format', '{{json .}}', listener)[1])
        begin = time.monotonic()
        for name in (listener, adapter, node): self.docker('stop', '--time', '10', name, timeout=15)
        logs = self.docker('logs', listener)[1]; (self.output / 'edge.jsonl').write_bytes(logs)
        stopped = [json.loads(line) for line in logs.splitlines() if line.startswith(b'{')][-1]
        assert stopped['event'] == 'stopped' and stopped['active'] == 0
        # Restart changes the Docker network namespace. Recreate both dependants.
        time.sleep(6); self.docker('start', node); self.ready(node)
        adapter = probe('probe-restarted'); listener = edge('edge-restarted')
        restarted = client('client-restarted')
        assert restarted['records'] == initial['records']
        self.exec_json(node, '/usr/local/bin/python3', INSIDE, 'idle')
        elapsed = round((time.monotonic() - begin) * 1000)
        if compression:
            compressed_restart = compressed_client('compression-restarted')
            for left, right in zip(compressed_initial['records'], compressed_restart['records'], strict=True):
                assert {key: value for key, value in left.items() if key != 'requestMillis'} == {
                    key: value for key, value in right.items() if key != 'requestMillis'}
            self.exec_json(node, '/usr/local/bin/python3', compression_inside, 'split-head')
            compressed_client('split-head', 'split-head')
            self.exec_json(node, '/usr/local/bin/python3', compression_inside, 'restore-head')
            self.exec_json(node, '/usr/local/bin/python3', compression_inside, 'revoke-and-corrupt')
            compressed_client('revoked', 'revoked', compressed_initial['records'][0]['etag'])
            self.exec_json(node, '/usr/local/bin/python3', INSIDE, 'idle')
        for name in (listener, adapter, node): self.docker('stop', '--time', '10', name, timeout=15)
        report = {'schemaVersion': 'latent.local-tls-edge-qualification.v1', 'passed': True,
            'initial': initial, 'restart': restarted, 'nativeIdle': idle, 'edgeShutdown': stopped,
            'restartMillis': elapsed, 'sampledResources': {key: resources[key] for key in ('CPUPerc', 'MemUsage', 'PIDs')},
            'fixedPeerPreservedAcrossRestart': '127.0.0.2', 'cloudQualified': False,
            'compression': compressed_initial,
            'revokedPublicationAndCorruptSourceDenied': compression,
            'independentHeadRouteChecked': compression,
            'dockerProcesses': self.calls, 'maximumDockerProcesses': 160, 'maximumSeconds': 300}
        (self.output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('image', 'frontend-image', 'edge-image'): parser.add_argument('--' + flag, required=True)
    for flag in ('release-directory', 'output'): parser.add_argument('--' + flag, required=True, type=Path)
    parser.add_argument('--compression', action='store_true')
    drill = EdgeDrill(parser.parse_args())
    try: print(json.dumps(drill.run()))
    finally: drill.cleanup()
