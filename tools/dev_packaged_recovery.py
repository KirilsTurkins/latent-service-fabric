"""Discard one committed response, then recover its original identity with the packaged frontend."""
import base64
import json
from pathlib import Path
import re

if __package__:
    from .dev_packaged_guest import guest_argv, observe
    from .dev_packaged_process import MAX_COMMANDS, Command, digest, read_json, require
else:
    from dev_packaged_guest import guest_argv, observe
    from dev_packaged_process import MAX_COMMANDS, Command, digest, read_json, require


def inject(api, config, item, kind, arguments=None):
    require(kind in {'release', 'deployment', 'invoke'}, 'closed-packaged-fault-kind')
    require(len(api.report['commands']) < MAX_COMMANDS - 24, 'qualification-command-count-limit')
    backend = read_json(api.state / item['workspace'] / 'backend.json')
    require(backend['kind'] in {'wsl2', 'linux', 'ssh'}
        and backend['helperSha256'] == item['helperSha256'], 'exact-owned-fault-helper-required')
    if backend['kind'] == 'wsl2':
        require(backend['user'] == item['user'] and backend['distribution'] == api.report['provision']['distribution']
            and re.fullmatch(r'LSF-Dev-[a-f0-9]{16}', backend['distribution']), 'owned-wsl-fault-target')
    source = Path(config['faultProbe'])
    require(source.is_file() and not source.is_symlink() and source.stat().st_size <= 16384
            and digest(source) == config['faultProbeSha256'], 'separate-reviewed-fault-conductor-required')
    # This maintained injector verifies and imports the installed helper zip.
    # It never imports an LSF checkout or substitutes a node/operator binary.
    helper = backend['helper'] if backend['kind'] == 'linux' else '/opt/latent-dev/helper.pyz'
    argv = guest_argv(api, item, ['/usr/local/bin/python3.13', '-I', '-B', '-c', source.read_text(encoding='utf-8'),
        '--helper', helper, '--helper-sha256', item['helperSha256'],
        '--workspace', item['workspace'], '--kind', kind])
    command = Command(argv, api.root, api.env,
        input_bytes=None if arguments is None else json.dumps(arguments).encode())
    try:
        require(command.finish(330) == 0, 'packaged-fault-injection-failed-inspect-original-intent')
        result = json.loads(command.raw())
        require(result['injection'] == 'discarded-real-successful-response' and result['selectedMutationCalls'] == 1
                and result['remoteMutationCalls'] == 1 and result['pending']['kind'] == kind
                and result['discarded']['id'] == result['pending']['id'], 'one-original-committed-operation-required')
        return result
    finally:
        try:
            command.abort_controller()
        finally:
            api.report['commands'].append({**command.receipt(), 'purpose': 'discard-one-real-committed-response'})


def recover(api, item, injected):
    pending = observe(api, item, 'journal')
    identity = injected['pending']['id']
    kind = injected['pending']['kind']
    require(pending['pending'] == {'id': identity, 'kind': kind}, 'original-pending-identity-changed')
    result = api.call('recover', '--workspace', item['workspace'], timeout=120)
    require(result['outcomeKnown'] is True and result['category'] == 'success', 'original-recovery-not-confirmed')
    if kind == 'invoke':
        require(result['data']['activationId'] == identity and result['data']['terminalState'] == 'completed'
                and result['data']['terminalOutcome']['kind'] == 'success', 'original-invoke-terminal-receipt')
    else:
        require(result['data']['receipt']['operationId'] == identity, 'original-mutation-receipt')
    journal = observe(api, item, 'journal')
    require(journal['pending'] is None and sum(row == {'id': identity, 'kind': kind} for row in journal['history']) == 1,
            'original-operation-not-settled-exactly-once')
    return {'injection': injected, 'recovery': result, 'journal': journal,
            'lookup': 'public-packaged-recover-original-id', 'effectReplay': False}


def deploy_with_lost_responses(api, config, item):
    item['startup'] = api.start(item['workspace'])
    result = item['packagedResponseRecovery'] = {}
    for kind in ('release', 'deployment'):
        result[kind] = recover(api, item, inject(api, config, item, kind))
    item['deployment'] = {'source': 'original-committed-deployment-recovered-without-replay',
                          'receipt': result['deployment']['recovery']}


def invoke_with_lost_response(api, config, item):
    project = Path(item['project'])
    descriptor = read_json(project / 'latent.project.json')
    cases = [case for name in descriptor['scenarios'] for case in read_json(project / name)['scenarios']]
    case = next(case for case in cases if case['expect']['category'] == 'success')
    raw = (project / case['input']).read_bytes()
    require(len(raw) <= 1048576, 'fault-invoke-input-bound')
    arguments = {key: case[key] for key in ('service', 'contract', 'function', 'mediaType')}
    arguments['input'] = base64.b64encode(raw).decode()
    item['packagedResponseRecovery']['invoke'] = recover(api, item, inject(api, config, item, 'invoke', arguments))
