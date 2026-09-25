"""Run the maintained closed-profile cases through installed public commands."""
from pathlib import Path

if __package__:
    from .dev_failure_case_inputs import populate as failure_inputs
    from .dev_clock_case_inputs import populate as clock_inputs
    from .dev_packaged_guest import export, observe
    from .dev_packaged_process import digest, read_json, require, write_json
else:
    from dev_failure_case_inputs import populate as failure_inputs
    from dev_clock_case_inputs import populate as clock_inputs
    from dev_packaged_guest import export, observe
    from dev_packaged_process import digest, read_json, require, write_json


def author(project, kind):
    descriptor = read_json(project / 'latent.project.json')
    require(descriptor['language'] == 'rust' and kind in {'failure', 'clock'}, 'rust-authored-failure-cases-required')
    (failure_inputs if kind == 'failure' else clock_inputs)(project, descriptor)


def node_campaign(api, config, helper_sha, *, backend_config=None, project_parent=None):
    if __package__:
        from .dev_packaged_windows import prepare, preserved_source, retained_invocation
    else:
        from dev_packaged_windows import prepare, preserved_source, retained_invocation
    observations = {}
    # Separate nodes and signing fixtures keep each exact authored input
    # independent. WSL additionally gives each workspace its own Linux user.
    # Neither test changes a retained application's node profile.
    api.report['closedProfile'] = observations
    for index, kind in enumerate(('failure', 'clock'), start=6):
        item = observations[kind] = prepare(api, config, 'rust', index, helper_sha,
            case_set=kind, backend_config=backend_config, project_parent=project_parent)
        name = item['workspace']
        item['startup'] = api.start(name)
        item['doctor'] = api.call('doctor', '--workspace', name)
        item['deployment'] = api.call('deploy', '--workspace', name, timeout=180)
        project = Path(item['project'])
        cases = read_json(project / 'tests/scenarios.json')['scenarios']
        selection = [case['id'] for case in cases if kind == 'failure' or case['id'].startswith('clock-zero-')]
        selected = [part for name in selection for part in ('--select', name)]
        item['tests'] = api.call('test', '--workspace', name, '--environment', 'node', *selected, timeout=330)
        require(item['tests']['passed'] and item['tests']['selection'] == selection
            and all(row['status'] == 'passed' and row['outcomeKnown'] for row in item['tests']['results']),
            'actual-closed-profile-node-case-failed')
        item['guest'] = observe(api, item, 'audit')
        item['publicArtifacts'] = export(api, item)
        item['sharedSelection'] = [name for name in selection if name != 'running-cancel']
        item['down'] = api.down(name)
        item['restart'] = api.start(name)
        item['afterRestart'] = retained_invocation(api, item)
        item['finalDown'] = api.down(name)
        item['purge'] = api.call('purge', '--workspace', name, '--confirm-workspace', name, timeout=120)
        item['sourceAfterPurge'] = preserved_source(item)
    return observations


def portable_campaign(api, observations, bundle):
    for kind, item in observations.items():
        arguments = ['test', '--workspace', 'test-portable-' + kind, '--environment', 'portable',
            '--project', item['project'], '--artifacts', item['publicArtifacts']['directory'],
            '--portable-bundle', bundle, '--controlled-development']
        selected = [part for name in item['sharedSelection'] for part in ('--select', name)]
        actual = item['portable'] = api.call(*arguments, *selected, timeout=330)
        require(actual['passed'] and actual['cleanup'] == 'owned-native-host-reaped'
            and actual['selection'] == item['sharedSelection'], 'packaged-native-closed-profile-failed')
        left, right = item['tests']['identity'], actual['identity']
        require(left['os'] == 'linux' and right['productionNode'] is False
            and left['artifacts'] == right['artifacts'], 'same-byte-real-node-native-comparison-required')
        keys = ('id', 'inputSha256', 'category', 'payloadSha256', 'fixtures', 'execution', 'platformCodes')
        node_rows = [row for row in item['tests']['results'] if row['id'] in item['sharedSelection']]
        require(len(node_rows) == len(actual['results']) and all(
            row['status'] == 'passed' and row['outcomeKnown']
            and all(row.get(key) == native.get(key) for key in keys)
            and native['status'] == 'passed' and native['outcomeKnown']
            for row, native in zip(node_rows, actual['results'])), 'closed-profile-typed-result-comparison')
        if kind == 'failure':
            # Required live node cancellation cannot silently fall back to the
            # portable host's explicitly smaller cancellation-before-start case.
            blocked = item['portableRequiredLiveCancellation'] = api.call(*arguments, timeout=330, expected_test_failure=True)
            require(blocked['passed'] is False and blocked['cleanup'] == 'no-native-host-started'
                and next(row for row in blocked['results'] if row['id'] == 'running-cancel')['status'] == 'unsupported',
                'portable-required-live-cancellation-must-block')
            project = Path(item['project'])
            descriptor = read_json(project / 'latent.project.json')
            document = read_json(project / 'tests/scenarios.json')
            case = {**document['scenarios'][0], 'id': 'native-cancel-before-start',
                'execution': {'grants': [], 'cancelBeforeStart': True},
                'expect': {'category': 'platform-failure', 'platformCode': 'cancelled'}}
            path = project / 'tests/native-cancellation.json'
            write_json(path, {'schemaVersion': 'latent.dev.scenarios.v1', 'scenarios': [case]})
            write_json(project / 'latent.project.json', {**descriptor, 'scenarios': ['tests/native-cancellation.json']})
            item['nativeCancellation'] = api.call(*arguments, '--select', case['id'], timeout=330)
            require(item['nativeCancellation']['passed'] and item['nativeCancellation']['cleanup'] == 'owned-native-host-reaped',
                'actual-native-prestart-cancellation-required')
            item['nativeCancellationSource'] = digest(path)
            # Restore only the author-owned scenario selection; no remote effect
            # is replayed and no selected deployment is changed by portable tests.
            write_json(project / 'latent.project.json', descriptor)
