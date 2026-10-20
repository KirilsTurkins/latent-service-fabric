"""Diagnostic-only acquisition of the actual random-byte retirement host."""
import hashlib
import io
import json
from pathlib import PurePosixPath
import re
import stat
import subprocess
import tarfile
import zipfile

from tools import dotnet_task_replay_acquisition as historical
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json

SOURCE = '75b408ea0184936aa1dc21df2c9dd5e6c44bbc46'
RUN = 39359322603
JOB = 118421487525
PROFILE = {'opt_level': '0', 'debuginfo': 0, 'debug_assertions': True,
           'overflow_checks': True, 'test': False}
MEMBERS = {'source.tar.gz': 128*1024**2, 'source.sha256': 4096,
           'random.log': 16*1024**2, 'tests.json': 1024**2,
           'native-build.jsonl': 16*1024**2, 'latentd': 512*1024**2,
           'current-host.json': 1024**2}


def origin():
    job = historical.api(f'actions/jobs/{JOB}')
    require(job['run_id'] == RUN and job['head_sha'] == SOURCE
            and job['status'] == 'completed' and job['conclusion'] == 'success',
            'byte-host-successful-actual-job-required')
    run = historical.api(f'actions/runs/{RUN}')
    require(run['head_sha'] == SOURCE and run['event'] == 'push'
            and run['path'] == '.github/workflows/random-bytes-lowering-reference.yml',
            'byte-host-fixed-owning-workflow')
    artifacts = historical.api(f'actions/runs/{RUN}/artifacts?per_page=100')
    require(artifacts['total_count'] == len(artifacts['artifacts']) == 1,
            'byte-host-single-artifact')
    artifact = artifacts['artifacts'][0]
    require(artifact['name'] == 'random-byte-lowering-'+SOURCE and not artifact['expired']
            and 0 < artifact['size_in_bytes'] <= 192*1024**2
            and re.fullmatch(r'sha256:[0-9a-f]{64}', artifact['digest']) is not None
            and artifact['workflow_run']['id'] == RUN
            and artifact['workflow_run']['head_sha'] == SOURCE, 'byte-host-artifact-origin')
    return artifact


def validate(root):
    info = read_json(root/'current-host.json')
    require(info['schemaVersion'] == 'latent.random-byte-lowering.host.v1'
            and info['compiledSource'] == SOURCE and info['features'] == []
            and info['ordinaryDefaults'] is True and info['profile'] == PROFILE
            and info['hermetic'] is False and info['implicitCompilerInputs'] == 'not-attested'
            and file_identity(root/'latentd', MEMBERS['latentd']) == info['binary']
            and file_identity(root/'source.tar.gz', MEMBERS['source.tar.gz']) == info['sourceArchive'],
            'byte-host-normal-product-profile')
    # Compare every archived native source byte with the frozen Git revision.
    listed = subprocess.check_output(['git', 'ls-tree', '-rz', SOURCE, '--',
        'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', '.cargo/config.toml',
        'apps', 'crates', 'sdk/rust', 'tools/optimization-workloads'], cwd=ROOT)
    entries = []
    for row in listed.rstrip(b'\0').split(b'\0'):
        metadata, name = row.split(b'\t'); mode, kind, oid = metadata.decode().split()
        require(mode in ('100644', '100755') and kind == 'blob', 'byte-host-Git-regular')
        entries.append((name.decode(), oid))
    require(0 < len(entries) <= 16384, 'byte-host-source-count')
    blobs = subprocess.run(['git', 'cat-file', '--batch'],
        input=''.join(oid+'\n' for _, oid in entries).encode(), cwd=ROOT,
        check=True, stdout=subprocess.PIPE, timeout=60).stdout
    require(len(blobs) <= 128*1024**2, 'byte-host-source-byte-bound')
    expected, position = {}, 0
    for name, oid in entries:
        end = blobs.index(b'\n', position)
        header = blobs[position:end].decode().split()
        require(header[:2] == [oid, 'blob'], 'byte-host-Git-header')
        size = int(header[2]); data = blobs[end+1:end+1+size]; position = end+size+2
        require(len(data) == size and hashlib.sha1(b'blob '+str(size).encode()+b'\0'+data).hexdigest() == oid,
                'byte-host-Git-blob')
        expected[name] = data
    require(position == len(blobs), 'byte-host-Git-trailing')
    observed, total = set(), 0
    with tarfile.open(root/'source.tar.gz', 'r:gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and '\\' not in member.name,
                    'byte-host-tar-path')
            if member.isdir():
                continue
            require(member.isfile() and member.name in expected and member.name not in observed
                    and member.size == len(expected[member.name]), 'byte-host-tar-regular-source')
            total += member.size
            require(total <= 128*1024**2, 'byte-host-tar-expanded-bound')
            require(archive.extractfile(member).read(member.size+1) == expected[member.name],
                    'byte-host-source-archive-Git-match')
            observed.add(member.name)
    require(observed == set(expected), 'byte-host-complete-source-archive')
    suites = json.loads(subprocess.check_output(['git', 'show', SOURCE+':tools/ci/suites.json'], cwd=ROOT))
    cases = next(s['expectedCases'] for s in suites['suites'] if s['id'] == 'latent-wasmtime.test.random')
    log = (root/'random.log').read_bytes()
    names = [n.decode() for n in re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', log, re.M)]
    require(len(names) == len(set(names)) == 17 and sorted(names) == sorted(cases)
            and re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', log, re.M)
                == [(b'17', b'0', b'0', b'0', b'0')], 'byte-host-actual-seventeen-tests')
    require(info['tests'] == read_json(root/'tests.json') == {'source': SOURCE, 'cases': names,
        'passed': 17, 'failed': 0, 'ignored': 0, 'filtered': 0,
        'randomByteLimitRaised': False, 'otherListRetentionChanged': False}, 'byte-host-test-receipt')
    artifacts = [r for line in (root/'native-build.jsonl').read_bytes().splitlines()
        if (r := json.loads(line)).get('reason') == 'compiler-artifact'
        and r['target']['name'] == 'latentd' and r.get('executable')]
    require(len(artifacts) == 1 and artifacts[0]['features'] == []
            and artifacts[0]['profile'] == PROFILE, 'byte-host-actual-cargo-profile')
    return info


def retrieve(output):
    artifact = origin()
    output = fresh(output)
    raw = subprocess.check_output(['gh', 'api', 'repos/'+historical.REPOSITORY+
        f"/actions/artifacts/{artifact['id']}/zip"], timeout=180)
    require(len(raw) == artifact['size_in_bytes']
            and 'sha256:'+hashlib.sha256(raw).hexdigest() == artifact['digest'], 'byte-host-ZIP-digest')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require(len(archive.infolist()) == len(MEMBERS)
                and set(archive.namelist()) == set(MEMBERS), 'byte-host-fixed-ZIP-members')
        for row in archive.infolist():
            require(not row.is_dir() and 0 < row.file_size <= MEMBERS[row.filename]
                    and stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG), 'byte-host-ZIP-regular')
            (output/row.filename).write_bytes(archive.read(row))
    info = validate(output)
    (output/'latentd').chmod(0o700)
    record = {'compiledSource': SOURCE, 'compiledTree': historical.api('git/commits/'+SOURCE)['tree']['sha'],
        'run': RUN, 'job': JOB, 'artifact': artifact['id'], 'archiveDigest': artifact['digest'],
        'binary': info['binary'], 'sourceArchive': info['sourceArchive'],
        'sourceIdentity': historical.git_source_identity(SOURCE), 'features': [], 'profile': PROFILE,
        'ordinaryDefaults': True, 'actualRandomTests': 17, 'currentDevelopmentCompilationClaimed': False}
    write_json(output/'host-retrieval.json', record)
    return record
