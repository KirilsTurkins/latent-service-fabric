"""Bounded watch observations using only the exact authenticated installed helper."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time


def main(args):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise ValueError('unprivileged-installed-watch-owner-required')
    helper_path = args.helper.absolute()
    if helper_path.resolve() != helper_path or not re.fullmatch(r'sha256:[a-f0-9]{64}', args.helper_sha256):
        raise ValueError('exact-installed-helper-required')
    for path in (helper_path, *helper_path.parents):
        info = path.lstat()
        sticky = info.st_uid == 0 and stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_ISVTX
        if info.st_uid not in {0, os.geteuid()} or info.st_mode & 0o022 and not sticky or stat.S_ISLNK(info.st_mode):
            raise ValueError('protected-installed-helper-required')
    with helper_path.open('rb') as stream:
        raw = stream.read(2097153)
    if len(raw) > 2097152 or 'sha256:' + hashlib.sha256(raw).hexdigest() != args.helper_sha256:
        raise ValueError('installed-helper-digest-mismatch')
    if args.workspace != 'test-packaged-rust-watch':
        raise ValueError('explicit-watch-qualification-workspace-required')
    packet = sys.stdin.buffer.read(65537)
    if len(packet) > 65536:
        raise ValueError('watch-conductor-input-limit')
    request = json.loads(packet)
    sys.path.insert(0, str(helper_path))
    from tools.dev_workflow import build_cache, build_control, helper, paths, state
    from tools.dev_workflow.common import decode, require
    root = state.workspace(helper.root_directory(), args.workspace)
    layout, _ = helper.installation(root)
    require(decode(layout.node.read_bytes())['securityProfile'] == 'local-experimental-v1',
            'explicit-local-watch-profile-required')
    marker = root / 'qualification-watch-switch.json'

    def output(event, value):
        print(json.dumps({'event': event, 'result': value}), flush=True)

    def reviewed(name):
        require(name in {'inflight', 'revocation'}, 'closed-watch-observer-module')
        selected = request[name]
        source = selected['source'].encode('utf-8')
        require(len(source) <= 16384 and 'sha256:' + hashlib.sha256(source).hexdigest() == selected['sha256'],
                'reviewed-watch-source-digest-mismatch')
        # Import only these two named, hash-checked modules from a new private
        # directory. No expression, arbitrary module name or project path is run.
        with tempfile.TemporaryDirectory(prefix='qualification-observer-', dir=root) as directory:
            filename = 'qualification_watch_' + name + '.py'
            paths.write_new(Path(directory) / filename, source)
            sys.path.insert(0, directory)
            try:
                if name == 'inflight':
                    from qualification_watch_inflight import Inflight
                    return Inflight
                from qualification_watch_revocation import run
                return run
            finally:
                sys.path.remove(directory)

    if args.mode == 'inflight':
        require(not marker.exists() and not (root / 'qualification-spin-intent.json').exists(),
                'inspect-original-watch-invocation-before-new-attempt')
        descriptor = state.load(root, 'project.json')['descriptor']
        # These two reviewed source strings are separately hashed by the host
        # conductor. Their application imports resolve to the verified zip above.
        inflight = reviewed('inflight')(root, descriptor, time.monotonic() + 150)
        try:
            inflight.start()
            output('inflight-ready', inflight.report)
            until = time.monotonic() + 120
            while not marker.exists():
                require(time.monotonic() < until, 'watch-switch-observation-deadline')
                time.sleep(0.05)
            selected = state.load(root, marker.name)
            result = inflight.switched(selected['before'], selected['after'])
            output('inflight-finished', result)
        finally:
            inflight.stop()
    elif args.mode == 'switch':
        before, after = request['before'], request['after']
        intent = state.load(root, 'qualification-spin-intent.json')
        require(intent['deployment'] == before and state.load(root, 'last-deployment.json') == after
                and before['publication'] != after['publication'], 'observed-original-watch-switch-required')
        paths.write_new(marker, json.dumps({'before': before, 'after': after}).encode())
        output('switch-recorded', {'originalActivation': intent['id'], 'effectReplay': False})
    elif args.mode == 'revoke':
        previous = request['previous']
        require(state.load(root, 'qualification-spin-intent.json')['deployment'] == previous,
                'original-watch-publication-required')
        require(not (root / 'qualification-revoke-intent.json').exists()
                and not (root / 'qualification-restore-intent.json').exists(),
                'inspect-original-revocation-before-any-new-mutation')
        output('revoked-restore', reviewed('revocation')(root, previous, time.monotonic() + 90))
    elif args.mode == 'build':
        active = build_control.status(root)
        result = {'build': active, 'child': None, 'source': None}
        if active.get('state') == 'running' and active.get('attempt'):
            ready = root / 'builds' / active['attempt'] / 'source/build-cache/qualification-ready.txt'
            if ready.exists():
                pid = int(paths.read(ready.parent, ready.name, 20))
                require(pid > 1, 'owned-slow-recipe-child-required')
                status = Path('/proc') / str(pid) / 'stat'
                try:
                    fields = status.read_text().rsplit(')', 1)[1].split()
                except FileNotFoundError:
                    fields = None
                if fields is not None:
                    result['source'] = build_cache.owner(root / 'builds' / active['attempt'])['source']
                    result['child'] = {'pid': pid, 'startTicks': fields[19],
                        'bootId': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        output('build-observation', result)
    elif args.mode == 'superseded':
        child = request['child']
        require(type(child['pid']) is int and child['pid'] > 1, 'owned-child-id-required')
        require(Path('/proc/sys/kernel/random/boot_id').read_text().strip() == child['bootId'],
                'watch-guest-restarted-during-cancellation')
        path = Path('/proc') / str(child['pid']) / 'stat'
        until = time.monotonic() + 5
        while True:
            try:
                fields = path.read_text().rsplit(')', 1)[1].split()
            except FileNotFoundError:
                break
            if fields[19] != child['startTicks']:
                break
            require(time.monotonic() < until, 'original-slow-recipe-child-not-reaped')
            time.sleep(0.05)
        output('superseded-child-reaped', {'child': child, 'originalChildReaped': True})
    elif args.mode == 'retention':
        attempts = list((root / 'builds').iterdir())
        require(len(attempts) <= build_cache.MAX_ATTEMPTS, 'watch-build-retention-exceeded')
        for attempt in attempts:
            build_cache.owner(attempt)
        output('retention', {'attempts': len(attempts), 'maximumAttempts': build_cache.MAX_ATTEMPTS,
            'ownedBytes': sum(build_cache.usage(path)[1] for path in attempts)})
    else:
        raise ValueError('closed-watch-observation-mode-required')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--helper-sha256', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--mode', choices=('inflight', 'switch', 'revoke', 'build', 'superseded', 'retention'), required=True)
    main(parser.parse_args())
