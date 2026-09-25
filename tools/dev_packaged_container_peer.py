"""Provision one explicit SSH peer and fresh private client volume for the devcontainer lane."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import shutil
import signal
import socket
import subprocess
import time


def main():
    assert os.getuid() == 0
    remote = pwd.getpwnam('lsfremote')
    assert remote.pw_uid == 23002
    home = Path('/qualification-client-home')
    assert home.is_dir() and not list(home.iterdir()), 'new empty client volume required'
    home.chmod(0o700)
    os.chown(home, 10001, 10001)
    inputs = home / 'inputs'
    shutil.copytree('/qualification-inputs', inputs, symlinks=False)
    selected = json.loads((inputs / 'inputs.json').read_bytes())
    with Path('/opt/latent-dev/helper.pyz').open('rb') as stream:
        assert 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest() == selected['linuxHelperSha256']
    for path in [inputs, *inputs.rglob('*')]:
        assert not path.is_symlink()
        os.chown(path, 10001, 10001)
        path.chmod(0o700 if path.is_dir() or path.name == 'gh-linux' else 0o600)
    # The host chose this new project bind explicitly. Only its empty root is
    # assigned to the declared UID; generated configuration files are untouched.
    project = Path('/qualification-project')
    assert project.is_dir() and {p.name for p in project.iterdir()} == {'.devcontainer'}
    os.chown(project, 10001, 10001)
    project.chmod(0o755)
    runtime = Path('/run/lsf-devcontainer-peer')
    runtime.mkdir(mode=0o700)
    Path('/run/sshd').mkdir(mode=0o755, exist_ok=True)
    ssh = home / '.ssh'
    ssh.mkdir(mode=0o700)
    key, host = ssh / 'identity', runtime / 'host'
    for destination in (key, host):
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(destination)],
                       check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=15)
    authorized = Path(remote.pw_dir) / '.ssh'
    authorized.mkdir(mode=0o700)
    public = authorized / 'authorized_keys'
    public.write_bytes(key.with_suffix('.pub').read_bytes())
    for path in (authorized, public):
        path.chmod(0o700 if path.is_dir() else 0o600)
        os.chown(path, remote.pw_uid, remote.pw_gid)
    known = ssh / 'known_hosts'
    known.write_text('[127.0.0.1]:2222 ' + host.with_suffix('.pub').read_text(), encoding='utf-8')
    for path in (ssh, key, key.with_suffix('.pub'), known):
        path.chmod(0o700 if path.is_dir() else 0o600)
        os.chown(path, 10001, 10001)
    client_home = Path('/home/latent-dev')
    client_inputs = client_home / 'inputs'
    support = client_inputs / 'support'
    selected['artifacts'] = {name: str(client_inputs / 'artifacts' / name) for name in ('linux', 'rust', 'native')}
    selected['faultProbe'] = str(support / 'dev_node_fault_probe.py')
    selected['trust'].update(hostVerifier=str(support / 'gh-linux'), guestVerifier=str(support / 'gh-linux'),
        trustedRoot=str(support / 'trusted_root.jsonl'), developerPolicy=str(support / 'developer-policy.json'),
        runtimePolicy=str(support / 'runtime-policy.json'))
    backend = {'kind': 'ssh', 'host': '127.0.0.1', 'port': 2222, 'user': 'lsfremote', 'ssh': '/usr/bin/ssh',
        'helperSha256': selected['linuxHelperSha256'], 'identityFile': str(client_home / '.ssh/identity'),
        'knownHosts': str(client_home / '.ssh/known_hosts')}
    for name, value in (('ssh-backend.json', backend), ('selected-inputs.json', selected)):
        path = home / name
        path.write_text(json.dumps(value), encoding='utf-8')
        path.chmod(0o600)
        os.chown(path, 10001, 10001)
    settings = runtime / 'sshd_config'
    settings.write_text('Port 2222\nListenAddress 127.0.0.1\nHostKey ' + str(host) + '\n'
        'PidFile /run/lsf-devcontainer-peer/sshd.pid\nAllowUsers lsfremote\nPermitRootLogin no\n'
        'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitEmptyPasswords no\nUsePAM no\n'
        'PubkeyAuthentication yes\nStrictModes yes\nAuthorizedKeysFile .ssh/authorized_keys\n'
        'DisableForwarding yes\nPermitTTY no\nLogLevel ERROR\n', encoding='utf-8')
    server = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', str(settings)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    try:
        deadline = time.monotonic() + 10
        while True:
            assert server.poll() is None and time.monotonic() < deadline
            try:
                with socket.create_connection(('127.0.0.1', 2222), timeout=1) as connection:
                    assert connection.recv(256).startswith(b'SSH-2.0-')
                break
            except ConnectionRefusedError:
                time.sleep(0.05)
        ready = home / 'peer-ready.json'
        ready.write_text(json.dumps({'ready': True, 'clientUid': 10001, 'serverUid': remote.pw_uid,
            'listener': '127.0.0.1:2222', 'hostKeySha256': hashlib.sha256(host.with_suffix('.pub').read_bytes()).hexdigest()}))
        ready.chmod(0o600)
        os.chown(ready, 10001, 10001)
        until = time.monotonic() + 3600
        while not stopping and time.monotonic() < until:
            assert server.poll() is None
            time.sleep(0.2)
        return 0 if stopping else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
