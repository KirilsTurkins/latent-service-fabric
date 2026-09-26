"""Execute the generated terminal devcontainer with a separate owned SSH peer."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_packaged_bootstrap import authenticate, extract
    from dev_packaged_process import Command, ProbeFailure, digest, environment, read_json, require, write_json
    from dev_packaged_windows import Frontend, acquire
else:
    from .dev_packaged_bootstrap import authenticate, extract
    from .dev_packaged_process import Command, ProbeFailure, digest, environment, read_json, require, write_json
    from .dev_packaged_windows import Frontend, acquire

CLI_SHA512 = 'LzaoOGKQ/Zql6PsiZ4hVIYVZagzWkD65aG/1ou5/Kly5Y1PtjLg1yn7qu+LZCzVoAl6DZZ/pbz8qOO4RLNlqMg=='


def extract_cli(source, destination):
    require(source.stat().st_size <= 64 * 1024 * 1024
        and base64.b64encode(hashlib.sha512(source.read_bytes()).digest()).decode() == CLI_SHA512,
        'reviewed-devcontainer-cli-archive-required')
    with tarfile.open(source, 'r:gz') as archive:
        rows = archive.getmembers()
        require(len(rows) <= 4096 and sum(row.size for row in rows) <= 128 * 1024 * 1024, 'devcontainer-cli-size-bound')
        require(all((row.isdir() or row.isfile()) and not row.name.startswith('/')
                    and '\\' not in row.name and '..' not in Path(row.name).parts for row in rows), 'devcontainer-cli-path')
        archive.extractall(destination, filter='data')
    entry = destination / 'package/devcontainer.js'
    require(entry.is_file(), 'devcontainer-cli-entrypoint')
    return entry


def run(config, linux_output, output):
    require(sys.platform == 'linux' and config['independentPolicyApproved'] is True
            and config['consentProvisionAndInstall'] is True, 'approved-owned-devcontainer-schedule-required')
    previous = read_json(linux_output / 'host-observation.json', 16 * 1024 * 1024)
    require(previous['passed'] is True and previous['sourceCommit'] == config['sourceCommit'], 'qualified-linux-prerequisite')
    require(not output.exists(), 'new-devcontainer-output-required')
    output.mkdir(mode=0o700)
    began = time.monotonic()
    report = {'schemaVersion': 'latent.dev.packaged-devcontainer-host.v1', 'passed': False,
        'qualificationComplete': False, 'sourceCommit': config['sourceCommit'], 'commands': [], 'cleanup': 'not-started',
        'limits': {'hostCommands': 64, 'clientSeconds': 2400, 'peerSeconds': 4800, 'clientMemoryBytes': 2147483648}}
    peer = client = label = None

    def call(argv, seconds, *, allowed=(0,), terminal=False):
        require(len(report['commands']) < 64, 'devcontainer-host-command-bound')
        child = Command(argv, output, environment(output))
        try:
            code = child.finish(seconds)
            if code not in allowed and terminal:
                # This CLI only sees the generated public configuration and OS
                # build. Retain its bounded structured error, never docker
                # inspection output, environment or private workspace files.
                try:
                    failure = json.loads(child.raw())
                except (ValueError, UnicodeError):
                    failure = {}
                report['terminalFailure'] = {key: failure[key][:2048]
                    for key in ('outcome', 'message', 'description')
                    if isinstance(failure, dict) and isinstance(failure.get(key), str)}
            require(code in allowed, 'devcontainer-host-command-failed')
            return child.raw()
        finally:
            try:
                child.abort_controller()
            finally:
                report['commands'].append(child.receipt())

    try:
        support = Path(__file__).resolve().parent
        node = shutil.which('node')
        require(node is not None and call([node, '--version'], 10).strip() == b'v24.19.0', 'reviewed-node-tool-required')
        cli = extract_cli(support / 'devcontainer-cli.tgz', output / 'cli')
        report['terminalTool'] = {'version': '0.89.0', 'archiveSha512Base64': CLI_SHA512, 'node': '24.19.0'}
        manifest, report['bootstrap'] = authenticate(config, output, target='linux-x86_64')
        executable = extract(Path(config['artifacts']['linux']), manifest, output / 'frontend')
        setup = output / 'setup'
        setup.mkdir(mode=0o700)
        report['frontendCommands'] = {'commands': []}
        api = Frontend(executable, setup, report['frontendCommands'])
        selected = acquire(api, config, config['artifacts']['linux'], 'linux-x86_64')
        project = output / 'Project spaces-\u00fc'
        project.mkdir(mode=0o700)
        generated = api.call('devcontainer', '--project', project, '--bundle', selected['bundle'], '--consent-files', timeout=330)
        report['generated'] = generated
        volume = generated['volume']
        require(re.fullmatch(r'lsf-dev-[a-f0-9]{16}', volume), 'generated-private-volume-name')
        require(volume not in call(['docker', 'volume', 'ls', '--format', '{{.Name}}'], 15).decode().splitlines(),
                'devcontainer-volume-already-exists')
        call(['docker', 'volume', 'create', volume], 15)
        name = 'lsf-devcontainer-peer-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
        require(re.fullmatch(r'lsf-devcontainer-peer-[0-9]{1,20}-[0-9]{1,4}', name), 'owned-peer-name')
        require(name not in call(['docker', 'ps', '-a', '--format', '{{.Names}}'], 15).decode().splitlines(), 'owned-peer-already-exists')
        image = previous['image']['id']
        require(re.fullmatch(r'sha256:[a-f0-9]{64}', image), 'exact-previous-os-image')
        argv = ['docker', 'create', '--name', name, '--init', '--network', 'none', '--memory', '8g', '--cpus', '2',
                '--pids-limit', '512', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges']
        for capability in ('CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'SETUID', 'SETGID', 'SYS_CHROOT', 'KILL'):
            argv.extend(['--cap-add', capability])
        argv.extend(['--mount', 'type=volume,source=' + volume + ',target=/qualification-client-home',
            '--mount', 'type=bind,source=' + str(project) + ',target=/qualification-project',
            '--mount', 'type=bind,source=' + str(linux_output / 'container-inputs') + ',target=/qualification-inputs,readonly',
            '--entrypoint', '/usr/local/bin/python3.13', image, '-I', '-B', '/qualification/dev_packaged_container_peer.py'])
        peer = call(argv, 30).decode().strip()
        require(re.fullmatch(r'[a-f0-9]{64}', peer), 'exact-owned-peer-id')
        inspected_peer = json.loads(call(['docker', 'inspect', peer], 15))[0]
        require(inspected_peer['Image'] == image and inspected_peer['Name'] == '/' + name
                and inspected_peer['HostConfig']['NetworkMode'] == 'none'
                and inspected_peer['HostConfig']['Privileged'] is False, 'owned-peer-identity')
        report['peer'] = {'id': peer, 'image': image, 'network': 'none'}
        # Copy only the pinned OS interpreter for the separate test conductor.
        # It is a read-only test mount, not an application or image prerequisite.
        python_root = output / 'conductor-python'
        call(['docker', 'cp', peer + ':/usr/local', str(python_root)], 120)
        call(['docker', 'start', peer], 20)
        deadline = time.monotonic() + 30
        while True:
            ready = call(['docker', 'exec', '--user', '10001:10001', peer, '/bin/cat',
                          '/qualification-client-home/peer-ready.json'], 10, allowed=(0, 1))
            if ready:
                report['peer']['ready'] = json.loads(ready)
                require(report['peer']['ready']['ready'] is True, 'explicit-ssh-peer-readiness')
                break
            require(time.monotonic() < deadline, 'explicit-ssh-peer-readiness-deadline')
            time.sleep(1)
        original = project / '.devcontainer/devcontainer.json'
        options = read_json(original)
        report['generatedConfigurationSha256'] = digest(original)
        # Explicitly choose a shared, disconnected network namespace so the SSH
        # address is valid. This never publishes or forwards management ports.
        options['runArgs'].append('--network=container:' + peer)
        options['mounts'].append('source=' + str(python_root) + ',target=/usr/local,type=bind,readonly')
        # The CLI accepts only devcontainer.json or .devcontainer.json. Keep
        # this beside the generated file so its relative build paths are intact.
        selected_config = project / '.devcontainer/.devcontainer.json'
        write_json(selected_config, options)
        report['qualificationConfigurationSha256'] = digest(selected_config)
        cli_state = output / 'cli-state'
        cli_state.mkdir(mode=0o700)
        label = 'lsf.qualification-dev559=' + generated['nonce']
        require(not call(['docker', 'ps', '-aq', '--filter', 'label=' + label], 15).strip(), 'new-container-owner-label-required')
        raw = call([node, cli, 'up', '--workspace-folder', project, '--config', selected_config,
                    '--id-label', label, '--mount-workspace-git-root', 'false', '--skip-post-create',
                    '--user-data-folder', cli_state], 1200, terminal=True)
        started = json.loads(raw)
        require(started.get('outcome') == 'success' and re.fullmatch(r'[a-f0-9]{64}', started.get('containerId', '')),
                'actual-devcontainer-cli-start-required')
        client = started['containerId']
        report['cliStart'] = started
        observed = json.loads(call(['docker', 'inspect', client], 15))[0]
        host = observed['HostConfig']
        mounts = observed['Mounts']
        require(observed['Config']['User'] in {'10001:10001', 'latent-dev'} and host['Privileged'] is False
            and 'ALL' in host['CapDrop'] and host['CapAdd'] in (None, []) and host['NetworkMode'] == 'container:' + peer
            and 'no-new-privileges' in host['SecurityOpt'] and not host['PortBindings']
            and host['Memory'] == 2147483648 and host['NanoCpus'] == 2000000000 and host['PidsLimit'] == 256
            and observed['Config']['Labels']['lsf.qualification-dev559'] == generated['nonce']
            and {row['Destination'] for row in mounts} == {'/workspaces/project', '/home/latent-dev', '/usr/local'}
            and next(row for row in mounts if row['Destination'] == '/usr/local')['RW'] is False
            and next(row for row in mounts if row['Destination'] == '/home/latent-dev')['Name'] == volume,
            'actual-devcontainer-isolation-mismatch')
        report['container'] = {'id': client, 'user': observed['Config']['User'], 'image': observed['Image'],
            'privileged': host['Privileged'], 'capDrop': host['CapDrop'], 'securityOpt': host['SecurityOpt'],
            'network': host['NetworkMode'], 'mounts': [{key: row[key] for key in ('Type', 'Destination', 'RW')} for row in mounts]}
        # This process conducts five separate installed workspaces. Its outer
        # budget is independent of each application's unchanged command limit.
        driver = Command([node, cli, 'exec', '--container-id', client, '--workspace-folder', project,
            '--config', selected_config, '--user-data-folder', cli_state, '/usr/local/bin/python3.13', '-I', '-B',
            '/home/latent-dev/inputs/support/dev_packaged_container_client.py'], output, environment(output))
        try:
            deadline = time.monotonic() + 2400
            while driver.child.poll() is None:
                require(not driver.limit.is_set(), 'devcontainer-conductor-output-limit')
                require(time.monotonic() < deadline, 'devcontainer-conductor-schedule-deadline')
                time.sleep(1)
            require(driver.finish(5) == 0, 'devcontainer-conductor-failed')
        finally:
            try:
                driver.abort_controller()
            finally:
                report['commands'].append(driver.receipt())
        call(['docker', 'cp', client + ':/home/latent-dev/qualification/observation.json', str(output / 'observation.json')], 30)
        require(read_json(output / 'observation.json', 16 * 1024 * 1024)['passed'] is True, 'actual-devcontainer-schedule-failed')
        report['passed'] = True
    except BaseException as error:
        report['failure'] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        raise
    finally:
        report['stops'] = {}
        if client is None and label is not None:
            try:
                found = call(['docker', 'ps', '-aq', '--no-trunc', '--filter', 'label=' + label], 15).decode().splitlines()
                require(len(found) <= 1 and all(re.fullmatch(r'[a-f0-9]{64}', item) for item in found), 'owned-cli-container-ambiguous')
                if found:
                    selected = json.loads(call(['docker', 'inspect', found[0]], 15))[0]
                    require(selected['Config']['Labels']['lsf.qualification-dev559'] == label.split('=', 1)[1],
                            'original-cli-container-owner-mismatch')
                    client = found[0]
            except BaseException as error:
                report['stops']['unresolvedCliContainer'] = {'stopped': False, 'failure': type(error).__name__}
                report['passed'] = False
        for kind, identifier in (('client', client), ('peer', peer)):
            if identifier is None:
                continue
            try:
                if kind == 'client' and not (output / 'observation.json').exists():
                    call(['docker', 'cp', identifier + ':/home/latent-dev/qualification/observation.json',
                          str(output / 'observation.json')], 30, allowed=(0, 1))
                call(['docker', 'stop', '--time', '30', identifier], 40)
                state = json.loads(call(['docker', 'inspect', identifier], 15))[0]
                require(state['Id'] == identifier and state['State']['Running'] is False, 'owned-container-stop-unconfirmed')
                report['stops'][kind] = {'stopped': True, 'exitCode': state['State']['ExitCode']}
            except BaseException as error:
                report['stops'][kind] = {'stopped': False, 'failure': type(error).__name__}
                report['passed'] = False
        report['cleanup'] = ('no-container-created' if not report['stops'] else
            'owned-containers-stopped-private-volume-and-source-retained' if all(item['stopped'] for item in report['stops'].values())
            else 'inspect-original-container-identity-cleanup-unconfirmed')
        report['seconds'] = round(time.monotonic() - began, 3)
        write_json(output / 'host-observation.json', report)
    require(report['passed'], 'devcontainer-cleanup-failed')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--linux-output', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(read_json(args.inputs), args.linux_output.absolute(), args.output.absolute())
