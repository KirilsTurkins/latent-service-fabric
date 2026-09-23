#!/usr/bin/env python3
"""Exercise real accounts only inside a disposable candidate-image container."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import tempfile


def main() -> int:
    if os.geteuid() != 0 or not Path('/.dockerenv').is_file() or sys.argv[1:] != ['--image-build-test']:
        raise SystemExit('Requires an explicitly selected disposable root container')
    helper = Path('/opt/latent-dev/helper.pyz')
    identity = 'sha256:' + hashlib.sha256(helper.read_bytes()).hexdigest()
    sys.path.insert(0, str(helper))
    from tools.dev_workflow import guest_users, state
    from tools.dev_workflow.common import DevError

    users = []
    with tempfile.TemporaryDirectory(prefix='lsf-accounts-') as temporary:
        registry = Path(temporary)
        for number in range(2):
            owner = {'workspace': 'image-test-' + str(number), 'user': 'lsfd-' + secrets.token_hex(6),
                     'helperSha256': identity, 'nonce': secrets.token_hex(16)}
            result = guest_users.operation('create-user', owner, registry)
            assert result['state'] == 'ready'
            users.append(owner)
        first, second = (pwd.getpwnam(owner['user']) for owner in users)
        assert first.pw_uid != second.pw_uid and first.pw_gid != second.pw_gid
        probe = subprocess.run([sys.executable, '-I', '-c',
            'from pathlib import Path; import sys; Path(sys.argv[1]).iterdir().__next__()', second.pw_dir],
            user=first.pw_uid, group=first.pw_gid, extra_groups=[], capture_output=True, timeout=10,
            env={'PATH': os.defpath, 'LANG': 'C.UTF-8'})
        assert probe.returncode != 0 and b'PermissionError' in probe.stderr
        # Interrupted host acknowledgement: reconcile the same nonce and UID.
        record = state.load(registry, users[0]['user'] + '.json')
        record['state'] = 'creating'
        state.atomic(registry, users[0]['user'] + '.json', record)
        assert guest_users.operation('user-status', users[0], registry)['state'] == 'ready'
        try:
            guest_users.operation('remove-user', {**users[0], 'nonce': '0' * 32}, registry)
        except DevError:
            pass
        else:
            raise AssertionError('A different owner removed an account')
        for owner in users:
            assert guest_users.operation('remove-user', owner, registry)['state'] == 'removed'
            assert guest_users.operation('remove-user', owner, registry)['state'] == 'removed'
            assert not os.path.lexists('/home/' + owner['user'])
        # Interrupted before useradd: explicit removal discards the reservation,
        # without retrying account creation or adopting a home.
        absent = {**users[0], 'user': 'lsfd-' + secrets.token_hex(6)}
        state.atomic(registry, absent['user'] + '.json', {'owner': absent, 'state': 'creating'})
        assert guest_users.operation('remove-user', absent, registry)['accountCreated'] is False
    print(json.dumps({'schemaVersion': 'latent.dev.guest-account-test.v1', 'helperSha256': identity,
        'environment': 'disposable-linux-container', 'accountsCreated': 2, 'privateHomes': True,
        'ownerMismatchDenied': True, 'recoveryFaultInjected': True, 'accountsRemoved': 2,
        'wslQualification': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
