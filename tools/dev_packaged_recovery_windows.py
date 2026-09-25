"""Exercise real expiry, authority and conflicting actors with approved installed packages."""
import argparse
from pathlib import Path
import os
import platform
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

if __package__:
    from .dev_packaged_authority import arguments, call as observe_recovery
    from .dev_packaged_bootstrap import authenticate, extract
    from .dev_packaged_guest import observe
    from .dev_packaged_process import MAX_COMMANDS, ProbeFailure, read_json, require, write_json
    from .dev_packaged_recovery import inject
    from .dev_packaged_windows import Frontend, acquire, make_private, prepare, preserved_source, retained_invocation, verify_language
    from .dev_packaged_wsl_lifecycle import stop_owned_distribution
else:
    from dev_packaged_authority import arguments, call as observe_recovery
    from dev_packaged_bootstrap import authenticate, extract
    from dev_packaged_guest import observe
    from dev_packaged_process import MAX_COMMANDS, ProbeFailure, read_json, require, write_json
    from dev_packaged_recovery import inject
    from dev_packaged_windows import Frontend, acquire, make_private, prepare, preserved_source, retained_invocation, verify_language
    from dev_packaged_wsl_lifecycle import stop_owned_distribution


def keep_original(api, item, injected, code):
    original = observe(api, item, 'journal')
    require(original['pending'] == {key: injected['pending'][key] for key in ('id', 'kind')},
            'one-original-unresolved-identity-required')
    response = api.call('recover', '--workspace', item['workspace'], expected_uncertain={code})
    blocked = api.call('deploy', '--workspace', item['workspace'],
                       expected_uncertain={'recover-original-operation-before-new-mutation'})
    case = arguments(item)
    descriptor = read_json(Path(item['project']) / 'latent.project.json')
    cases = [value for name in descriptor['scenarios'] for value in read_json(Path(item['project']) / name)['scenarios']]
    source = next(value['input'] for value in cases if value['expect']['category'] == 'success')
    invocation = api.call('invoke', '--workspace', item['workspace'], '--service', case['service'],
        '--contract', case['contract'], '--function', case['function'], '--media-type', case['mediaType'],
        '--input', Path(item['project']) / source, expected_uncertain={'recover-original-operation-before-new-mutation'})
    after = observe(api, item, 'journal')
    require(after == original, 'unresolved-intent-replaced-or-settled')
    return {'recovery': response, 'blockedDeployment': blocked, 'blockedInvocation': invocation,
            'journalBefore': original, 'journalAfter': after, 'effectReplay': False, 'sameOriginalRetained': True}


def run(config, output):
    require(os.name == 'nt' and platform.machine().lower() in {'amd64', 'x86_64'}, 'actual-windows-x64-required')
    require(config['consentProvisionAndInstall'] is True and config['independentPolicyApproved'] is True,
            'explicit-provision-install-and-policy-approval-required')
    require(not output.exists() and output.parent.is_dir(), 'new-existing-parent-output-required')
    make_private(output)
    began = time.monotonic()
    report = {'schemaVersion': 'latent.dev.packaged-recovery-probe.v1', 'passed': False, 'qualificationComplete': False,
        'sourceCommit': config['sourceCommit'], 'host': {'osVersion': platform.version(), 'architecture': platform.machine()},
        'sourceCheckoutUsedByApplication': False, 'runtimeCompiled': False, 'commands': [], 'workspaces': {},
        'cleanup': 'not-started', 'phase': 'authenticate', 'limits': {'commands': MAX_COMMANDS,
            'reservedCleanupCommands': 24, 'receiptBytes': 16777216, 'scheduleSeconds': 7200}}
    api = None
    try:
        manifest, report['bootstrap'] = authenticate(config, output)
        executable = extract(Path(config['artifacts']['windows']), manifest, output / 'frontend')
        api = Frontend(executable, output, report)
        report['doctor'] = api.call('doctor')
        report['frontend'] = acquire(api, config, config['artifacts']['windows'], 'windows-x86_64')
        image = acquire(api, config, config['artifacts']['wsl'], 'linux-x86_64-wsl-rootfs')
        inventory = read_json(api.state / 'bundles' / image['bundle'] / 'rootfs-inventory.json')
        report['provision'] = api.call('provision', '--bundle', image['bundle'], '--consent-provision', timeout=360)
        report['phase'] = 'two-installed-workspaces'
        for index, kind in enumerate(('expiry', 'unknown'), 11):
            item = report['workspaces'][kind] = prepare(api, config, 'rust', index, inventory['helperSha256'], recovery_case=kind)
            verify_language(api, item)
            write_json(output / 'observation.json', report)
        expiry, unknown = (report['workspaces'][name] for name in ('expiry', 'unknown'))
        require(expiry['user'] != unknown['user']
            and expiry['tests']['identity']['node'] != unknown['tests']['identity']['node'], 'separate-recovery-workspace-owners')
        expiry['isolation'] = observe(api, expiry, 'audit', unknown['user'])
        unknown['isolation'] = observe(api, unknown, 'audit', expiry['user'])
        before = observe_recovery(api, config, unknown, 'deployment-state')
        report['phase'] = 'authority'
        report['authority'] = observe_recovery(api, config, unknown, 'authority', {'arguments': arguments(unknown)})
        report['phase'] = 'actual-receipt-expiry'
        observed = report['expiry'] = observe_recovery(api, config, expiry, 'expire-original-invoke',
                                                      {'arguments': arguments(expiry)})
        observed['noReplay'] = keep_original(api, expiry, observed['injection'], 'original-activation-receipt-unavailable-no-replay')
        observed['otherWorkspaceInvocation'] = retained_invocation(api, unknown)
        require(observe_recovery(api, config, unknown, 'deployment-state') == before, 'unresolved-workspace-changed-another')
        observed['otherWorkspaceDeploymentUnchanged'] = True
        write_json(output / 'observation.json', report)
        report['phase'] = 'concurrent-deployment'
        concurrent = report['concurrent'] = {'injection': inject(api, config, unknown, 'concurrent')}
        concurrent['rejection'] = api.call('deploy', '--workspace', unknown['workspace'],
                                          rejection={'concurrent-deployment-change-no-overwrite'})
        after = observe_recovery(api, config, unknown, 'deployment-state')
        require(after['controller'] == before['controller']
            and after['serverGeneration'] == concurrent['injection']['serverGeneration'], 'conflict-overwrote-another-actor')
        concurrent.update(controllerUnchanged=True, actorUnchanged=True, observed=after)
        report['phase'] = 'unknown-original-operation'
        original = report['unknown'] = {'injection': inject(api, config, unknown, 'unknown')}
        original['noReplay'] = keep_original(api, unknown, original['injection'], 'original-operation-unknown-or-expired-no-replay')
        require(observe_recovery(api, config, unknown, 'deployment-state') == after, 'unknown-intent-changed-deployment')
        report['phase'] = 'retain-original-intents-and-stop'
        for kind, item in report['workspaces'].items():
            item['shutdown'] = api.down(item['workspace'])
            item['authoredSourceRetained'] = preserved_source(item)
            item['retainedJournal'] = observe(api, item, 'journal')
            require(item['retainedJournal'] == report[kind]['noReplay']['journalAfter'],
                    'shutdown-changed-original-intent-or-history')
        report['distroStopped'] = stop_owned_distribution(api)
        report.update(passed=True, phase='complete', cleanup='owned-nodes-and-distro-stopped-private-original-intents-retained')
    except BaseException as error:
        report['failure'] = str(error) if isinstance(error, ProbeFailure) else type(error).__name__
        report['cleanup'] = 'failed-attempt-private-state-retained'
        raise
    finally:
        if api is not None and api.running:
            report['cleanupAttempts'] = {}
            for name in list(api.running):
                try:
                    report['cleanupAttempts'][name] = api.down(name)
                except BaseException as error:
                    report['cleanupAttempts'][name] = {'failure': type(error).__name__, 'remoteTerminationConfirmed': False}
            report['cleanup'] = 'failed-attempt-private-workspaces-retained-inspect-cleanup-receipts'
        report['seconds'] = round(time.monotonic() - began, 3)
        write_json(output / 'observation.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(read_json(args.inputs.absolute()), args.output.absolute())
    print('Packaged Windows recovery schedule passed:', result['passed'])
