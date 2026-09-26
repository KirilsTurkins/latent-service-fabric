"""Bounded observations of authority and terminal receipt expiry in installed nodes."""
import base64
import json
from pathlib import Path
import re

if __package__:
    from .dev_packaged_guest import guest_argv
    from .dev_packaged_process import MAX_COMMANDS, Command, digest, read_json, require
else:
    from dev_packaged_guest import guest_argv
    from dev_packaged_process import MAX_COMMANDS, Command, digest, read_json, require


def arguments(item):
    project = Path(item['project'])
    descriptor = read_json(project / 'latent.project.json')
    cases = [case for name in descriptor['scenarios'] for case in read_json(project / name)['scenarios']]
    case = next(case for case in cases if case['expect']['category'] == 'success')
    path = project / case['input']
    require(path.stat().st_size <= 1048576, 'recovery-invoke-input-bound')
    return {**{key: case[key] for key in ('service', 'contract', 'function', 'mediaType')},
            'input': base64.b64encode(path.read_bytes()).decode()}


def reviewed(path, expected):
    require(re.fullmatch(r'sha256:[a-f0-9]{64}', expected) and path.is_file()
        and not path.is_symlink() and path.stat().st_size <= 16384 and digest(path) == expected,
        'separate-reviewed-recovery-conductor-required')
    return {'source': path.read_bytes().decode('utf-8'), 'sha256': expected}


def call(api, config, item, mode, request=None):
    require(item['workspace'] in {'test-packaged-rust-expiry', 'test-packaged-rust-unknown'}
        and mode in {'configure-expiry', 'authority', 'expire-original-invoke', 'deployment-state'},
        'closed-installed-recovery-observation')
    require(len(api.report['commands']) < MAX_COMMANDS - 24, 'qualification-command-count-limit')
    backend = read_json(api.state / item['workspace'] / 'backend.json')
    require(backend['kind'] == 'wsl2' and backend['helperSha256'] == item['helperSha256']
        and backend['distribution'] == api.report['provision']['distribution'], 'exact-owned-recovery-helper-required')
    source = reviewed(Path(config['faultProbe']).with_name('dev_packaged_recovery_guest.py'), config['recoveryProbeSha256'])
    packet = dict(request or {})
    if mode == 'expire-original-invoke':
        packet['faultSource'] = reviewed(Path(config['faultProbe']), config['faultProbeSha256'])
    raw = json.dumps(packet).encode()
    require(len(raw) <= 1572864, 'recovery-conductor-input-limit')
    argv = guest_argv(api, item, ['/usr/local/bin/python3.13', '-I', '-B', '-c', source['source'],
        '--helper', '/opt/latent-dev/helper.pyz', '--helper-sha256', item['helperSha256'],
        '--workspace', item['workspace'], '--mode', mode])
    child = Command(argv, api.root, api.env, input_bytes=raw)
    try:
        require(child.finish(120) == 0, 'installed-recovery-observation-failed-inspect-original-intent')
        return json.loads(child.raw())
    finally:
        try:
            child.abort_controller()
        finally:
            api.report['commands'].append({**child.receipt(), 'purpose': 'installed-recovery-' + mode})
