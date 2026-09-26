"""Run reviewed watch probes against an authenticated installed helper only."""
from pathlib import Path
import json
import re

if __package__:
    from .dev_packaged_guest import guest_argv
    from .dev_packaged_process import MAX_COMMANDS, Command, digest, read_json, require
else:
    from dev_packaged_guest import guest_argv
    from dev_packaged_process import MAX_COMMANDS, Command, digest, read_json, require

SOURCES = ('dev_packaged_watch_guest.py', 'dev_watch_inflight.py', 'dev_watch_revocation.py')


class Observer:
    def __init__(self, api, config, item):
        self.api, self.item, self.active = api, item, {}
        self.backend = read_json(api.state / item['workspace'] / 'backend.json')
        require(item['workspace'] == 'test-packaged-rust-watch'
                and item['profile']['admission'] == 'trusted-local'
                and self.backend['helperSha256'] == item['helperSha256'], 'exact-owned-watch-helper-required')
        if self.backend['kind'] == 'wsl2':
            require(self.backend['distribution'] == api.report['provision']['distribution'], 'owned-wsl-watch-target')
        self.sources = {}
        require(set(config['watchProbeSha256']) == set(SOURCES), 'closed-reviewed-watch-probe-set')
        for name in SOURCES:
            path = Path(config['faultProbe']).parent / name
            expected = config['watchProbeSha256'][name]
            require(re.fullmatch(r'sha256:[a-f0-9]{64}', expected)
                and path.is_file() and not path.is_symlink() and path.stat().st_size <= 16384
                and digest(path) == expected, 'separate-reviewed-watch-conductor-required')
            self.sources[name] = {'source': path.read_bytes().decode('utf-8'), 'sha256': expected}

    def start(self, mode, request=None):
        require(mode in {'inflight', 'switch', 'revoke', 'build', 'superseded', 'retention'}
            and mode not in self.active, 'closed-single-watch-observer-mode')
        require(len(self.api.report['commands']) < MAX_COMMANDS - 24, 'qualification-command-count-limit')
        packet = dict(request or {})
        if mode == 'inflight':
            packet['inflight'] = self.sources['dev_watch_inflight.py']
        if mode == 'revoke':
            packet['revocation'] = self.sources['dev_watch_revocation.py']
        raw = json.dumps(packet).encode()
        require(len(raw) <= 65536, 'watch-conductor-input-limit')
        helper = self.backend['helper'] if self.backend['kind'] == 'linux' else '/opt/latent-dev/helper.pyz'
        argv = guest_argv(self.api, self.item, ['/usr/local/bin/python3.13', '-I', '-B', '-c',
            self.sources['dev_packaged_watch_guest.py']['source'], '--helper', helper,
            '--helper-sha256', self.item['helperSha256'], '--workspace', self.item['workspace'], '--mode', mode])
        child = Command(argv, self.api.root, self.api.env, input_bytes=raw)
        self.active[mode] = child
        return child

    def finish(self, mode, seconds=120):
        child = self.active.pop(mode)
        try:
            require(child.finish(seconds) == 0, 'packaged-watch-' + mode + '-failed-inspect-original-intent')
            events = child.events()
            require(events and len(events) <= 2, 'bounded-watch-observation-required')
            return events[-1]['result']
        finally:
            try:
                child.abort_controller()
            finally:
                self.api.report['commands'].append({**child.receipt(), 'purpose': 'installed-watch-' + mode,
                                                    'events': child.events()})

    def call(self, mode, request=None):
        self.start(mode, request)
        return self.finish(mode, 120 if mode == 'revoke' else 30)

    def close(self):
        # Give the bounded guest its opportunity to cancel and reap its original
        # Invoke. A failed observer is never restarted or relabeled successful.
        for mode in list(self.active):
            self.finish(mode, 165)
