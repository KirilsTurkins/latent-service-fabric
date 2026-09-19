"""Run authenticated push, exact pull and evidence discovery on owned Harbor 2.15.2."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.harbor_registry.config import IMAGES, INSTALLER_DIGEST, bounded_compose, installer_template, write_input
from tools.harbor_registry.owner import Owner, command
from tools.harbor_registry.dns import Fixture as DnsFixture
from tools.run_oci_registry_tests import certificates
import yaml

TEST = 'bearer::real_harbor_bearer_roundtrip'


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def api(origin: str, certificate: Path, password: str, method: str, path: str, data=None):
    context = ssl.create_default_context(cafile=str(certificate))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirects(),
                                        urllib.request.HTTPSHandler(context=context))
    token = base64.b64encode(('admin:' + password).encode()).decode()
    body = None if data is None else json.dumps(data).encode()
    request = urllib.request.Request(origin + path, data=body, method=method,
                                     headers={'Authorization': 'Basic ' + token, 'Content-Type': 'application/json'})
    with opener.open(request, timeout=3) as response:
        body = response.read(65537)
        if len(body) > 65536:
            raise RuntimeError('Harbor management response byte bound')
        return json.loads(body) if body else None


def provision(origin: str, root: Path, password: str) -> Path:
    certificate = root / 'fixtures/ca.pem'
    deadline = time.monotonic() + 180
    while True:
        try:
            result = api(origin, certificate, password, 'GET', '/api/v2.0/health')
            if result.get('status') == 'healthy':
                break
        except (OSError, ValueError, urllib.error.URLError):
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError('Harbor readiness deadline exceeded')
        time.sleep(0.5)
    api(origin, certificate, password, 'POST', '/api/v2.0/projects',
        {'project_name': 'lsf-test', 'metadata': {'public': 'false'}, 'storage_limit': 16 * 1024 * 1024})
    robot = api(origin, certificate, password, 'POST', '/api/v2.0/robots', {
        'name': 'conformance', 'description': 'Disposable LSF package-only fixture',
        'duration': 1, 'level': 'project', 'permissions': [{
            'kind': 'project', 'namespace': 'lsf-test', 'access': [
                {'resource': 'repository', 'action': 'pull'}, {'resource': 'repository', 'action': 'push'}]}]})
    if not isinstance(robot, dict) or not all(isinstance(robot.get(field), str) and 1 <= len(robot[field]) <= 512 for field in ['name', 'secret']):
        raise RuntimeError('invalid Harbor robot credential')
    path = root / 'credential.json'
    with path.open('x', encoding='ascii') as output:
        json.dump({'username': robot['name'], 'password': robot['secret']}, output)
    path.chmod(0o600)
    return path


def source_snapshot() -> dict:
    return {'commit': command(['git', 'rev-parse', 'HEAD']),
            'trackedClean': not bool(command(['git', 'status', '--porcelain', '--untracked-files=no'])),
            'untrackedFiles': bool(command(['git', 'ls-files', '--others', '--exclude-standard']))}


def source_receipt(before: dict, after: dict, binary: Path | None) -> dict:
    stable = before == after
    receipt = {'sourceCommit': before['commit'], 'sourceStable': stable,
               'trackedTreeClean': stable and before['trackedClean'],
               'sourceTreeClean': stable and before['trackedClean'] and not before['untrackedFiles'],
               'testBinarySource': 'cargo test in this worktree' if binary is None else
                                   'caller supplied; source correspondence not established'}
    if binary is not None:
        with binary.open('rb') as source:
            receipt['testBinarySha256'] = hashlib.file_digest(source, 'sha256').hexdigest()
    return receipt


def run(arguments) -> dict:
    before = source_snapshot()
    if arguments.test_binary is None and not arguments.check_fixture:
        subprocess.run(['cargo', 'test', '-p', 'latent-oci', '--test', 'registry', '--locked', '--no-run'],
                       cwd=ROOT, check=True, timeout=900)
    owned_base = ROOT / 'target/phase3-harbor/runs'
    owned_base.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='run-', dir=owned_base)).resolve()
    if not root.is_relative_to(owned_base.resolve()):
        raise RuntimeError('Harbor fixture directory escaped its owner')
    token = uuid.uuid4().hex
    owner = Owner(root, token)
    print('Preparing owned Harbor fixture: ' + token, flush=True)
    receipt = None
    dns = None
    try:
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        fixture = root / 'fixtures'
        fixture.mkdir()
        certificates(fixture, dns_names=('harbor.test',) if arguments.network else ())
        password = 'Lsf1-' + secrets.token_hex(20)
        template = installer_template(ROOT / 'target/phase3-harbor/installer')
        write_input(root, port, password, template, network=arguments.network)
        owner.prepare()
        raw = yaml.safe_load((root / 'docker-compose.yml').read_bytes())
        compose = bounded_compose(raw, root, owner.project, token, port)
        (root / 'compose.json').write_text(json.dumps(compose), encoding='utf-8')
        owner.launch()
        origin = f'https://127.0.0.1:{port}'
        credential = provision(origin, root, password)
        if arguments.network:
            origin = f'https://harbor.test:{port}'
            dns = DnsFixture()
        if arguments.check_fixture:
            receipt = {'fixtureReady': True}
        else:
            environment = os.environ.copy()
            environment.update(LSF_OCI_TEST_ORIGIN=origin, LSF_OCI_TEST_CA_DER=str(fixture / 'ca.der'),
                               LSF_HARBOR_CREDENTIAL_FILE=str(credential))
            environment.pop('LSF_OCI_DNS_SERVER', None)
            if dns:
                environment['LSF_OCI_DNS_SERVER'] = dns.address
            test = ([str(arguments.test_binary.resolve())] if arguments.test_binary else
                    ['cargo', 'test', '-p', 'latent-oci', '--test', 'registry', '--locked', '--'])
            result = subprocess.run([*test, '--exact', TEST, '--ignored', '--nocapture', '--test-threads=1'],
                                    cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
            if len(result.stdout) > 1024 * 1024 or len(result.stderr) > 1024 * 1024:
                raise RuntimeError('Harbor test output limit')
            if result.returncode:
                (ROOT / 'target/phase3-harbor/last-test-failure.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
                raise RuntimeError('Harbor Rust conformance failed; local test diagnostics retained')
            marker = 'LSF_HARBOR_EVIDENCE '
            reports = [line.partition(marker)[2] for line in result.stdout.splitlines() if marker in line]
            if len(reports) != 1:
                raise RuntimeError('Harbor conformance evidence missing')
            receipt = json.loads(reports[0])
        receipt.update(installerSha256=INSTALLER_DIGEST, images=IMAGES)
        receipt.update(source_receipt(before, source_snapshot(), arguments.test_binary))
        if arguments.check_fixture:
            receipt['testBinarySource'] = 'not executed; fixture readiness only'
        if dns:
            receipt['dnsQueries'] = dns.count
    finally:
        try:
            if dns:
                dns.close()
        finally:
            owner.close()
            owner.release_files()
            if not root.resolve().is_relative_to(owned_base.resolve()):
                raise RuntimeError('refusing unowned Harbor directory cleanup')
            shutil.rmtree(root)
    receipt['ownedContainersNetworksVolumesRemoved'] = True
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test-binary', type=Path)
    parser.add_argument('--check-fixture', action='store_true')
    parser.add_argument('--network', action='store_true', help='exercise the explicit bounded DNS and connected-peer profile')
    parser.add_argument('--output', type=Path)
    arguments = parser.parse_args()
    receipt = run(arguments)
    rendered = json.dumps(receipt, indent=2) + '\n'
    if arguments.output:
        with arguments.output.open('x', encoding='utf-8') as output:
            output.write(rendered)
    print(rendered)
    return 0


if __name__ == '__main__':
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        reason = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        print('Harbor conformance failed: ' + reason, file=sys.stderr)
        sys.exit(1)
