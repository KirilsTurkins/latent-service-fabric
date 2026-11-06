#!/usr/bin/env python3
"""Select a retained successful development Go qualification, without trusting its bytes."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, write_json

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
REPOSITORY_ID = 1337591365
WORKFLOW = '.github/workflows/go-guest.yml'
JOB = 'Go runtime and complete capsule qualification'
STEPS = ('Qualify editable projects, all SDK owners, enforced node and printed guide',
         'Retain successful and failed upstream observations')
SCHEMA = 'latent.go.cost-producer.v1'
SHA = re.compile(r'[0-9a-f]{40}\Z')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')
RELEVANT_PREFIXES = ('apps/', 'crates/', 'examples/', 'sdk/',
                     'wit/', 'schemas/', '.cargo/', 'tools/')
RELEVANT_FILES = (WORKFLOW, 'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml', 'LICENSE', 'NOTICE',
                  'docs/component-development/go-authoring.md')
# These are downstream consumer controls, not inputs to the normal Go producer.
CONSUMER_ONLY = frozenset(('tools/go_cost_producer.py', 'tools/qualify_go_runtime_costs.py',
                           'tools/go_runtime_cost_fixture.py', 'tools/go_runtime_cost_probe.py',
                           'tools/tests/test_go_runtime_costs.py',
                           'tools/ci/contracts/python/test_go_runtime_costs.py.json',
                           'tools/ci/contracts/workflows/go-runtime-cost-reference.yml/workflow.json',
                           'tools/ci/contracts/workflows/go-runtime-cost-reference.yml/jobs/live-cost.json'))


def positive_integer(value):
    return type(value) is int and 0 < value < 10**20


def github(path):
    result = subprocess.run(['gh', 'api', 'repos/' + REPOSITORY + '/' + path],
                            check=True, capture_output=True, timeout=60)
    require(len(result.stdout) <= 8 * 1024 * 1024, 'Go-cost-producer-api-byte-bound')
    value = json.loads(result.stdout)
    require(type(value) is dict, 'Go-cost-producer-api-object')
    return value


def page(data, key):
    rows = data.get(key)
    require(type(rows) is list and type(data.get('total_count')) is int
            and 0 <= data['total_count'] <= 100 and len(rows) == data['total_count'],
            'Go-cost-producer-complete-api-page')
    return rows


def validate_run(run, requested):
    require(type(run) is dict and run.get('id') == requested and positive_integer(requested)
            and run.get('path') == WORKFLOW and run.get('event') in ('push', 'workflow_dispatch')
            and run.get('head_branch') == 'development'
            and run.get('status') == 'completed' and run.get('conclusion') == 'success'
            and run.get('repository', {}).get('id') == REPOSITORY_ID
            and run.get('head_repository', {}).get('id') == REPOSITORY_ID
            and type(run.get('head_sha')) is str and SHA.fullmatch(run['head_sha']),
            'Go-cost-producer-successful-development-run-required')


def validate_metadata(run, jobs, artifacts, requested, *, allow_expired=False):
    validate_run(run, requested)
    matching_jobs = [job for job in page(jobs, 'jobs') if job.get('name') == JOB]
    require(len(matching_jobs) == 1, 'Go-cost-producer-unique-owner-job')
    job = matching_jobs[0]
    require(positive_integer(job.get('id')) and job.get('run_id') == requested
            and job.get('head_sha') == run['head_sha'] and job.get('status') == 'completed'
            and job.get('conclusion') == 'success', 'Go-cost-producer-successful-owner-job')
    steps = job.get('steps')
    require(type(steps) is list and len(steps) <= 200, 'Go-cost-producer-step-bound')
    for name in STEPS:
        matches = [step for step in steps if step.get('name') == name]
        require(len(matches) == 1 and matches[0].get('status') == 'completed'
                and matches[0].get('conclusion') == 'success', 'Go-cost-producer-successful-owner-step')
    name = 'go-guest-upstream-' + run['head_sha']
    matching_artifacts = [artifact for artifact in page(artifacts, 'artifacts') if artifact.get('name') == name]
    require(len(matching_artifacts) <= 1, 'Go-cost-producer-unique-artifact')
    if not matching_artifacts or matching_artifacts[0].get('expired') is True:
        require(allow_expired, 'Go-cost-producer-artifact-unavailable')
        return None
    artifact = matching_artifacts[0]
    origin = artifact.get('workflow_run', {})
    require(artifact.get('expired') is False and positive_integer(artifact.get('id'))
            and type(artifact.get('size_in_bytes')) is int and 0 < artifact['size_in_bytes'] <= 1024**3
            and type(artifact.get('digest')) is str and DIGEST.fullmatch(artifact['digest'])
            and origin.get('id') == requested and origin.get('head_sha') == run['head_sha']
            and origin.get('head_branch') == 'development' and origin.get('repository_id') == REPOSITORY_ID
            and origin.get('head_repository_id') == REPOSITORY_ID, 'Go-cost-producer-authenticated-artifact')
    return {'schemaVersion': SCHEMA, 'repository': REPOSITORY, 'workflow': WORKFLOW,
            'runId': requested, 'headSha': run['head_sha'], 'jobId': job['id'],
            'artifactId': artifact['id'], 'artifactName': name, 'artifactDigest': artifact['digest'],
            'artifactBytes': artifact['size_in_bytes']}


def relevant(path):
    require(type(path) is str and path and not path.startswith('/') and '..' not in path.split('/'),
            'Go-cost-producer-comparison-path')
    if path in CONSUMER_ONLY:
        return False
    return path in RELEVANT_FILES or path.startswith(RELEVANT_PREFIXES)


def validate_comparison(comparison, producer_head, consumer_head):
    files = comparison.get('files')
    commits = comparison.get('commits')
    ahead = comparison.get('ahead_by')
    behind = comparison.get('behind_by')
    total = comparison.get('total_commits')
    require(comparison.get('base_commit', {}).get('sha') == producer_head
            and comparison.get('merge_base_commit', {}).get('sha') == producer_head
            and type(ahead) is int and type(behind) is int and type(total) is int
            and behind == 0 and 0 <= ahead == total <= 100
            and type(commits) is list and len(commits) == total
            and all(type(commit) is dict and type(commit.get('sha')) is str
                    and SHA.fullmatch(commit['sha']) for commit in commits)
            and ((comparison.get('status') == 'identical' and producer_head == consumer_head
                  and total == 0)
                 or (comparison.get('status') == 'ahead' and producer_head != consumer_head
                     and total > 0 and commits[-1]['sha'] == consumer_head))
            and type(files) is list and len(files) < 300,
            'Go-cost-producer-incomplete-or-nonancestor-comparison')
    for row in files:
        require(type(row) is dict and not relevant(row.get('filename')), 'Go-cost-producer-source-changed')
        if 'previous_filename' in row:
            require(not relevant(row['previous_filename']), 'Go-cost-producer-source-renamed')
    return {'consumerHead': consumer_head, 'relevantChangedFiles': 0,
            'comparisonFiles': len(files), 'comparisonFileLimit': 299,
            'comparisonCommits': total, 'comparisonCommitLimit': 100}


def current_head():
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, check=True,
                          capture_output=True, timeout=30).stdout.decode('ascii').strip()
    require(SHA.fullmatch(head), 'Go-cost-producer-consumer-head')
    changes = subprocess.run(['git', 'diff', '--name-only', '--no-renames', '-z', 'HEAD'], cwd=ROOT,
                             check=True, capture_output=True, timeout=30).stdout
    require(all(not relevant(name.decode('utf-8')) for name in changes.split(b'\0') if name),
            'Go-cost-producer-uncommitted-source')
    scope = [prefix.rstrip('/') for prefix in RELEVANT_PREFIXES] + list(RELEVANT_FILES)
    for options in (['--exclude-standard'], ['--ignored', '--exclude-standard']):
        untracked = subprocess.run(['git', 'ls-files', '--others', *options, '-z', '--', *scope],
                                   cwd=ROOT, check=True, capture_output=True, timeout=30).stdout
        require(len(untracked) <= 64 * 1024 * 1024
                and all(not relevant(name.decode('utf-8')) for name in untracked.split(b'\0') if name),
                'Go-cost-producer-untracked-source')
    return head


def bind_source(receipt, api=github):
    head = current_head()
    comparison = api('compare/' + receipt['headSha'] + '...' + head + '?per_page=100')
    binding = validate_comparison(comparison, receipt['headSha'], head)
    recipe = api('contents/' + WORKFLOW + '?ref=' + receipt['headSha'])
    require(recipe.get('type') == 'file' and recipe.get('path') == WORKFLOW
            and recipe.get('encoding') == 'base64' and type(recipe.get('size')) is int
            and 0 < recipe['size'] <= 1024 * 1024 and type(recipe.get('content')) is str,
            'Go-cost-producer-recipe-metadata')
    upstream = base64.b64decode(recipe['content'].replace('\n', ''), validate=True)
    local = (ROOT / WORKFLOW).read_bytes()
    require(len(upstream) == recipe['size'] and upstream == local,
            'Go-cost-producer-recipe-changed')
    receipt.update(sourceComparison=binding, workflowSha256=hashlib.sha256(upstream).hexdigest())
    return receipt


def select(run_id='', api=github):
    require(type(run_id) is str and (not run_id or re.fullmatch(r'[1-9][0-9]{0,19}', run_id)),
            'Go-cost-producer-run-id')
    if run_id:
        candidates = [int(run_id)]
    else:
        listing = api('actions/workflows/go-guest.yml/runs?branch=development&event=push&status=success&per_page=20')
        rows = listing.get('workflow_runs')
        require(type(rows) is list and len(rows) <= 20, 'Go-cost-producer-run-list-bound')
        candidates = [row.get('id') for row in rows]
    for candidate in candidates:
        require(positive_integer(candidate), 'Go-cost-producer-listed-run-id')
        run = api('actions/runs/' + str(candidate))
        # Do not fall back on malformed or unsuccessful metadata. Only an absent
        # or expired artifact is a normal reason to try another successful run.
        validate_run(run, candidate)
        artifacts = api('actions/runs/' + str(candidate) + '/artifacts?per_page=100')
        jobs = api('actions/runs/' + str(candidate) + '/jobs?per_page=100')
        receipt = validate_metadata(run, jobs, artifacts, candidate, allow_expired=not run_id)
        if receipt is not None:
            return bind_source(receipt, api)
    raise RuntimeError('Go-cost-producer-no-retained-successful-development-run')


def validate_receipt(value):
    require(type(value) is dict and set(value) == {'schemaVersion', 'repository', 'workflow', 'runId',
            'headSha', 'jobId', 'artifactId', 'artifactName', 'artifactDigest', 'artifactBytes',
            'sourceComparison', 'workflowSha256'}
            and value['schemaVersion'] == SCHEMA and value['repository'] == REPOSITORY
            and value['workflow'] == WORKFLOW and all(positive_integer(value[key])
                for key in ('runId', 'jobId', 'artifactId', 'artifactBytes'))
            and value['artifactBytes'] <= 1024**3 and type(value['headSha']) is str
            and SHA.fullmatch(value['headSha']) and value['artifactName'] == 'go-guest-upstream-' + value['headSha']
            and type(value['artifactDigest']) is str and DIGEST.fullmatch(value['artifactDigest'])
            and value['workflowSha256'] == hashlib.sha256((ROOT / WORKFLOW).read_bytes()).hexdigest()
            and type(value['sourceComparison']) is dict
            and set(value['sourceComparison']) == {'consumerHead', 'relevantChangedFiles', 'comparisonFiles',
                                                   'comparisonFileLimit', 'comparisonCommits', 'comparisonCommitLimit'}
            and type(value['sourceComparison']['consumerHead']) is str
            and SHA.fullmatch(value['sourceComparison']['consumerHead'])
            and value['sourceComparison']['consumerHead'] == current_head()
            and value['sourceComparison']['relevantChangedFiles'] == 0
            and type(value['sourceComparison']['comparisonFiles']) is int
            and 0 <= value['sourceComparison']['comparisonFiles'] <= 299
            and value['sourceComparison']['comparisonFileLimit'] == 299
            and type(value['sourceComparison']['comparisonCommits']) is int
            and 0 <= value['sourceComparison']['comparisonCommits'] <= 100
            and value['sourceComparison']['comparisonCommitLimit'] == 100
            and ((value['headSha'] == value['sourceComparison']['consumerHead'])
                 == (value['sourceComparison']['comparisonCommits'] == 0)),
            'Go-cost-producer-receipt')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', default='')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--github-output', type=Path, required=True)
    args = parser.parse_args()
    receipt = validate_receipt(select(args.run_id))
    write_json(args.output, receipt)
    with args.github_output.open('a', encoding='utf-8') as output:
        output.write('run_id=' + str(receipt['runId']) + '\n')
        output.write('artifact_id=' + str(receipt['artifactId']) + '\n')


if __name__ == '__main__':
    main()
