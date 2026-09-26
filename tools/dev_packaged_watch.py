"""Drive installed watch through real edits, failures and revision-pinned work."""
import base64
import json
from pathlib import Path
import time

if __package__:
    from .dev_packaged_guest import observe
    from .dev_packaged_process import digest, read_json, require
    from .dev_packaged_watch_observer import Observer
    from .dev_watch_case_inputs import edit
else:
    from dev_packaged_guest import observe
    from dev_packaged_process import digest, read_json, require
    from dev_packaged_watch_observer import Observer
    from dev_watch_case_inputs import edit


def current_value(api, item, marker, selected):
    root = Path(item['project'])
    descriptor = read_json(root / 'latent.project.json')
    result = api.call('invoke', '--workspace', item['workspace'], '--service', descriptor['service'],
        '--contract', 'examples:greeting/api@1.0.0', '--function', 'value',
        '--input', root / 'tests/value-input.json', '--media-type', 'application/vnd.latent.wit-values.v1+json')
    require(result['category'] == 'success' and result['outcomeKnown'] is True
        and result['data']['resolvedRevision']['publicationId'] == selected['publication']
        and result['data']['resolvedRevision']['releaseDigest'] == selected['componentDigest']
        and json.loads(base64.b64decode(result['data']['payload']['data'], validate=True)) == [marker],
        'last-working-watch-revision-not-callable')
    return result


def run(api, config, item):
    root, name = Path(item['project']), item['workspace']
    require(name == 'test-packaged-rust-watch' and item['profile']['admission'] == 'trusted-local',
            'watch-requires-its-explicit-provider-free-trusted-local-workspace')
    observation = item['packagedWatch'] = {'passed': False, 'events': []}
    observer = Observer(api, config, item)
    process = None
    try:
        observation['watchReady'] = api.start(name, project=root, selection='value')
        process = api.running[name]
        initial = process.until(lambda event: event.get('event') == 'post-deploy-tests'
            and event.get('passed') is True, 330)
        selected_a = initial['currentDeployment']
        require(initial['report']['selection'] == ['value'] and initial['rollbackPerformed'] is False,
                'explicit-focused-watch-selection-required')
        item['tests'] = initial['report']
        observation['revisionA'] = selected_a
        inflight = observer.start('inflight')
        observation['inflightReady'] = inflight.until(lambda event: event.get('event') == 'inflight-ready', 20)['result']
        after = len(process.events())
        edit(root, 201)
        deployed = process.until(lambda event: event.get('event') == 'deployed'
            and event['deployment']['publication'] != selected_a['publication'], 110, after=after)
        selected_b = observation['revisionB'] = deployed['deployment']
        require(deployed['build']['attempt'] == item['watchWarmB']['attempt'], 'exact-warm-b-cache-not-reused')
        observation['switch'] = observer.call('switch', {'before': selected_a, 'after': selected_b})
        observation['inflight'] = observer.finish('inflight', 20)
        require(observation['inflight']['oldRevisionRetained'] is True
            and observation['inflight']['invokeCalls'] == 1 and observation['inflight']['cancelCalls'] == 1,
            'one-original-revision-pinned-invocation-required')
        completed = process.until(lambda event: event.get('event') == 'post-deploy-tests'
            and event.get('passed') is True and event['currentDeployment'] == selected_b, 330, after=after)
        observation['focusedRevisionB'] = completed['report']
        observation['revisionBValue'] = current_value(api, item, 201, selected_b)

        for mode, code in (('compiler-error', 'guest-build-failed-last-deployment-retained'),
                           ('malformed', 'build-output-is-not-component-model')):
            after = len(process.events())
            edit(root, 301, mode='normal' if mode == 'compiler-error' else mode, compiler_error=mode == 'compiler-error')
            failure = process.until(lambda event: event.get('event') == 'edit-failed'
                and event.get('code') == code, 330, after=after)
            require(failure['currentDeployment'] == selected_b and failure['phase'] == 'build'
                and failure['uncertain'] is False and failure['rollbackPerformed'] is False,
                'failed-edit-changed-selected-deployment')
            observation[mode] = {'event': failure, 'callableB': current_value(api, item, 201, selected_b)}

        after = len(process.events())
        edit(root, 301, mode='slow')
        until = time.monotonic() + 90
        for _ in range(40):
            slow = observer.call('build')
            if slow['child'] is not None:
                break
            require(time.monotonic() < until, 'slow-watch-build-observation-deadline')
            time.sleep(0.25)
        require(slow['child'] is not None and slow['build']['state'] == 'running', 'actual-owned-slow-recipe-child-required')
        observation['rapidEdits'] = {'original': slow, 'intermediateValue': 401, 'latestValue': 501}
        edit(root, 401)
        edit(root, 501, expected=999)
        superseded = process.until(lambda event: event.get('event') == 'build-superseded'
            and event.get('source') == slow['source'], 330, after=after)
        require(superseded['phase'] == 'build' and superseded['uncertain'] is False
            and superseded['currentDeployment'] == selected_b, 'slow-build-cancellation-changed-deployment')
        observation['rapidEdits']['superseded'] = superseded
        observation['rapidEdits']['cleanup'] = observer.call('superseded', {'child': slow['child']})
        latest = process.until(lambda event: event.get('event') == 'deployed'
            and event['deployment']['publication'] != selected_b['publication'], 330, after=after)
        selected = observation['latestDeployment'] = latest['deployment']
        require(selected['source'] == latest['build']['source'], 'latest-watch-build-deployment-mismatch')
        failed_test = process.until(lambda event: event.get('event') == 'post-deploy-tests'
            and event['currentDeployment'] == selected, 330, after=after)
        require(failed_test['passed'] is False and failed_test['report']['selection'] == ['value']
            and failed_test['rollbackPerformed'] is False, 'focused-post-deploy-failure-was-hidden')
        observation['postDeployFailure'] = failed_test
        observation['postDeployFailureStillLive'] = current_value(api, item, 501, selected)
        observation['revokedRestore'] = observer.call('revoke', {'previous': selected_a})
        observation['afterRevokedRestore'] = current_value(api, item, 501, selected)
        observation['retention'] = observer.call('retention')
        observation['downAfterWatch'] = api.down(name)
        deployed_events = [row['deployment'] for row in process.events() if row.get('event') == 'deployed']
        require(deployed_events == [selected_a, selected_b, selected], 'unexpected-or-out-of-order-watch-deployment')
        observation['retainedRestart'] = api.start(name)
        observation['afterRestart'] = current_value(api, item, 501, selected)
        observation['finalDown'] = api.down(name)
        item['authoredSource'] = {name: digest(root / name) for name in item['authoredSource']}
    finally:
        if process is not None:
            observation['events'] = process.events()
        observer.close()
    observation['passed'] = True


def campaign(api, config, helper_sha, *, backend_config=None, project_parent=None):
    # The signed fixtures bind one accepted build. This separately declared
    # provider-free trusted-local project preserves that boundary through edits.
    if __package__:
        from .dev_packaged_windows import prepare, preserved_source
    else:
        from dev_packaged_windows import prepare, preserved_source
    item = prepare(api, config, 'rust', 10, helper_sha, backend_config=backend_config,
                   project_parent=project_parent, watch_project=True)
    run(api, config, item)
    item['guest'] = observe(api, item, 'audit')
    name = item['workspace']
    item['purge'] = api.call('purge', '--workspace', name, '--confirm-workspace', name, timeout=120)
    item['preservedAuthorSource'] = preserved_source(item)
    return item
