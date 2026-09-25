"""Exercise the packaged frontend inside the generated, unprivileged devcontainer."""
from pathlib import Path
import json
import os
import platform
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_packaged_bootstrap import authenticate
    from dev_packaged_process import ProbeFailure, digest, read_json, require, write_json
    from dev_packaged_windows import Frontend, acquire, prepare, verify_language, retained_invocation, preserved_source
    from dev_packaged_watch import campaign as watch_campaign
    from dev_packaged_recovery import deploy_with_lost_responses, invoke_with_lost_response
    from dev_packaged_failures import node_campaign
else:
    from .dev_packaged_bootstrap import authenticate
    from .dev_packaged_process import ProbeFailure, digest, read_json, require, write_json
    from .dev_packaged_windows import Frontend, acquire, prepare, verify_language, retained_invocation, preserved_source
    from .dev_packaged_watch import campaign as watch_campaign
    from .dev_packaged_recovery import deploy_with_lost_responses, invoke_with_lost_response
    from .dev_packaged_failures import node_campaign


def run():
    require(sys.platform == 'linux' and os.getuid() == 10001, 'declared-devcontainer-user-required')
    home = Path('/home/latent-dev')
    config = read_json(home / 'selected-inputs.json')
    require(config['independentPolicyApproved'] is True and config['consentProvisionAndInstall'] is True,
            'independently-approved-devcontainer-inputs-required')
    output = home / 'qualification'
    require(not output.exists(), 'fresh-devcontainer-schedule-required')
    output.mkdir(mode=0o700)
    began = time.monotonic()
    report = {'schemaVersion': 'latent.dev.packaged-devcontainer-probe.v1', 'passed': False,
        'qualificationComplete': False, 'sourceCommit': config['sourceCommit'], 'commands': [],
        'sourceCheckoutUsedByApplication': False, 'runtimeCompiled': False,
        'host': {'osVersion': Path('/etc/os-release').read_text(), 'architecture': platform.machine(),
                 'kernel': platform.release(), 'uid': os.getuid()}, 'cleanup': 'not-started'}
    api = None
    try:
        absent = [name for name in ('gcc', 'g++', 'clang', 'rustc', 'cargo', 'dotnet', 'javac', 'go', 'node')
                  if shutil.which(name) is None]
        require(len(absent) == 9, 'no-sdk-or-runtime-compiler-in-devcontainer')
        report['absentCompilers'] = absent
        manifest, report['bootstrap'] = authenticate(config, output, target='linux-x86_64')
        # The image build verified all members. Recheck the executable actually
        # selected here before its first invocation inside this container.
        executable = Path('/opt/latent-dev/bin/latent-dev')
        pin = next(row for row in manifest['files'] if row['path'] == 'bin/latent-dev')
        require(digest(executable) == pin['sha256'], 'generated-image-frontend-digest')
        api = Frontend(executable, output, report)
        report['doctor'] = api.call('doctor')
        report['frontend'] = acquire(api, config, config['artifacts']['linux'], 'linux-x86_64')
        item = report['application'] = prepare(api, config, 'rust', 2, config['linuxHelperSha256'],
            backend_config=home / 'ssh-backend.json', project_parent=Path('/workspaces/project'))
        deploy_with_lost_responses(api, config, item)
        verify_language(api, item)
        invoke_with_lost_response(api, config, item)
        report['editor'] = api.call('editor', '--workspace', item['workspace'], '--project', item['project'],
                                   '--frontend', executable)
        tasks = read_json(Path(item['project']) / '.vscode/tasks.json')
        require(tasks['version'] == '2.0.0' and all(task['type'] == 'process' for task in tasks['tasks']),
                'same-process-task-contract-required')
        report['editorTasksSha256'] = digest(Path(item['project']) / '.vscode/tasks.json')
        report['logs'] = api.call('logs', '--workspace', item['workspace'])
        item['down'] = api.down(item['workspace'])
        item['restart'] = api.start(item['workspace'])
        item['retainedInvocation'] = retained_invocation(api, item)
        item['finalDown'] = api.down(item['workspace'])
        item['purge'] = api.call('purge', '--workspace', item['workspace'], '--confirm-workspace', item['workspace'], timeout=120)
        item['preservedSource'] = preserved_source(item)
        report['watchApplication'] = watch_campaign(api, config, config['linuxHelperSha256'],
            backend_config=home / 'ssh-backend.json', project_parent=Path('/workspaces/project'))
        report['closedProfile'] = node_campaign(api, config, config['linuxHelperSha256'],
            backend_config=home / 'ssh-backend.json', project_parent=Path('/workspaces/project'))
        report.update(passed=True, cleanup='owned-remote-node-reaped-workspace-purged-client-state-retained')
    except BaseException as error:
        report['failure'] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        raise
    finally:
        if api is not None and api.running:
            report['cleanupAttempts'] = {}
            for name in list(api.running):
                try:
                    report['cleanupAttempts'][name] = api.down(name)
                except BaseException as error:
                    report['cleanupAttempts'][name] = {'failure': type(error).__name__, 'remoteTerminationConfirmed': False}
        report['seconds'] = round(time.monotonic() - began, 3)
        write_json(output / 'observation.json', report)
    return report


if __name__ == '__main__':
    print(json.dumps({'passed': run()['passed']}))
