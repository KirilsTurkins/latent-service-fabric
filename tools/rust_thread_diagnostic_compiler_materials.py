"""Four exact retained compiler members; no compilation or receipt relabeling."""
from pathlib import Path
import os
import re
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
from tools.rust_thread_diagnostic_package import SOURCE, RUN, PINS

HISTORICAL_ARTIFACT = {'id': 12469845581, 'size_in_bytes': 52246859,
    'digest': 'sha256:76e11dc5d099d353d027b5e946ec7624f5c7bc90110f4844fc9aff387f2afdc6'}
EARLIER_ARTIFACT = {'id': 12968677962, 'size_in_bytes': 52244511,
    'digest': 'sha256:feae6e80f418041ca48d5dce1c82456903d1d77cf5e93d1878e2ed0bd36a6138'}
PREVIOUS_ARTIFACT = {'id': 12978203439, 'size_in_bytes': 55102784,
    'digest': 'sha256:6570db47d0c9657b3375d66c0ddd720cbc2c05fcce61b48d3d2b9ae7ff47dbf2'}
PRIOR_ARTIFACT = {'id': 12996890774, 'size_in_bytes': 53110361,
    'digest': 'sha256:1adc79551de5dfd54255c9fba50346a18161eeec3d01c2c097f06e69b8251e86'}
LATEST_PREVIOUS_ARTIFACT = {'id': 13004447135, 'size_in_bytes': 53113028,
    'digest': 'sha256:b7df73bbe827a016e45b1681db7304054a6d941c7d1844ebde87063417a58c37'}
CATALOGUE_PREVIOUS_ARTIFACT = {'id': 13012116413, 'size_in_bytes': 53116510,
    'digest': 'sha256:1f1fc1598c340b22f74b2bdf6b361ad576168738bbd619043a136a5faefcf45e'}
ARTIFACT = {'id': 13038776169, 'size_in_bytes': 53097750, 'digest': 'sha256:c3dcc608d605de8b07fffbfa6bdbc15d78311253107cc5d752cb448c7bfdbaf7'}
JOB = 124504142965
PREFIX = 'application-diagnostic/'
# These identify the separately verified storage event, not a new compiler run.
RECOVERY = {'run': 41886594203, 'job': 126772593516,
    'source': '83f1bbd2fad747471c37a777a50965dfd81351c0',
    'artifact': {'id': 13357657805, 'size_in_bytes': 20919269,
        'digest': 'sha256:59628870883ca8870072332004efb1325e76ecb7d3aa1700ce39c430eb6c3a0f'}}
RECOVERY_BRANCH = 'recovery/rust-e3-retained-20261104'
RECOVERY_WORKFLOW = '.github/workflows/rust-e3-retained-recovery.yml'
RECOVERY_NAME = 'rust-e3-retained-four-members-recovery'
RECOVERY_JOB_NAME = 'Restore exact retained Rust e3 compiler inputs'


def storage_for(listing):
    require(type(listing.get('artifacts')) is list
            and listing.get('total_count') == len(listing['artifacts'])
            and len(listing['artifacts']) <= 1,
            'rust-thread-retained-compiler-single-artifact')
    if listing['artifacts']:
        original = listing['artifacts'][0]
        require(all(original.get(name) == value for name, value in ARTIFACT.items())
                and original['workflow_run']['id'] == RUN
                and original['workflow_run']['head_sha'] == SOURCE
                and type(original.get('expired')) is bool,
                'rust-thread-retained-compiler-exact-artifact')
        if not original['expired']:
            return ARTIFACT, PREFIX, 125, {'kind': 'original-compiler-artifact',
                'run': RUN, 'job': JOB, 'source': SOURCE, 'artifact': ARTIFACT}
    # Expiry or an empty original listing alone does not authenticate new bytes.
    # A separately reviewed recovery run is mandatory; None always fails closed.
    c = RECOVERY
    require(type(c) is dict and set(c) == {'run', 'job', 'source', 'artifact'}
            and type(c['run']) is int and c['run'] > 0
            and type(c['job']) is int and c['job'] > 0
            and type(c['source']) is str and re.fullmatch('[0-9a-f]{40}', c['source']) is not None
            and type(c['artifact']) is dict
            and set(c['artifact']) == {'id', 'size_in_bytes', 'digest'}
            and type(c['artifact']['id']) is int and c['artifact']['id'] > 0
            and type(c['artifact']['size_in_bytes']) is int
            and 0 < c['artifact']['size_in_bytes'] <= 32 * 1024 * 1024
            and type(c['artifact']['digest']) is str
            and re.fullmatch('sha256:[0-9a-f]{64}', c['artifact']['digest']) is not None,
            'rust-thread-retained-recovery-unconfigured')
    recovery_run, recovery_job = api(f"actions/runs/{c['run']}"), api(f"actions/jobs/{c['job']}")
    require(recovery_run['id'] == c['run'] and recovery_run['path'] == RECOVERY_WORKFLOW
            and recovery_run['event'] == 'push' and recovery_run['head_sha'] == c['source']
            and recovery_run['head_branch'] == RECOVERY_BRANCH
            and recovery_run['repository']['full_name'] == REPOSITORY
            and recovery_run['head_repository']['full_name'] == REPOSITORY
            and recovery_run['status'] == 'completed' and recovery_run['conclusion'] == 'success'
            and recovery_job['id'] == c['job'] and recovery_job['run_id'] == c['run']
            and recovery_job['head_sha'] == c['source'] and recovery_job['name'] == RECOVERY_JOB_NAME
            and recovery_job['status'] == 'completed' and recovery_job['conclusion'] == 'success',
            'rust-thread-retained-recovery-origin')
    recovery_listing = api(f"actions/runs/{c['run']}/artifacts?per_page=100")
    require(recovery_listing['total_count'] == len(recovery_listing['artifacts']) == 1,
            'rust-thread-retained-recovery-single-artifact')
    item = recovery_listing['artifacts'][0]
    require(all(item.get(name) == value for name, value in c['artifact'].items())
            and item['name'] == RECOVERY_NAME and item['expired'] is False
            and item['workflow_run']['id'] == c['run']
            and item['workflow_run']['head_sha'] == c['source'],
            'rust-thread-retained-recovery-exact-artifact')
    return c['artifact'], '', 4, {'kind': 'separately-attributed-recovery-artifact',
        'run': c['run'], 'job': c['job'], 'source': c['source'], 'artifact': c['artifact']}


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
    artifact, prefix, expected_members, storage = storage_for(listing)
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and bool(token), 'rust-thread-retained-explicit-actions-token')
    request = urllib.request.Request(
        f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact["id"]}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'rust-thread-retained-artifact-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('rust-thread-retained-artifact-redirect-required')
    require(url.startswith('https://'), 'rust-thread-retained-artifact-https')
    remote = Ranges(url, artifact['size_in_bytes'])
    identities = {}
    with zipfile.ZipFile(remote) as archive:
        rows = archive.infolist()
        require(len(rows) == expected_members and len({row.filename.casefold() for row in rows}) == expected_members
                and (prefix != '' or {row.filename for row in rows} == set(PINS)),
                'rust-thread-retained-compiler-archive-index')
        # Only these four names can be extracted; all are fixed by the independently
        # verified immutable compiler event. No executable from this archive runs.
        for name, (size, sha) in PINS.items():
            member = archive.getinfo(prefix + name)
            require(member.file_size == size and not member.is_dir()
                    and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG),
                    'rust-thread-retained-compiler-member-preflight')
        for name, (size, sha) in PINS.items():
            count = 0
            with archive.open(prefix + name) as stream, (output / name).open('xb') as destination:
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
        'storage': storage,
        'producerAttempt': 1, 'historicalArtifact': HISTORICAL_ARTIFACT,
        'earlierArtifact': EARLIER_ARTIFACT, 'previousArtifact': PREVIOUS_ARTIFACT,
        'priorArtifact': PRIOR_ARTIFACT, 'latestPreviousArtifact': LATEST_PREVIOUS_ARTIFACT,
        'cataloguePreviousArtifact': CATALOGUE_PREVIOUS_ARTIFACT,
        'archiveDigestVerification': 'official-storage-metadata-only-selected-members-hash-verified',
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
