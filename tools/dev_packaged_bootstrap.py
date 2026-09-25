"""Authenticate and unpack the first native frontend before executing its code."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import unicodedata
import zipfile

if __package__:
    from .dev_packaged_process import Command, digest, environment, read_json, require
else:
    from dev_packaged_process import Command, digest, environment, read_json, require

REPOSITORY = 'KirilsTurkins/latent-service-fabric'


def authenticate(config, temporary, *, target='windows-x86_64'):
    require(target in {'windows-x86_64', 'linux-x86_64'}, 'closed-frontend-bootstrap-target')
    trust = config['trust']
    policy = read_json(trust['developerPolicy'])
    require(policy == config['approvedDeveloperPolicy'], 'independent-approved-policy-mismatch')
    require(policy['repository'] == REPOSITORY and policy['workflow'] == '.github/workflows/developer-tools.yml'
            and policy['sourceCommit'] == config['sourceCommit'] and policy['version'] == config['version']
            and policy['purpose'] == 'candidate' and re.fullmatch(r'[a-f0-9]{40}', config['sourceCommit']),
            'exact-nonpublishing-source-required')
    require(read_json(trust['runtimePolicy']) == config['approvedRuntimePolicy'], 'independent-runtime-policy-mismatch')
    runtime = config['approvedRuntimePolicy']
    require(runtime['sourceCommit'] == policy['sourceCommit'] and runtime['version'] == policy['version']
            and runtime['purpose'] == 'candidate', 'matching-runtime-policy-required')
    require(digest(trust['hostVerifier']) == trust['hostVerifierSha256']
            and digest(trust['guestVerifier']) == trust['guestVerifierSha256']
            and digest(trust['trustedRoot']) == trust['trustedRootSha256'], 'independent-verification-input-changed')
    root = Path(config['artifacts']['windows' if target == 'windows-x86_64' else 'linux'])
    command = Command([trust['hostVerifier'], 'attestation', 'verify', root / 'SHA256SUMS',
        '--bundle', root / 'attestation.json', '--custom-trusted-root', trust['trustedRoot'],
        '--repo', REPOSITORY, '--hostname', 'github.com', '--cert-identity',
        f"https://github.com/{REPOSITORY}/{policy['workflow']}@{policy['sourceRef']}",
        '--cert-oidc-issuer', 'https://token.actions.githubusercontent.com',
        '--source-ref', policy['sourceRef'], '--source-digest', policy['sourceCommit'],
        '--signer-digest', policy['sourceCommit'], '--deny-self-hosted-runners',
        '--predicate-type', 'https://slsa.dev/provenance/v1', '--digest-alg', 'sha256', '--format', 'json'],
        temporary, environment(temporary))
    try:
        require(command.finish(90) == 0, 'frontend-attestation-rejected')
        verified = json.loads(command.raw())
    finally:
        command.abort_controller()
    manifest = read_json(root / 'developer-bundle.json')
    require(manifest['sourceCommit'] == config['sourceCommit'] and manifest['version'] == config['version']
            and manifest['target'] == target and manifest['schemaVersion'] == 'latent.dev.bundle.v1'
            and manifest['hostAbi'] == 'lsf-host-abi-phase3-v4' and manifest['protocol'] == 'latent.dev.protocol.v1',
            'frontend-identity-or-target')
    archive = manifest['archive']
    require(re.fullmatch(r'[A-Za-z0-9._-]+\.zip', archive['name']), 'frontend-archive-name')
    expected = {'developer-bundle.json': digest(root / 'developer-bundle.json')[7:], archive['name']: archive['sha256'][7:]}
    require((root / 'SHA256SUMS').read_bytes() == ''.join(f'{value}  {name}\n' for name, value in sorted(expected.items())).encode(),
            'frontend-checksum-inventory')
    require(0 < archive['size'] <= 1024**3 and (root / archive['name']).stat().st_size == archive['size']
            and digest(root / archive['name']) == archive['sha256'], 'frontend-archive-digest')
    return manifest, {'verifier': command.receipt(), 'attestation': verified}


def extract(root, manifest, destination):
    deadline = time.monotonic() + 300
    require(not destination.exists(), 'new-frontend-directory-required')
    target = manifest.get('target', 'windows-x86_64')
    require(target in {'windows-x86_64', 'linux-x86_64'}, 'closed-frontend-bootstrap-target')
    executable = 'bin/latent-dev.exe' if target == 'windows-x86_64' else 'bin/latent-dev'
    entries = manifest['files']
    require(0 < len(entries) <= 4096, 'frontend-inventory-bound')
    files, aliases = {}, set()
    total = 0
    for entry in entries:
        name = entry['path']
        parts = PurePosixPath(name).parts
        require(parts and '/'.join(parts) == name and not name.startswith('/') and '\\' not in name
                and not any(ord(char) < 32 or char in ':<>"|?*' for char in name)
                and all(part not in {'.', '..'} and part.rstrip(' .') == part for part in parts)
                and unicodedata.normalize('NFC', name).casefold() not in aliases, 'frontend-unsafe-member')
        require(all(part.split('.')[0].upper() not in {'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))} for part in parts),
                'frontend-device-member')
        require(type(entry['size']) is int and 0 <= entry['size'] <= 1024**3
                and re.fullmatch(r'sha256:[a-f0-9]{64}', entry['sha256']), 'frontend-entry-bound')
        total += entry['size']
        files[name] = entry
        aliases.add(unicodedata.normalize('NFC', name).casefold())
    require(total <= 2 * 1024**3 and executable in files
            and files[executable]['executable'] is True, 'frontend-expanded-byte-bound')
    require(not any('/'.join(name.split('/')[:n]).casefold() in aliases for name in files
                    for n in range(1, len(name.split('/')))), 'frontend-file-directory-collision')
    with zipfile.ZipFile(root / manifest['archive']['name']) as archive:
        members = archive.infolist()
        require(len(members) == len(files) and len({item.filename for item in members}) == len(files), 'frontend-member-count')
        for member in members:
            require(time.monotonic() < deadline, 'frontend-extraction-deadline')
            require(member.filename in files and not member.is_dir() and not member.flag_bits & 1
                    and stat.S_IFMT(member.external_attr >> 16) in {0, stat.S_IFREG}
                    and member.file_size == files[member.filename]['size'], 'frontend-member-identity')
        destination.mkdir(mode=0o700)
        for member in members:
            path = destination / member.filename
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            checksum, count = hashlib.sha256(), 0
            with archive.open(member) as source, path.open('xb') as output:
                while chunk := source.read(1024 * 1024):
                    require(time.monotonic() < deadline, 'frontend-extraction-deadline')
                    count += len(chunk)
                    require(count <= files[member.filename]['size'], 'frontend-expanded-member-bound')
                    checksum.update(chunk)
                    output.write(chunk)
            require(count == files[member.filename]['size']
                    and 'sha256:' + checksum.hexdigest() == files[member.filename]['sha256'], 'frontend-expanded-member-digest')
            if os.name == 'posix':
                path.chmod(0o700 if files[member.filename]['executable'] else 0o600)
    return destination / executable
