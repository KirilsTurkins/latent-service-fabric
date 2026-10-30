"""Four exact retained compiler members; no compilation or receipt relabeling."""
from pathlib import Path
import os
import stat
import sys
import urllib.error
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_replay_materials import api, NoRedirect, Ranges, REPOSITORY
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import fresh, write_json
from tools.rust_thread_runtime_package import SOURCE, RUN, PINS

HISTORICAL_ARTIFACT = {'id': 12469845581, 'size_in_bytes': 52246859,
    'digest': 'sha256:76e11dc5d099d353d027b5e946ec7624f5c7bc90110f4844fc9aff387f2afdc6'}
EARLIER_ARTIFACT = {'id': 12968677962, 'size_in_bytes': 52244511,
    'digest': 'sha256:feae6e80f418041ca48d5dce1c82456903d1d77cf5e93d1878e2ed0bd36a6138'}
PREVIOUS_ARTIFACT = {'id': 12978203439, 'size_in_bytes': 55102784,
    'digest': 'sha256:6570db47d0c9657b3375d66c0ddd720cbc2c05fcce61b48d3d2b9ae7ff47dbf2'}
PRIOR_ARTIFACT = {'id': 12996890774, 'size_in_bytes': 53110361,
    'digest': 'sha256:1adc79551de5dfd54255c9fba50346a18161eeec3d01c2c097f06e69b8251e86'}
ARTIFACT = {'id': 13004447135, 'size_in_bytes': 53113028,
    'digest': 'sha256:b7df73bbe827a016e45b1681db7304054a6d941c7d1844ebde87063417a58c37'}
JOB = 124260142818
PREFIX = 'application-diagnostic/'


def prepare(output: Path) -> dict:
    run, job = api(f'actions/runs/{RUN}'), api(f'actions/jobs/{JOB}')
    require(run['id'] == RUN and run['path'] == '.github/workflows/rust-owned-thread-inputs.yml'
            and run['event'] == 'workflow_dispatch' and run['head_sha'] == SOURCE
            and run['head_branch'] == 'feat/rust-thread-runtime-20261023'
            and run['status'] == 'completed' and run['conclusion'] == 'success'
            and job['id'] == JOB and job['run_id'] == RUN and job['head_sha'] == SOURCE
            and job['name'] == 'Compile exact Rust context utility and owned thread sysroot'
            and job['status'] == 'completed' and job['conclusion'] == 'success',
            'rust-thread-retained-official-compiler-origin')
    listing = api(f'actions/runs/{RUN}/artifacts?per_page=100')
    require(listing['total_count'] == len(listing['artifacts']) == 1,
            'rust-thread-retained-compiler-single-artifact')
    artifact = listing['artifacts'][0]
    require(all(artifact.get(name) == value for name, value in ARTIFACT.items())
            and artifact['expired'] is False and artifact['workflow_run']['id'] == RUN
            and artifact['workflow_run']['head_sha'] == SOURCE,
            'rust-thread-retained-compiler-exact-artifact')
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and bool(token), 'rust-thread-retained-explicit-actions-token')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT["id"]}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'rust-thread-retained-artifact-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('rust-thread-retained-artifact-redirect-required')
    require(url.startswith('https://'), 'rust-thread-retained-artifact-https')
    remote = Ranges(url, ARTIFACT['size_in_bytes'])
    identities = {}
    with zipfile.ZipFile(remote) as archive:
        rows = archive.infolist()
        require(len(rows) == 125 and len({row.filename.casefold() for row in rows}) == 125,
                'rust-thread-retained-compiler-archive-index')
        # Only these four names can be extracted; all are fixed by the independently
        # verified immutable compiler event. No executable from this archive runs.
        for name, (size, sha) in PINS.items():
            member = archive.getinfo(PREFIX + name)
            require(member.file_size == size and not member.is_dir()
                    and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG),
                    'rust-thread-retained-compiler-member-preflight')
        for name, (size, sha) in PINS.items():
            count = 0
            with archive.open(PREFIX + name) as stream, (output / name).open('xb') as destination:
                while data := stream.read(8 * 1024 * 1024):
                    count += len(data)
                    require(count <= size, 'rust-thread-retained-compiler-member-bound')
                    destination.write(data)
            actual = file_identity(output / name, 32 * 1024 * 1024)
            require(count == size and actual == {'bytes': size, 'sha256': 'sha256:' + sha},
                    'rust-thread-retained-compiler-member-hash')
            identities[name] = actual
    record = {'schemaVersion': 'latent.rust.thread-retained-compiler.v1',
        'source': SOURCE, 'run': RUN, 'job': JOB, 'artifact': ARTIFACT,
        'producerAttempt': 1, 'historicalArtifact': HISTORICAL_ARTIFACT,
        'earlierArtifact': EARLIER_ARTIFACT, 'previousArtifact': PREVIOUS_ARTIFACT,
        'priorArtifact': PRIOR_ARTIFACT,
        'archiveDigestVerification': 'official-metadata-only-selected-members-hash-verified',
        'wholeArchiveRetained': False, 'selected': identities,
        'rangeBytes': remote.transferred, 'rangeRequests': remote.requests,
        'applicationRecompiled': False, 'retainedExecutableInvoked': False,
        'originalCompilerReceiptRewritten': False, 'actualGuestExecuted': False}
    write_json(output / 'retrieval.json', record)
    return record


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
