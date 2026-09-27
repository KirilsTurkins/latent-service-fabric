"""Real local containers and volumes, bounded lifetime, no cloud API or simulation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


class Drill:
    def __init__(self, args):
        self.args = args
        self.name = 'lsf-container-' + secrets.token_hex(8)
        self.deadline = time.monotonic() + 300
        self.calls = 0
        self.containers = []
        self.volumes = []
        self.output = args.output.resolve()
        self.output.mkdir(mode=0o700, parents=False, exist_ok=False)

    def docker(self, *arguments, codes=(0,), timeout=60):
        self.calls += 1
        if self.calls > 128 or time.monotonic() >= self.deadline:
            raise RuntimeError('container-drill-bound')
        result = subprocess.run(['docker', *map(str, arguments)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=min(timeout, self.deadline - time.monotonic()))
        if result.returncode not in codes or len(result.stdout) + len(result.stderr) > 1048576:
            # Arguments contain paths/identities only. Credentials remain in private volumes.
            diagnostic = result.stderr.decode(errors='replace')[:4096]
            raise RuntimeError('container-command-failed: ' + str(arguments[:2]) + ': ' + diagnostic)
        return result.returncode, result.stdout + (result.stderr if result.returncode else b'')

    def volume(self, kind):
        name = self.name + '-' + kind
        self.docker('volume', 'create', '--label', 'io.latent.container-qualification=' + self.name, name)
        self.volumes.append(name)
        return name

    def container(self, suffix, arguments):
        name = self.name + '-' + suffix
        self.docker('create', '--name', name, '--label', 'io.latent.container-qualification=' + self.name,
                    '--cpus', '2', '--memory', '1g', '--pids-limit', '128', '--network', 'none',
                    '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--log-driver', 'json-file', '--log-opt', 'max-size=1m', '--log-opt', 'max-file=1', *arguments)
        self.containers.append(name)
        return name

    def attached(self, name, destination, codes=(0,)):
        status, output = self.docker('start', '--attach', name, codes=codes, timeout=120)
        (self.output / destination).write_bytes(output)
        actual = json.loads(self.docker('inspect', '--format', '{{.State.ExitCode}}', name)[1])
        if actual not in codes or status not in codes:
            raise RuntimeError('container-exit-status')
        return output

    def exec_json(self, name, *arguments):
        return json.loads(self.docker('exec', name, *arguments, timeout=100)[1])

    def ready(self, node):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status, output = self.docker('exec', node, '/opt/lsf/release/bin/latent', '--config',
                '/etc/lsf/client.json', '--output', 'json', 'node', 'get', 'container-qualification',
                codes=(0, 1, 5, 6, 7, 9, 12), timeout=8)
            if status == 0:
                report = json.loads(output)
                if report.get('outcomeKnown') and report['data']['inventory']['health']['ready'] is True:
                    return
            time.sleep(0.2)
        raise RuntimeError('authenticated-container-readiness-timeout')

    def run(self):
        volumes = {key: self.volume(key) for key in ('config', 'work', 'data', 'cache')}
        def mount(source, target, readonly=False, kind='volume'):
            return ['--mount', f'type={kind},source={source},target={target}' + (',readonly' if readonly else '')]
        source = mount(ROOT, '/source', True, 'bind')
        native = mount(self.args.release_directory.resolve(), '/native', True, 'bind')
        seed = self.container('seed', ['--user', '0:0', '--cap-add', 'CHOWN', '--cap-add', 'FOWNER', '--cap-add', 'DAC_OVERRIDE',
            '--entrypoint', '/usr/local/bin/python3', *source,
            *sum((mount(volumes[key], '/' + key) for key in volumes), []), self.args.image,
            '-I', '/source/tools/container_runtime/qualification_seed.py', 'fresh-test-volumes'])
        self.attached(seed, 'seed.json')
        publisher = self.container('publisher', ['--user', '10001:10001', '-e', 'TMPDIR=/work',
            *source, *native, *mount(volumes['config'], '/config'), *mount(volumes['work'], '/work'),
            self.args.frontend_image, '/source/tools/container_runtime/qualification_inputs.mjs'])
        self.attached(publisher, 'publisher.json')
        mounts = [*mount(volumes['config'], '/etc/lsf', True), *mount(volumes['work'], '/work', True),
                  *mount(volumes['data'], '/var/lib/lsf'), *mount(volumes['cache'], '/var/cache/lsf')]
        check = self.container('check', [*mounts, self.args.image, 'check'])
        preflight = json.loads(self.attached(check, 'preflight.json'))
        if preflight.get('passed') is not True:
            raise RuntimeError('container-preflight-failed')
        root = self.container('reject-root', ['--user', '0:0', *mounts, self.args.image, 'check'])
        denied = json.loads(self.attached(root, 'reject-root.json', codes=(1,)))
        if denied.get('reason') != 'run-as-uid-and-gid-10001':
            raise RuntimeError('root-rejection-reason')
        node = self.container('node', [*mounts, self.args.image])
        self.docker('start', node)
        self.ready(node)
        self.docker('cp', ROOT / 'tools/container_runtime/qualification_inside.py', node + ':/var/cache/lsf/qualification.py')
        published = self.exec_json(node, '/usr/local/bin/python3', '/var/cache/lsf/qualification.py', 'publish')
        (self.output / 'publication.json').write_text(json.dumps(published) + '\n')
        begin = time.monotonic()
        self.docker('stop', '--time', '10', node, timeout=15)
        stopped = json.loads(self.docker('inspect', '--format', '{{.State.ExitCode}}', node)[1])
        if stopped != 0:
            raise RuntimeError('native-signal-shutdown-failed')
        logs = self.docker('logs', node)[1]
        (self.output / 'shutdown.jsonl').write_bytes(logs)
        # Enforced admission persists an upper wall-clock lease. Respect it after restart.
        time.sleep(6)
        self.docker('start', node)
        self.ready(node)
        reopened = self.exec_json(node, '/usr/local/bin/python3', '/var/cache/lsf/qualification.py', 'reopen')
        elapsed = round((time.monotonic() - begin) * 1000)
        self.docker('stop', '--time', '10', node, timeout=15)
        if json.loads(self.docker('inspect', '--format', '{{.State.ExitCode}}', node)[1]) != 0:
            raise RuntimeError('second-native-shutdown-failed')
        report = {'schemaVersion': 'latent.container-qualification.v1', 'passed': True,
                  'preflight': preflight, 'publication': published, 'restart': reopened,
                  'shutdownExitCode': stopped, 'stopToVerifiedRestartMillis': elapsed,
                  'imageId': self.docker('image', 'inspect', '--format', '{{.Id}}', self.args.image)[1].decode().strip(),
                  'cloudQualified': False, 'negativeChecks': ['root-identity-rejected'],
                  'dockerProcesses': self.calls, 'maximumSeconds': 300, 'privilegedRuntime': False}
        (self.output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
        return report

    def cleanup(self):
        # Remove only exact resources created by this invocation, never prune or enumerate user data.
        for kind, names in [('container', self.containers), ('volume', self.volumes)]:
            for name in reversed(names):
                command = ['docker', kind, 'inspect', name]
                result = subprocess.run(command, capture_output=True, timeout=10)
                if result.returncode:
                    continue
                item = json.loads(result.stdout)[0]
                labels = item['Config']['Labels'] if kind == 'container' else item['Labels']
                if labels.get('io.latent.container-qualification') != self.name:
                    raise RuntimeError('qualification-cleanup-owner-changed')
                subprocess.run(['docker', kind, 'rm', *(['--force'] if kind == 'container' else []), name],
                               check=True, stdout=subprocess.DEVNULL, timeout=15)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--frontend-image', required=True)
    parser.add_argument('--release-directory', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    for identity in (args.image, args.frontend_image):
        if not re.fullmatch(r'[a-z0-9][a-zA-Z0-9/_.:@-]{0,255}', identity):
            parser.error('explicit built image identity required')
    drill = Drill(args)
    try:
        print(json.dumps(drill.run()))
    finally:
        drill.cleanup()


if __name__ == '__main__':
    main()
