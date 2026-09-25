"""Provision only two owned accounts and loopback SSH inside the disposable OS container."""
from pathlib import Path
import hashlib
import json
import os
import pwd
import shutil
import socket
import subprocess
import sys
import time


def main():
    assert os.getuid() == 0 and len(sys.argv) == 1
    for name in ('gcc', 'g++', 'clang', 'rustc', 'cargo', 'dotnet', 'javac', 'go', 'node'):
        assert shutil.which(name) is None, 'runtime compiler or SDK present in clean OS'
    source = Path('/qualification-inputs')
    home = Path('/home/lsfqa')
    account, remote = pwd.getpwnam('lsfqa'), pwd.getpwnam('lsfremote')
    assert account.pw_uid == 23001 and remote.pw_uid == 23002
    support = home / 'inputs'
    assert not support.exists()
    shutil.copytree(source, support, symlinks=False)
    for path in [support, *support.rglob('*')]:
        assert not path.is_symlink()
        os.chown(path, account.pw_uid, account.pw_gid)
        path.chmod(0o700 if path.is_dir() or path.name == 'gh-linux' else 0o600)
    selected = json.loads((support / 'inputs.json').read_bytes())
    selected['artifacts'] = {name: str(support / 'artifacts' / name) for name in ('linux', 'rust', 'native')}
    selected['faultProbe'] = str(support / 'support/dev_node_fault_probe.py')
    selected['trust'] = {**selected['trust'], 'hostVerifier': str(support / 'support/gh-linux'),
        'guestVerifier': str(support / 'support/gh-linux'), 'trustedRoot': str(support / 'support/trusted_root.jsonl'),
        'developerPolicy': str(support / 'support/developer-policy.json'),
        'runtimePolicy': str(support / 'support/runtime-policy.json')}
    with Path('/opt/latent-dev/helper.pyz').open('rb') as stream:
        assert 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest() == selected['linuxHelperSha256']
    ssh = home / '.ssh'
    ssh.mkdir(mode=0o700)
    os.chown(ssh, account.pw_uid, account.pw_gid)
    runtime = Path('/run/lsf-qualification')
    runtime.mkdir(mode=0o700)
    Path('/run/sshd').mkdir(mode=0o755, exist_ok=True)
    key = ssh / 'identity'
    host = runtime / 'host'
    for destination in (key, host):
        subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(destination)],
                       check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, timeout=15)
    for path in (key, key.with_suffix('.pub')):
        os.chown(path, account.pw_uid, account.pw_gid)
        path.chmod(0o600)
    authorized = Path(remote.pw_dir) / '.ssh'
    authorized.mkdir(mode=0o700)
    os.chown(authorized, remote.pw_uid, remote.pw_gid)
    public_key = authorized / 'authorized_keys'
    public_key.write_bytes(key.with_suffix('.pub').read_bytes())
    public_key.chmod(0o600)
    os.chown(public_key, remote.pw_uid, remote.pw_gid)
    known = ssh / 'known_hosts'
    known.write_text('[127.0.0.1]:2222 ' + host.with_suffix('.pub').read_text(), encoding='utf-8')
    known.chmod(0o600)
    os.chown(known, account.pw_uid, account.pw_gid)
    settings = runtime / 'sshd_config'
    settings.write_text('Port 2222\nListenAddress 127.0.0.1\nHostKey ' + str(host) + '\n'
        'PidFile /run/lsf-qualification/sshd.pid\nAllowUsers lsfremote\nPermitRootLogin no\n'
        'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitEmptyPasswords no\n'
        'UsePAM no\nPubkeyAuthentication yes\nStrictModes yes\nAuthorizedKeysFile .ssh/authorized_keys\n'
        'DisableForwarding yes\nPermitTTY no\nLogLevel ERROR\n', encoding='utf-8')
    selected['sshBackend'] = {'kind': 'ssh', 'helperSha256': selected['linuxHelperSha256'],
        'host': '127.0.0.1', 'port': 2222, 'user': 'lsfremote', 'ssh': '/usr/bin/ssh',
        'identityFile': str(key), 'knownHosts': str(known)}
    config = home / 'selected-inputs.json'
    config.write_text(json.dumps(selected), encoding='utf-8')
    config.chmod(0o600)
    os.chown(config, account.pw_uid, account.pw_gid)
    server = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', str(settings)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 10
        while True:
            assert server.poll() is None and time.monotonic() < deadline, 'owned SSH service readiness failed'
            try:
                with socket.create_connection(('127.0.0.1', 2222), timeout=1) as connection:
                    assert connection.recv(256).startswith(b'SSH-2.0-'), 'owned SSH service protocol'
                break
            except ConnectionRefusedError:
                time.sleep(0.05)
        completed = subprocess.run(['/usr/sbin/runuser', '-u', 'lsfqa', '--', '/usr/local/bin/python3.13', '-I', '-B',
            '/qualification/dev_packaged_linux.py', '--inputs', str(config), '--output', str(home / 'observation')],
            stdin=subprocess.DEVNULL, timeout=7200, env={'HOME': str(home), 'PATH': '/usr/local/bin:/usr/bin:/bin',
                                                       'LANG': 'C.UTF-8'})
        return completed.returncode
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)


if __name__ == '__main__':
    raise SystemExit(main())
