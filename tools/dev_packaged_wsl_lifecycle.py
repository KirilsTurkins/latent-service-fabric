"""Interrupt only the recorded owned distro and observe actual namespace replacement."""
import os
from pathlib import Path
import re

if __package__:
    from .dev_packaged_process import MAX_COMMANDS, Command, read_json, require
else:
    from dev_packaged_process import MAX_COMMANDS, Command, read_json, require


def registration(api):
    import winreg
    owned = read_json(api.state / 'wsl.json')
    require(re.fullmatch(r'LSF-Dev-[a-f0-9]{16}', owned['distribution'])
            and re.fullmatch(r'\{[a-fA-F0-9-]{36}\}', owned['registration'])
            and Path(owned['directory']) == api.state / owned['distribution'], 'exact-owned-wsl-lifecycle-target')
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Lxss' + '\\' + owned['registration']) as key:
        name = winreg.QueryValueEx(key, 'DistributionName')[0]
        directory = winreg.QueryValueEx(key, 'BasePath')[0]
        version = winreg.QueryValueEx(key, 'Version')[0]
    require(name == owned['distribution'] and version == 2
            and Path(directory.removeprefix('\\\\?\\')) == Path(owned['directory']), 'wsl-registration-replaced-before-lifecycle-test')
    return {'distribution': name, 'registration': owned['registration'], 'directory': owned['directory'], 'version': version}


def restart_owned_distribution(api, item):
    name = item['workspace']
    require(name in api.running and len(api.running) == 1, 'one-explicit-retained-workspace-required-for-distro-loss')
    require(len(api.report['commands']) < MAX_COMMANDS - 24, 'qualification-command-count-limit')
    before = api.call('status', '--workspace', name)
    require(before['state'] == 'ready' and isinstance(before.get('guestInstance'), dict), 'actual-ready-guest-identity-required')
    owner = registration(api)
    require(owner['distribution'] == api.report['provision']['distribution'], 'original-qualified-distro-required')
    command = Command([Path(os.environ['SystemRoot']) / 'System32/wsl.exe', '--terminate', owner['distribution']],
                      api.root, api.env)
    result = {'injection': 'terminate-and-resume-exact-owned-wsl-distribution', 'owner': owner,
              'before': before, 'globalWslShutdown': False, 'passed': False}
    item['actualWslLifecycle'] = result
    try:
        require(command.finish(60) == 0, 'owned-distro-termination-failed')
    finally:
        try:
            command.abort_controller()
        finally:
            api.report['commands'].append({**command.receipt(), 'purpose': 'explicit-owned-distro-lifecycle-interruption'})
    foreground = api.running.pop(name)
    try:
        code = foreground.finish(90)
        events = foreground.events()
        require(events and code in {0, 2, 5} and events[-1].get('code') in {
            'success', 'workspace-session-lost-inspect-status', 'backend-transport-lost-status-required',
            'workspace-session-cleanup-unconfirmed'}, 'unexpected-foreground-loss-outcome')
        result['foregroundAfterLoss'] = {'exitCode': code, 'events': events}
    finally:
        try:
            foreground.abort_controller()
        finally:
            api.report['commands'].append({**foreground.receipt(), 'purpose': 'original-foreground-after-distro-loss'})
    require(registration(api) == owner, 'distro-identity-changed-during-restart')
    observed = api.call('status', '--workspace', name)
    require(observed['state'] == 'stopped' and observed.get('reaped') is True
            and observed.get('cleanShutdown') is False
            and observed.get('failure') == 'guest-restarted-inspect-operation-receipts', 'new-namespace-reaping-not-confirmed')
    result['observedAfterResume'] = observed
    restarted = api.start(name)
    require(restarted['guestInstance'] != before['guestInstance'], 'actual-guest-namespace-did-not-change')
    result.update(restarted=restarted, passed=True)
    return result
