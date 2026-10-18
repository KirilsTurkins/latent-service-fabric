#!/usr/bin/env python3
"""Run the delivered C watch qualification in a private, offline CI account."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow import process
from tools.dev_workflow.common import decode, encode, require
from tools.native_runtime import files


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return 'sha256:' + hashlib.file_digest(stream, 'sha256').hexdigest()


def run(payload: Path, supplied: Path, output: Path, *, qualifier: Path, fixture: Path, node_probe: Path) -> None:
    require(sys.platform == 'linux' and os.geteuid() == 0
            and os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('RUNNER_OS') == 'Linux',
            'private-c-watch-account-only-on-ephemeral-linux-ci')
    require(not output.exists(), 'fresh-c-watch-ci-output-required')
    home = Path(tempfile.mkdtemp(prefix='lsf-c-watch-ci-', dir='/tmp'))
    with files.directory(home, {0}):
        pass
    name = 'lsf-c-watch-' + secrets.token_hex(4)
    subprocess.run(['/usr/sbin/useradd', '--system', '--user-group', '--no-create-home',
                    '--home-dir', str(home), '--shell', '/usr/sbin/nologin', name], check=True, timeout=30)
    account = pwd.getpwnam(name)
    require(account.pw_uid != 0 and account.pw_dir == str(home), 'private-c-watch-passwd-identity')
    root = Path(__file__).resolve().parent
    require((qualifier, fixture, node_probe) == tuple(root / filename for filename in (
        'qualify_c_dependency_watch.py', 'c_dependency_watch_fixture.py', 'dev_node_application_probe.py')),
        'reviewed-c-watch-source-fixtures-required')
    # The candidate recipe/controller comes only from the captured distribution.
    # These three explicit source fixtures are independently digest-bound.
    for source, destination in ((payload, home / 'payload'), (supplied, home / 'source-node')):
        shutil.copytree(source, destination, symlinks=True)
    fixtures = ('qualify_c_dependency_watch.py', 'c_dependency_watch_fixture.py', 'dev_node_application_probe.py')
    for filename in fixtures:
        shutil.copyfile(root / filename, home / filename)
    for parent, directories, names in os.walk(home, followlinks=False):
        for path in (Path(parent), *(Path(parent) / child for child in (*directories, *names))):
            os.chown(path, account.pw_uid, account.pw_gid, follow_symlinks=False)
    python = home / 'payload/sdk/bin/python'
    helper = home / 'source-node/helper.pyz'
    probe = home / 'dev_node_application_probe.py'
    fixture = home / 'c_dependency_watch_fixture.py'
    observed = home / 'observation'
    command = ['/usr/sbin/runuser', '-u', name, '--', str(python), '-I', '-B',
        str(home / 'qualify_c_dependency_watch.py'), '--installed', str(home / 'payload'),
        '--helper', str(helper), '--helper-sha256', digest(helper),
        '--source-probe', str(probe), '--source-probe-sha256', digest(probe),
        '--fixture-source', str(fixture), '--fixture-sha256', digest(fixture),
        '--source-node', str(home / 'source-node'), '--output', str(observed)]
    result = None
    try:
        # The child alone gets a fresh network namespace. Only loopback is up;
        # authoring, three signed nodes and their local control connections share
        # that namespace. No compiler/feed can reach an original network source.
        result = process.run(['/usr/bin/unshare', '--net', '/bin/sh', '-c',
            '/usr/sbin/ip link set lo up && exec "$@"', 'c-watch-offline', *command],
            home, timeout=2450, graceful=15, maximum=262144)
    finally:
        output.mkdir(mode=0o755)
        public = observed / 'public-qualification.json'
        if public.is_file() and not public.is_symlink():
            (output / public.name).write_bytes(files.read(public, 1024 * 1024, owners={0, account.pw_uid}))
        for filename in ('initial-build.stdout', 'initial-build.stderr'):
            diagnostic = observed / filename
            if diagnostic.is_file() and not diagnostic.is_symlink():
                (output / filename).write_bytes(files.read(diagnostic, 1024 * 1024, owners={0, account.pw_uid}))
        (output / 'ci-account.json').write_bytes(encode({
            'purpose': 'ephemeral-source-c-dependency-watch', 'privatePasswdHome': True,
            'dedicatedUnprivilegedAccount': True, 'requestedNetworkNamespace': 'loopback-only',
            'runnerAclChanged': False, 'cleanup': 'private-evidence-retained-until-runner-teardown'}))
    require(result is not None and result.returncode == 0, 'actual-c-dependency-watch-qualification-failed')
    report = decode((output / 'public-qualification.json').read_bytes(), 1024 * 1024)
    require(report['passed'] is True and report['deploymentCount'] == 3,
            'actual-c-dependency-watch-or-cleanup-unconfirmed')
    print('Delivered C dependency watch passed: three reviewed signed builds in an offline private account')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('payload', 'source-node', 'output'):
        parser.add_argument('--' + argument, type=Path, required=True)
    for argument in ('qualifier', 'fixture', 'node-probe'):
        parser.add_argument('--' + argument, type=Path, required=True)
    args = parser.parse_args()
    run(args.payload.resolve(strict=True), args.source_node.resolve(strict=True), args.output.absolute(),
        qualifier=args.qualifier.resolve(strict=True), fixture=args.fixture.resolve(strict=True),
        node_probe=args.node_probe.resolve(strict=True))
