#!/usr/bin/env python3
"""Stage only the conductor and independent verification inputs for a clean host."""
from __future__ import annotations

import hashlib
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TRUSTED_ROOT_SHA = '65ca537f6ed8a47fd0e560c421baa1f6c1efb8b25fc200d8c5c02c0e92eb2b9c'
VERIFIERS = {
    'windows': ('gh_2.96.0_windows_amd64.zip', 'c2d6acc935cd2f00e2144d7e036d5cd82e6b6bd5594e8c75aa75ef2a4ed6aac3'),
    'linux': ('gh_2.96.0_linux_amd64.tar.gz', '83d5c2ccad5498f58bf6368acb1ab32588cf43ab3a4b1c301bf36328b1c8bd60')}


def checked(condition, code):
    if not condition:
        raise ValueError(code)


def download(url, *, token=None, maximum=64 * 1024 * 1024):
    headers = {'User-Agent': 'LSF-packaged-qualification'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        data = response.read(maximum + 1)
    checked(len(data) <= maximum, 'verification-input-download-limit')
    return data


def main():
    selected = json.loads(os.environ['LSF_APPROVED_POLICIES'])
    checked(set(selected) == {'developer', 'runtime'}, 'two-independent-policies-required')
    source = selected['developer']['sourceCommit']
    checked(re.fullmatch(r'[a-f0-9]{40}', source), 'exact-source-required')
    for name, workflow in (('developer', 'developer-tools.yml'), ('runtime', 'native-runtime.yml')):
        value = selected[name]
        checked(set(value) == {'schemaVersion', 'repository', 'workflow', 'sourceRef', 'sourceCommit', 'version', 'purpose'},
                'publisher-policy-fields')
        checked(value['schemaVersion'] == 'latent.native-publisher-policy.v1'
                and value['repository'] == 'KirilsTurkins/latent-service-fabric'
                and value['workflow'] == '.github/workflows/' + workflow and value['purpose'] == 'candidate'
                and value['sourceCommit'] == source and value['version'] == selected['developer']['version']
                and re.fullmatch(r'refs/heads/[A-Za-z0-9._/-]+', value['sourceRef']), 'candidate-policy-selection')
    target = Path(os.environ['RUNNER_TEMP']) / 'packaged-support'
    target.mkdir()
    runs = {}
    for kind, variable, workflow in (('developer', 'LSF_DEVELOPER_RUN', 'developer-tools.yml'),
                                     ('runtime', 'LSF_RUNTIME_RUN', 'native-runtime.yml')):
        number = os.environ[variable]
        checked(re.fullmatch(r'[0-9]{1,20}', number), 'numeric-candidate-run-required')
        run = json.loads(download(f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/runs/{number}',
                                 token=os.environ['GH_TOKEN'], maximum=1024 * 1024))
        checked(run['head_sha'] == source and run['status'] == 'completed' and run['conclusion'] == 'success'
                and run['path'] == '.github/workflows/' + workflow, 'successful-exact-candidate-workflow-required')
        runs[kind] = {'id': int(number), 'url': run['html_url'], 'sourceCommit': source, 'conclusion': run['conclusion']}
    for name in ('dev_packaged_probe', 'dev_packaged_process', 'dev_packaged_bootstrap', 'dev_packaged_windows',
                 'dev_packaged_guest', 'dev_packaged_watch', 'dev_packaged_linux', 'dev_packaged_linux_host',
                 'dev_packaged_linux_entry', 'dev_packaged_recovery', 'dev_packaged_wsl_lifecycle', 'dev_node_fault_probe',
                 'dev_packaged_container_host', 'dev_packaged_container_peer', 'dev_packaged_container_client'):
        shutil.copyfile(ROOT / 'tools' / (name + '.py'), target / (name + '.py'))
    shutil.copyfile(ROOT / 'packaging/dev/qualification.Dockerfile', target / 'qualification.Dockerfile')
    root = ROOT / 'packaging/dev/qualification-trusted-root.jsonl'
    checked(hashlib.sha256(root.read_bytes()).hexdigest() == TRUSTED_ROOT_SHA, 'independent-trust-root-changed')
    shutil.copyfile(root, target / 'trusted_root.jsonl')
    verifiers = {}
    for kind, (name, expected) in VERIFIERS.items():
        raw = download('https://github.com/cli/cli/releases/download/v2.96.0/' + name)
        checked(hashlib.sha256(raw).hexdigest() == expected, 'independent-gh-archive-digest')
        if kind == 'windows':
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                names = [name for name in archive.namelist() if name == 'bin/gh.exe' or name.endswith('/bin/gh.exe')]
                checked(len(names) == 1 and archive.getinfo(names[0]).file_size <= 134217728, 'gh-windows-member')
                binary = archive.read(names[0])
        else:
            with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
                member = archive.getmember('gh_2.96.0_linux_amd64/bin/gh')
                checked(member.isfile() and member.size <= 134217728, 'gh-linux-member')
                binary = archive.extractfile(member).read()
        file = target / ('gh.exe' if kind == 'windows' else 'gh-linux')
        file.write_bytes(binary)
        file.chmod(0o700)
        verifiers[kind] = 'sha256:' + hashlib.sha256(binary).hexdigest()
    for key in ('developer', 'runtime'):
        (target / (key + '-policy.json')).write_text(json.dumps(selected[key], sort_keys=True) + '\n', encoding='utf-8')
    if __package__:
        from .dev_packaged_container_host import CLI_SHA512
    else:
        from dev_packaged_container_host import CLI_SHA512
    archive = download('https://registry.npmjs.org/@devcontainers/cli/-/cli-0.89.0.tgz')
    checked(base64.b64encode(hashlib.sha512(archive).digest()).decode() == CLI_SHA512, 'reviewed-devcontainer-cli-digest')
    (target / 'devcontainer-cli.tgz').write_bytes(archive)
    plan = {'sourceCommit': source, 'version': selected['developer']['version'],
        'approvedDeveloperPolicy': selected['developer'], 'approvedRuntimePolicy': selected['runtime'],
        'consentProvisionAndInstall': True, 'independentPolicyApproved': True,
        'verificationInputs': {'verifierSha256': verifiers, 'trustedRootSha256': 'sha256:' + TRUSTED_ROOT_SHA},
        'candidateRuns': runs, 'conductorSourceCommit': os.environ['GITHUB_SHA'],
        'faultProbeSha256': 'sha256:' + hashlib.sha256((target / 'dev_node_fault_probe.py').read_bytes()).hexdigest(),
        'devcontainerCli': {'version': '0.89.0', 'archiveSha512Base64': CLI_SHA512}}
    (target / 'selection.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    print('Prepared separate conductor and exact candidate verification inputs:', source)


if __name__ == '__main__':
    main()
