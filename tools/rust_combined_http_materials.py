"""Retrieve exact members from the source-captured corrected compiler job.

The selected compiler job and workflow passed. Historical failed compiler and
signed observations retain their own identities and are not relabelled.
"""
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
from tools.rust_thread_http_combined_package import SOURCE, RUN, JOB, ARTIFACT, PINS, ORIGIN

ARCHIVE = ORIGIN['archive']
PREFIX = ORIGIN['archivePrefix']


def prepare(output: Path) -> dict:
    run, job = api(f'actions/runs/{RUN}'), api(f'actions/jobs/{JOB}')
    require(run['id'] == RUN and run['path'] == ORIGIN['workflowPath']
            and run['event'] == 'push' and run['head_sha'] == ORIGIN['workflowSource']
            and run['run_attempt'] == 1 and run['head_branch'] == ORIGIN['workflowBranch']
            and run['status'] == 'completed' and run['conclusion'] == ORIGIN['workflowConclusion']
            and job['id'] == JOB and job['run_id'] == RUN
            and job['head_sha'] == ORIGIN['workflowSource'] and job['name'] == ORIGIN['jobName']
            and job['status'] == 'completed' and job['conclusion'] == ORIGIN['producerJobConclusion'],
            'rust-combined-exact-compiler-job-identity')
    artifact = api(f'actions/artifacts/{ARTIFACT}')
    require(all(artifact.get(name) == value for name, value in ARCHIVE.items())
            and artifact['name'] == ORIGIN['artifactName']
            and artifact['expired'] is False and artifact['workflow_run']['id'] == RUN
            and artifact['workflow_run']['head_sha'] == ORIGIN['workflowSource']
            and artifact['workflow_run']['repository_id'] == artifact['workflow_run']['head_repository_id'] == 1337591365,
            'rust-combined-exact-compiler-artifact')
    output = fresh(output)
    token = os.environ.get('GH_TOKEN')
    require(type(token) is str and bool(token), 'rust-combined-explicit-actions-token')
    request = urllib.request.Request(f'https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{ARTIFACT}/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'rust-combined-artifact-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('rust-combined-artifact-redirect-required')
    require(url.startswith('https://'), 'rust-combined-artifact-https')
    remote = Ranges(url, ARCHIVE['size_in_bytes'])
    identities = {}
    with zipfile.ZipFile(remote) as archive:
        rows = archive.infolist()
        require(len(rows) == ORIGIN['archiveMembers']
                and len({row.filename.casefold() for row in rows}) == len(rows),
                'rust-combined-original-archive-index')
        for name, (size, _sha) in PINS.items():
            member = archive.getinfo(PREFIX + name)
            require(member.file_size == size and not member.is_dir()
                    and stat.S_IFMT(member.external_attr >> 16) in (0, stat.S_IFREG),
                    'rust-combined-original-member-preflight')
        for name, (size, sha) in PINS.items():
            count = 0
            with archive.open(PREFIX + name) as stream, (output / name).open('xb') as destination:
                while data := stream.read(8 * 1024 * 1024):
                    count += len(data)
                    require(count <= size, 'rust-combined-original-member-bound')
                    destination.write(data)
            actual = file_identity(output / name, 32 * 1024 * 1024)
            require(count == size and actual == {'bytes': size, 'sha256': 'sha256:' + sha},
                    'rust-combined-original-member-identity')
            identities[name] = actual
    record = {'schemaVersion': 'latent.rust.combined-http.retained-compiler.v1', 'source': SOURCE,
        'run': RUN, 'job': JOB, 'artifact': ARCHIVE, 'producerConclusion': ORIGIN['producerJobConclusion'],
        'workflowSource': ORIGIN['workflowSource'], 'workflowConclusion': ORIGIN['workflowConclusion'],
        'archiveDigestVerification': 'official-metadata-only-selected-members-hash-verified',
        'wholeArchiveRetained': False, 'selected': identities, 'rangeBytes': remote.transferred,
        'rangeRequests': remote.requests, 'applicationRecompiled': True, 'applicationRecompiledDuringRetrieval': False,
        'originalCompilerReceiptRewritten': False, 'actualGuestExecuted': False}
    write_json(output / 'retrieval.json', record)
    return record


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
