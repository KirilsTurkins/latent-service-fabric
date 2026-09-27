"""Finite source-built CLI conformance on the real owned Harbor fixture."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream)
    path.chmod(0o600)
    return path


def run(cli: Path, root: Path, origin: str, credential: Path, dns):
    cli = cli.resolve(strict=True)
    work = root / 'cli'
    work.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment['TMPDIR'] = str(work)
    prepared = subprocess.run(['node', str(ROOT / 'tools/harbor_registry/prepare.mjs'), str(cli)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, cwd=ROOT, timeout=120)
    if prepared.returncode or len(prepared.stdout) + len(prepared.stderr) > 262144:
        raise RuntimeError('Harbor CLI signed-input preparation failed')
    inputs = Path(json.loads(prepared.stdout)['work']).resolve(strict=True)
    if not inputs.is_relative_to(work.resolve()):
        raise RuntimeError('Harbor CLI input ownership failed')
    secret = json.loads(credential.read_bytes())
    write(work / 'credential.json', {'mode': 'basic', **secret})
    (work / 'ca.der').write_bytes((root / 'fixtures/ca.der').read_bytes())
    profile = {'formatVersion': 2, 'origin': origin, 'repository': 'lsf-test/cli', 'addresses': [],
        'credentialFile': 'credential.json', 'rootCertificates': ['ca.der'],
        'bearerChallenge': {'realm': origin + '/service/token', 'service': 'harbor-registry',
            'identity': {'tenant': 'tests', 'principal': 'fixture-ci', 'credentialEpoch': 1},
            'actions': 'pull-push', 'addresses': []},
        'network': {'maximumRedirects': 0, 'destinations': [{'origin': origin,
            'addresses': {'networks': ['127.0.0.1/32'], 'specialAddresses': ['127.0.0.1']},
            'resolution': {'mode': 'dns', 'server': dns.address, 'maximumTtlSeconds': 1}, 'contentPrefixes': []}]}}
    writer = write(work / 'writer.json', profile)
    reader_value = copy.deepcopy(profile); reader_value['bearerChallenge']['actions'] = 'pull'
    reader = write(work / 'reader.json', reader_value)
    calls, outcomes = 0, []
    deadline = time.monotonic() + 120

    def call(*args, success=True):
        nonlocal calls
        calls += 1
        if calls > 40 or time.monotonic() >= deadline:
            raise RuntimeError('Harbor CLI operation bound')
        result = subprocess.run([str(cli), '--output', 'json', '--connect-timeout-ms', '1000',
            '--rpc-timeout-ms', '10000', *(str(arg) for arg in args)], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=min(16, deadline - time.monotonic()))
        if len(result.stdout) + len(result.stderr) > 262144:
            raise RuntimeError('Harbor CLI output bound')
        value = json.loads(result.stdout)
        outcomes.append({key: value.get(key) for key in ('category', 'code', 'outcomeKnown')})
        if (result.returncode == 0) != success:
            raise RuntimeError('Harbor CLI unexpected outcome: ' + json.dumps(outcomes[-1]))
        if success and value.get('outcomeKnown') is not True:
            raise RuntimeError('Harbor CLI uncertain successful outcome')
        return value

    packages = []
    for name in ['site', 'documentation']:
        package, evidence = inputs / name / 'package', inputs / (name + '-evidence')
        digest = call('package', 'inspect', package)['data']['packageDigest']
        pushed = call('package', 'push', package, '--registry-profile', writer, '--reference', digest,
                      '--evidence-index', evidence / 'index.json', '--evidence-root', evidence)
        confirmed = pushed['data']['transfer']['confirmedDigests']
        index = json.loads((evidence / 'index.json').read_bytes())
        expected = {digest}
        for kind in ('signatures', 'provenance', 'sboms'):
            expected.update('sha256:' + hashlib.sha256((evidence / row['manifest']).read_bytes()).hexdigest()
                            for row in index[kind])
        if len(confirmed) != len(expected) or set(confirmed) != expected:
            raise RuntimeError('Harbor CLI exact package and evidence confirmation required')
        destination = work / (name + '-pulled'); destination.mkdir(mode=0o700)
        call('package', 'pull', '--registry-profile', reader, '--reference', digest,
             '--output-dir', destination / 'package', '--evidence-output', destination / 'evidence')
        observed = call('package', 'inspect', destination / 'package')['data']
        if observed['packageDigest'] != digest:
            raise RuntimeError('Harbor CLI exact pull subject mismatch')
        call('--tenant', 'tests', 'package', 'verify', destination / 'package',
             '--evidence-index', destination / 'evidence/index.json', '--evidence-root', destination / 'evidence',
             '--policy', inputs / 'policy.json')
        packages.append({'packageDigest': digest, 'confirmedDigests': confirmed, 'publisherAndBuilderVerified': True})
    package = inputs / 'site/package'
    call('package', 'push', package, '--registry-profile', reader, '--reference', 'denied-read-only', success=False)
    negatives = []
    for name in ['address', 'tls', 'credential', 'repository', 'unavailable']:
        value = copy.deepcopy(profile)
        if name == 'address': value['network']['destinations'][0]['addresses']['specialAddresses'] = []
        if name == 'tls': value['rootCertificates'] = []
        if name == 'credential':
            write(work / 'denied-credential.json', {'mode': 'basic', 'username': 'not-authorized', 'password': 'not-a-secret'})
            value['credentialFile'] = 'denied-credential.json'
        if name == 'repository': value['repository'] = 'outside-project/cli'
        if name == 'unavailable':
            # A real refused local endpoint, still subject to explicit address policy.
            value['origin'] = 'https://harbor.test:1'
            value['bearerChallenge']['realm'] = value['origin'] + '/service/token'
            value['network']['destinations'][0]['origin'] = value['origin']
        selected = write(work / (name + '-profile.json'), value)
        call('package', 'pull', '--registry-profile', selected, '--reference', packages[0]['packageDigest'],
             '--output-dir', work / (name + '-package'), '--evidence-output', work / (name + '-evidence'), success=False)
        negatives.append(name)
    with cli.open('rb') as stream: binary_digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'schemaVersion': 'latent.harbor-cli.v1', 'passed': True, 'actualRegistry': 'Harbor 2.15.2',
        'cliSha256': binary_digest, 'cliReleasedBinary': False, 'packages': packages, 'cliProcesses': calls,
        'dnsQueries': dns.count, 'negativeCases': negatives, 'pullOnlyWriteDenied': True,
        'cloudQualified': False, 'redirects': 'disabled; local Harbor storage',
        'tokenExpiry': 'each CLI owns fresh token state; in-operation refresh has separate TLS conformance',
        'credentialLifetime': 'one-day disposable project robot, destroyed with the owned registry'}
