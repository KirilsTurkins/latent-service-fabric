"""Own one clean, disconnected Linux OS container for the explicit packaged schedule."""
from pathlib import Path
import argparse
import json
import os
import re
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_packaged_bootstrap import authenticate, extract
    from dev_packaged_process import Command, ProbeFailure, digest, environment, read_json, require, write_json
else:
    from .dev_packaged_bootstrap import authenticate, extract
    from .dev_packaged_process import Command, ProbeFailure, digest, environment, read_json, require, write_json


def run(config, output):
    require(sys.platform == 'linux' and config['independentPolicyApproved'] is True
            and config['consentProvisionAndInstall'] is True, 'approved-disposable-linux-qualification-required')
    require(not output.exists(), 'new-linux-container-output-required')
    output.mkdir(mode=0o700)
    report = {'schemaVersion': 'latent.dev.packaged-linux-container.v1', 'passed': False,
        'qualificationComplete': False, 'commands': [], 'cleanup': 'not-started',
        'sourceCommit': config['sourceCommit'], 'publiclyPublished': False,
        'limits': {'memoryBytes': 8589934592, 'cpus': 2, 'pids': 512, 'scheduleSeconds': 7200,
                   'containerSeconds': 3600, 'hostCommands': 384}}
    name = 'lsf-package-qualification-' + os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    require(re.fullmatch(r'lsf-package-qualification-[0-9]{1,20}-[0-9]{1,4}', name), 'exact-disposable-container-name')
    container = None

    def command(argv, seconds, *, allowed=(0,)):
        require(len(report['commands']) < 384, 'linux-host-command-count-limit')
        child = Command(argv, output, environment(output))
        try:
            require(child.finish(seconds) in allowed, 'owned-container-command-failed-' + str(argv[1]))
            return child.raw()
        finally:
            try:
                child.abort_controller()
            finally:
                report['commands'].append(child.receipt())

    try:
        require(shutil.disk_usage(output).free >= 30 * 1024**3, 'qualification-host-free-space-bound')
        manifest, report['bootstrap'] = authenticate(config, output, target='linux-x86_64')
        frontend = output / 'authenticated-frontend'
        extract(Path(config['artifacts']['linux']), manifest, frontend)
        helper = frontend / 'helper.pyz'
        expected = next(entry for entry in manifest['files'] if entry['path'] == 'helper.pyz')
        require(digest(helper) == expected['sha256'], 'authenticated-helper-identity')
        context = output / 'os-context'
        context.mkdir(mode=0o700)
        shutil.copyfile(helper, context / 'helper.pyz')
        support = Path(__file__).resolve().parent
        shutil.copyfile(support / 'qualification.Dockerfile', context / 'Dockerfile')
        conductor = context / 'conductor'
        conductor.mkdir()
        for path in support.glob('dev_packaged_*.py'):
            shutil.copyfile(path, conductor / path.name)
        for input_module in ('dev_failure_case_inputs.py', 'dev_clock_case_inputs.py', 'dev_watch_case_inputs.py'):
            shutil.copyfile(support / input_module, conductor / input_module)
        inputs = output / 'container-inputs'
        inputs.mkdir(mode=0o700)
        shutil.copytree(support, inputs / 'support')
        (inputs / 'artifacts').mkdir()
        for kind in ('linux', 'rust', 'native'):
            shutil.copytree(config['artifacts'][kind], inputs / 'artifacts' / kind)
        selected = {**config, 'linuxHelperSha256': expected['sha256']}
        write_json(inputs / 'inputs.json', selected)
        before = command(['docker', 'ps', '-a', '--format', '{{.Names}}'], 15).decode().splitlines()
        require(name not in before, 'qualification-container-already-exists')
        command(['docker', 'build', '--network', 'default', '--tag', name, str(context)], 1200)
        image = json.loads(command(['docker', 'image', 'inspect', name], 15))[0]
        report['image'] = {'id': image['Id'], 'created': image['Created'], 'dockerfileSha256': digest(context / 'Dockerfile')}
        argv = ['docker', 'create', '--name', name, '--init', '--network', 'none', '--memory', '8g',
                '--cpus', '2', '--pids-limit', '512', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges']
        for capability in ('CHOWN', 'DAC_OVERRIDE', 'FOWNER', 'SETUID', 'SETGID', 'SYS_CHROOT', 'KILL'):
            argv.extend(['--cap-add', capability])
        argv.extend(['--mount', 'type=bind,source=' + str(inputs) + ',target=/qualification-inputs,readonly', image['Id']])
        container = command(argv, 30).decode().strip()
        require(re.fullmatch(r'[a-f0-9]{64}', container), 'owned-container-id')
        created = json.loads(command(['docker', 'inspect', container], 15))[0]
        require(created['Name'] == '/' + name and created['Image'] == image['Id']
                and created['HostConfig']['NetworkMode'] == 'none', 'owned-container-identity-or-network')
        report['container'] = {'id': container, 'name': name, 'network': 'none', 'privileged': created['HostConfig']['Privileged']}
        require(report['container']['privileged'] is False, 'unprivileged-container-required')
        command(['docker', 'start', container], 20)
        deadline = time.monotonic() + 3600
        while True:
            stopped = json.loads(command(['docker', 'inspect', container], 15))[0]
            require(stopped['Id'] == container and stopped['Name'] == '/' + name and stopped['Image'] == image['Id'],
                    'original-container-owner-changed')
            if stopped['State']['Running'] is False:
                break
            require(time.monotonic() < deadline, 'linux-container-schedule-deadline')
            time.sleep(min(10, max(0, deadline - time.monotonic())))
        # Eight independently installed node workspaces share this outer hour;
        # application commands keep their original individual deadlines.
        report['exitCode'] = stopped['State']['ExitCode']
        require(stopped['State']['Running'] is False and stopped['State']['ExitCode'] == report['exitCode'], 'container-stop-unconfirmed')
        command(['docker', 'cp', container + ':/home/lsfqa/observation/observation.json', str(output / 'observation.json')], 30)
        observation = read_json(output / 'observation.json', 16 * 1024 * 1024)
        require(report['exitCode'] == 0 and observation['passed'] is True, 'packaged-linux-schedule-failed')
        report.update(passed=True, cleanup='owned-container-stopped-private-state-retained-until-runner-teardown')
    except BaseException as error:
        report['failure'] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        report['cleanup'] = 'owned-container-state-unconfirmed-inspect-original-id' if container else 'no-container-created'
        raise
    finally:
        if container is not None:
            try:
                observed = json.loads(command(['docker', 'inspect', container], 15))[0]
                require(observed['Id'] == container and observed['Name'] == '/' + name
                        and observed['Image'] == image['Id'], 'original-container-owner-changed')
                if observed['State']['Running']:
                    command(['docker', 'stop', '--time', '30', container], 40)
                    observed = json.loads(command(['docker', 'inspect', container], 15))[0]
                require(observed['Id'] == container and observed['State']['Running'] is False,
                        'owned-container-stop-unconfirmed')
                report['containerShutdown'] = {'stopped': True, 'exitCode': observed['State']['ExitCode']}
                report['cleanup'] = 'owned-container-stopped-private-state-retained-until-runner-teardown'
            except BaseException as error:
                report['containerShutdown'] = {'stopped': False, 'failure': type(error).__name__}
                report.update(passed=False, cleanup='owned-container-state-unconfirmed-inspect-original-id')
        write_json(output / 'host-observation.json', report)
    require(report['passed'], 'owned-linux-container-cleanup-failed')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(read_json(args.inputs), args.output.absolute())
