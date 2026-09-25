"""Drive packaged watch using authored edits and the public frontend commands."""
import base64
from pathlib import Path

if __package__:
    from .dev_packaged_guest import export
    from .dev_packaged_process import digest, read_json, require
else:
    from dev_packaged_guest import export
    from dev_packaged_process import digest, read_json, require


def run(api, item):
    root = Path(item['project'])
    descriptor = read_json(root / 'latent.project.json')
    cases = [case for name in descriptor['scenarios'] for case in read_json(root / name)['scenarios']]
    case = next(case for case in cases if case['expect']['category'] == 'success')
    source = root / 'app/src/lib.rs'
    original = source.read_bytes()
    require(b'Hello, ' in original, 'maintained-rust-watch-source-changed')
    name = item['workspace']
    require(name == 'test-packaged-rust-watch' and item['profile']['admission'] == 'trusted-local',
            'watch-requires-its-explicit-provider-free-trusted-local-workspace')
    observation = item['packagedWatch'] = {'passed': False, 'events': [], 'initialTests': item['tests']}
    observation['downBeforeWatch'] = api.down(name)
    observation['watchReady'] = api.start(name, project=root, selection=case['id'])
    process = api.running[name]
    try:
        initial = process.until(lambda event: event.get('event') == 'post-deploy-tests' and event.get('passed') is True, 330)
        selected_a = initial['currentDeployment']
        after = len(process.events())
        # Write the finite edit burst without changing its trusted recipe. Watch
        # still owns coalescing, compilation, deployment and focused test dispatch.
        for entry in cases:
            if 'payload' in entry['expect']:
                expected = root / entry['expect']['payload']
                raw = expected.read_bytes()
                if b'Hello, ' in raw:
                    expected.write_bytes(raw.replace(b'Hello, ', b'Howdy, '))
        changed = original.replace(b'Hello, ', b'Howdy, ')
        source.write_bytes(changed)
        deployed = process.until(lambda event: event.get('event') == 'deployed'
            and event['deployment']['publication'] != selected_a['publication'], 330, after=after)
        selected_b = deployed['deployment']
        observation['revisionB'] = selected_b
        completed = process.until(lambda event: event.get('event') == 'post-deploy-tests'
            and event.get('passed') is True and event['currentDeployment'] == selected_b, 330, after=after)
        observation['focusedRevisionB'] = completed['report']
        after = len(process.events())
        source.write_bytes(changed + b'\nthis is deliberately invalid Rust;\n')
        failure = process.until(lambda event: event.get('event') == 'edit-failed'
            and event.get('code') == 'guest-build-failed-last-deployment-retained', 330, after=after)
        require(failure['currentDeployment'] == selected_b and failure['uncertain'] is False
                and failure['rollbackPerformed'] is False, 'compiler-failure-changed-selected-deployment')
        observed = api.call('invoke', '--workspace', name, '--service', case['service'], '--contract', case['contract'],
            '--function', case['function'], '--input', root / case['input'], '--media-type', case['mediaType'])
        require(observed['category'] == 'success' and observed['outcomeKnown'] is True
                and observed['data']['resolvedRevision']['publicationId'] == selected_b['publication']
                and base64.b64decode(observed['data']['payload']['data'], validate=True)
                    == (root / case['expect']['payload']).read_bytes(), 'last-good-watch-revision-not-callable')
        observation['invokeDuringCompilerFailure'] = observed
        observation['downAfterFailure'] = api.down(name)
        # A deliberate author action restores valid B. It does not restore A or
        # replay a publication. The accepted B cache must still validate exactly.
        source.write_bytes(changed)
        item['build'] = api.call('build', '--workspace', name, '--project', root, timeout=1200)
        require(item['build']['artifacts']['component'] == deployed['build']['artifacts']['component'], 'restored-b-build-identity')
        observation['explicitAuthorRestore'] = True
        observation['retainedBRestart'] = api.start(name)
        item['tests'] = api.call('test', '--workspace', name, '--environment', 'node', timeout=330)
        require(item['tests']['passed'] and item['tests']['identity']['deployment'] == selected_b, 'retained-b-republished-or-failed')
        item['authoredSource'] = {name: digest(root / name) for name in item['authoredSource']}
        item['publicArtifacts'] = export(api, item, suffix='-revision-b')
        observation['passed'] = True
    finally:
        observation['events'] = process.events()


def campaign(api, config, helper_sha, *, backend_config=None, project_parent=None):
    # The maintained short-lived signing fixture binds exactly one accepted
    # build. Watch has a distinct provider-free Rust workspace, configured with
    # its documented trusted-local mode before the first deployment. No signed
    # workspace changes admission or credentials to accommodate an edit.
    if __package__:
        from .dev_packaged_windows import prepare, verify_language, retained_invocation, preserved_source
    else:
        from dev_packaged_windows import prepare, verify_language, retained_invocation, preserved_source
    item = prepare(api, config, 'rust', 10, helper_sha, backend_config=backend_config,
                   project_parent=project_parent, watch_project=True)
    verify_language(api, item)
    run(api, item)
    name = item['workspace']
    item['down'] = api.down(name)
    item['retainedRestart'] = api.start(name)
    item['afterRestart'] = retained_invocation(api, item)
    item['finalDown'] = api.down(name)
    item['purge'] = api.call('purge', '--workspace', name, '--confirm-workspace', name, timeout=120)
    item['preservedAuthorSource'] = preserved_source(item)
    return item
