"""Execute the Windows guide's greeting edits through the installed public frontend."""
import base64
import json
import locale
from pathlib import Path
import time

if __package__:
    from .dev_packaged_guest import observe
    from .dev_packaged_process import digest, read_json, require
else:
    from dev_packaged_guest import observe
    from dev_packaged_process import digest, read_json, require


def reviewed_guide(config):
    selected = config['newcomerGuide']
    path = Path(config['faultProbe']).parent / 'windows-application.md'
    require(selected['path'] == 'docs/component-development/windows-application.md'
        and path.is_file() and not path.is_symlink() and path.stat().st_size <= 65536
        and digest(path) == selected['sha256'], 'exact-reviewed-newcomer-guide-required')
    return {**selected, 'conductorSourceCommit': config['conductorSourceCommit'],
            'execution': 'automated-public-command-walkthrough', 'interactiveEditorReview': False}


def greeting(api, item, expected, selected):
    root = Path(item['project'])
    descriptor = read_json(root / 'latent.project.json')
    result = api.call('invoke', '--workspace', item['workspace'], '--service', descriptor['service'],
        '--contract', 'examples:greeting/api@1.0.0', '--function', 'greet', '--input', root / 'tests/0-input.json')
    require(result['category'] == 'success' and result['outcomeKnown'] is True
        and result['data']['resolvedRevision']['publicationId'] == selected['publication']
        and result['data']['resolvedRevision']['releaseDigest'] == selected['componentDigest']
        and json.loads(base64.b64decode(result['data']['payload']['data'], validate=True)) == [{'ok': expected}],
        'newcomer-greeting-value-or-selected-revision-mismatch')
    return result


def completed(process, selected=None, *, after=0):
    event = process.until(lambda event: event.get('event') == 'post-deploy-tests'
        and (selected is None or event['currentDeployment'] == selected), 330, after=after)
    require(event['passed'] is True and event['report']['selection'] == ['greeting-0']
        and event['rollbackPerformed'] is False, 'newcomer-focused-greeting-failed')
    return event


def diagnostics_finished(process, *, after):
    deadline = time.monotonic() + 5
    while True:
        raw = process.raw(1)[after:]
        if raw.rstrip().endswith(b'LSF build-end'):
            # Windows redirected text can use its native code page. Preserve
            # source paths exactly; replacement characters cannot prove mapping.
            try:
                return raw.decode('utf-8', errors='strict'), 'utf-8'
            except UnicodeDecodeError:
                encoding = locale.getencoding()
                return raw.decode(encoding, errors='strict'), encoding
        require(time.monotonic() < deadline, 'newcomer-live-diagnostic-batch-not-finished')
        time.sleep(0.05)


def campaign(api, config, helper_sha):
    if __package__:
        from .dev_packaged_windows import prepare, preserved_source
    else:
        from dev_packaged_windows import prepare, preserved_source
    guide = reviewed_guide(config)
    item = prepare(api, config, 'rust', 9, helper_sha, newcomer_project=True)
    root, name = Path(item['project']), item['workspace']
    require(item['profile']['admission'] == 'trusted-local', 'newcomer-explicit-trusted-local-profile-required')
    report = item['walkthrough'] = {'passed': False, 'guide': guide,
        'nativeBusinessTest': {'executed': False, 'reason': 'no-native-host-toolchain-selected'},
        'credentialsAuthoredByUser': False, 'runtimeCompiled': False, 'events': []}
    process = None
    try:
        report['startup'] = api.start(name)
        report['doctor'] = api.call('doctor', '--workspace', name)
        selected = report['deployment'] = api.call('deploy', '--workspace', name, timeout=180)
        item['tests'] = api.call('test', '--workspace', name, '--environment', 'node', timeout=330)
        require(item['tests']['passed'] and len(item['tests']['results']) == 3
            and all(case['status'] == 'passed' for case in item['tests']['results'])
            and {case['category'] for case in item['tests']['results']} == {'success', 'declared-error'},
            'three-real-node-greeting-cases-required')
        report['hello'] = greeting(api, item, 'Hello, Ada!', selected)
        report['logs'] = api.call('logs', '--workspace', name)
        report['editorConfiguration'] = api.call('editor', '--workspace', name, '--project', root,
                                                '--frontend', api.executable)
        require(report['editorConfiguration']['automaticExecution'] is False, 'newcomer-editor-auto-execution')
        report['downBeforeWatch'] = api.down(name)
        report['watchReady'] = api.start(name, project=root, selection='greeting-0', editor_diagnostics=True)
        process = api.running[name]
        report['initialFocusedTest'] = completed(process)
        after = len(process.events())
        # Preserve the exact JSON and source byte format specified by the guide.
        # Expected files first keep an intermediate source save from testing stale expectations.
        for relative in ('tests/0-expected.json', 'tests/1-expected.json', 'app/src/lib.rs'):
            path = root / relative
            original = path.read_bytes()
            require(b'Hello,' in original, 'maintained-greeting-source-drift')
            path.write_bytes(original.replace(b'Hello,', b'Welcome,'))
        changed = process.until(lambda event: event.get('event') == 'deployed'
            and event['deployment']['publication'] != selected['publication'], 330, after=after)
        selected = report['welcomeDeployment'] = changed['deployment']
        report['welcomeFocusedTest'] = completed(process, selected, after=after)
        report['welcome'] = greeting(api, item, 'Welcome, Ada!', selected)

        source = root / 'app/src/lib.rs'
        valid = source.read_bytes()
        after = len(process.events())
        diagnostic_after = len(process.raw(1))
        source.write_bytes(valid + b'\nfn deliberately_broken( {\n')
        failed = process.until(lambda event: event.get('event') == 'edit-failed'
            and event.get('code') == 'guest-build-failed-last-deployment-retained', 330, after=after)
        require(failed['phase'] == 'build' and failed['currentDeployment'] == selected
            and failed['uncertain'] is False and failed['rollbackPerformed'] is False
            and any(row['path'] == 'app/src/lib.rs' and row['severity'] == 'error'
                and row['hostPath'] == str(source) for row in failed['diagnostics']),
            'newcomer-compiler-failure-not-mapped-to-retained-source')
        report['compilerFailure'] = failed
        raw, failed_encoding = diagnostics_finished(process, after=diagnostic_after)
        require('LSF ' + str(source) + ':' in raw and ': error ' in raw,
                'newcomer-live-compiler-diagnostic-missing')
        report['failedBuildStillCallable'] = greeting(api, item, 'Welcome, Ada!', selected)
        after = len(process.events())
        diagnostic_after = len(process.raw(1))
        source.write_bytes(valid)
        restored = completed(process, after=after)
        selected = restored['currentDeployment']
        require(selected['componentDigest'] == report['welcomeDeployment']['componentDigest'],
                'newcomer-restored-component-changed')
        report['restoredFocusedTest'] = restored
        raw, restored_encoding = diagnostics_finished(process, after=diagnostic_after)
        require(': error ' not in raw.rsplit('LSF build-start', 1)[-1], 'newcomer-old-diagnostic-not-cleared')
        report['diagnostics'] = {'failedBuildVisibleWhileWatchRunning': True, 'restoredBatchHasNoErrors': True,
                                 'failedBatchEncoding': failed_encoding, 'restoredBatchEncoding': restored_encoding,
                                 'bytes': len(process.raw(1)), 'editorUiObserved': False}
        report['statusBeforeRecovery'] = api.call('status', '--workspace', name)
        report['recover'] = api.call('recover', '--workspace', name)
        require(report['recover']['state'] == 'no-pending-operation', 'newcomer-unexpected-pending-operation')
        report['downAfterWatch'] = api.down(name)
        report['retainedRestart'] = api.start(name)
        require(report['retainedRestart']['node'] == report['startup']['node'], 'newcomer-retained-node-changed')
        report['retainedGreeting'] = greeting(api, item, 'Welcome, Ada!', selected)
        report['finalDown'] = api.down(name)
        report['stopped'] = api.call('status', '--workspace', name)
        require(report['stopped']['state'] == 'stopped', 'newcomer-final-shutdown-not-confirmed')
        item['guest'] = observe(api, item, 'audit')
        item['authoredSource'] = {relative: digest(root / relative) for relative in item['authoredSource']}
        item['authoredSource']['.vscode/tasks.json'] = digest(root / '.vscode/tasks.json')
        item['purge'] = api.call('purge', '--workspace', name, '--confirm-workspace', name, timeout=120)
        item['preservedAuthorSource'] = preserved_source(item)
        report['passed'] = True
    finally:
        if process is not None:
            report['events'] = process.events()
        # The surrounding Windows schedule owns down/reconciliation on failure.
        api.report['newcomerApplication'] = item
    return item
