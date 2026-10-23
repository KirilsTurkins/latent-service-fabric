"""Acquire only the frozen successful source splicer for borrow controls.

No old engine, native host, SDK diagnostic, library or qualification is acquired.
The successful owning job remains distinct from its cancelled aggregate run.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_replay_materials import api, NoRedirect
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, fresh, write_json
from tools.typescript_guest.native_build import source_splicer
from tools.typescript_tracking_replay_inputs import RUN, HEAD, SOURCE, PARENTS, SPECS, owning, unpack


def prepare(output: Path) -> dict:
    output = output.resolve()
    require(output != ROOT and ROOT not in output.parents, 'borrow-splicer-independent-output')
    output = fresh(output)
    commit = api('git/commits/' + SOURCE)
    require(commit['sha'] == SOURCE and tuple(row['sha'] for row in commit['parents']) == PARENTS,
            'borrow-splicer-original-source-commit')
    identity, size, _sha, job, _name = SPECS['splicer']
    run = api('actions/runs/' + str(RUN))
    artifact = api('actions/artifacts/' + str(identity))
    owning(run, api('actions/jobs/' + str(job)), artifact, 'splicer')
    token = os.environ.get('GH_TOKEN')
    require(isinstance(token, str) and 0 < len(token) <= 4096, 'borrow-splicer-read-token')
    request = urllib.request.Request(
        'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/' + str(identity) + '/zip',
        headers={'Authorization': 'Bearer ' + token})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'borrow-splicer-artifact-redirect')
        location = error.headers['Location']
    else:
        raise ValueError('borrow-splicer-artifact-redirect-required')
    parsed = urllib.parse.urlsplit(location)
    require(parsed.scheme == 'https' and parsed.username is None and parsed.hostname is not None
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'borrow-splicer-artifact-origin')
    with urllib.request.urlopen(location, timeout=90) as response:
        raw = response.read(size + 1)
    members = unpack(raw, 'splicer', output / 'splicer')
    (output / 'splicer.zip').write_bytes(raw)
    # Run the unchanged normal source/SDK/recipe validator before any fresh
    # library/engine work. No receipt or source digest is rewritten for reuse.
    validated = source_splicer(output / 'splicer')
    value = {'schemaVersion': 'latent.typescript.borrow-splicer-input.v1',
             'source': SOURCE, 'run': RUN, 'head': HEAD, 'artifact': identity,
             'archiveBytes': size, 'archiveDigest': artifact['digest'], 'owningJob': job,
             'owningConclusion': 'success', 'aggregateConclusion': 'cancelled',
             'members': members, 'validated': validated, 'credentialsRetained': False,
             'engineAcquired': False, 'nativeHostAcquired': False, 'qualification': 'unknown'}
    write_json(output / 'acquisition.json', value)
    return value


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args().output)))
