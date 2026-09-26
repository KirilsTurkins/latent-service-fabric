"""Exercise two installed nodes under distinct explicitly selected SSH users."""
if __package__:
    from .dev_packaged_guest import observe
    from .dev_packaged_process import require
    from .dev_packaged_windows import Frontend, prepare, verify_language, retained_invocation, preserved_source
else:
    from dev_packaged_guest import observe
    from dev_packaged_process import require
    from dev_packaged_windows import Frontend, prepare, verify_language, retained_invocation, preserved_source


def campaign(api, config, primary, helper_sha, backend_config):
    root = api.root / 'isolation'
    root.mkdir(mode=0o700)
    report = api.report['workspaceIsolation'] = {'commands': [], 'passed': False}
    companion = Frontend(api.executable, root, report)
    try:
        item = report['application'] = prepare(companion, config, 'rust', 3, helper_sha,
                                                backend_config=backend_config)
        verify_language(companion, item)
        require(item['user'] != primary['user'] and item['startup']['node'] != primary['startup']['node'],
                'distinct-live-devcontainer-node-owners-required')
        report['primaryHomeDenied'] = observe(companion, item, 'audit', primary['user'])
        report['companionHomeDenied'] = observe(api, primary, 'audit', item['user'])
        report['primaryWhileBothReady'] = retained_invocation(api, primary)
        name = item['workspace']
        item['down'] = companion.down(name)
        item['repeatedDown'] = companion.call('down', '--workspace', name)
        report['primaryAfterCompanionStop'] = retained_invocation(api, primary)
        item['purge'] = companion.call('purge', '--workspace', name, '--confirm-workspace', name, timeout=120)
        item['repeatedPurge'] = companion.call('purge', '--workspace', name, '--confirm-workspace', name, timeout=120)
        item['preservedSource'] = preserved_source(item)
        report['primaryAfterCompanionPurge'] = retained_invocation(api, primary)
        report['passed'] = True
    finally:
        for name in list(companion.running):
            try:
                report.setdefault('cleanupAttempts', {})[name] = companion.down(name)
            except BaseException as error:
                report.setdefault('cleanupAttempts', {})[name] = {
                    'failure': type(error).__name__, 'remoteTerminationConfirmed': False}
    return report
