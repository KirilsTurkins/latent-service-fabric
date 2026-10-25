"""One normal published Polly capture exercising original Task.WaitAll APIs."""
from pathlib import Path

from tools import application_dependencies as inputs, dotnet_dependency_authoring as authoring
from tools import dotnet_published_task_fixture as published
from tools.build_observation import build_environment
from tools.dotnet_application_dependencies import resolve
from tools.dotnet_guest.compiler import Compiler
from tools.phase2_operator_process import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, read_file

LIBRARY = 'tools/fixtures/dotnet-aggregate-task-waits/PublishedTasks.cs'
PREFIX = 'published:'
CASES = ('waitall-two-incomplete', 'waitall-reverse-completion', 'waitall-polly-multiple-errors',
    'waitall-task-own-cancellation', 'waitall-entry-token-precedence', 'waitall-later-wait-cancel',
    'waitall-one-finite-deadline', 'waitall-zero-query', 'waitall-nested-single', 'waitall-nested-aggregate')
FRESH = CASES[0]
ORIGINALS = {
    'polly/8.6.3': {'digest': 'sha256:922a22762e8f2968147bbba3fab4fc93907a13bae8da220ca3ad1c2eb68524bd', 'size': 766807},
    'polly.core/8.6.3': {'digest': 'sha256:e972912ebc10f2760bc14361c3cfbfe59e84bdf20b860b9bd939fa07a5d2c48c', 'size': 826595}}
ASSETS = {'polly/8.6.3': 'lib/net6.0/Polly.dll', 'polly.core/8.6.3': 'lib/net8.0/Polly.Core.dll'}


def expected(mode):
    require(mode in CASES, 'dotnet-aggregate-wait-unknown-case')
    return 'aggregate-task-wait:'+mode+'|original-results-observed'


def prepare(output: Path, outside: Path, tools: Path):
    app = published.application(output)
    source = read_file(ROOT/LIBRARY)
    (app/'src/PublishedTasks.cs').write_bytes(source)
    sdk = (app/'sdk-lock.json').read_bytes()
    outside.mkdir(mode=0o700)
    (outside/'capture-evidence').mkdir(mode=0o700)
    commands = Commands(app, outside/'capture-evidence', build_environment(outside))
    compiler = Compiler(tools, commands, app/'vendor/lsf', offline=True, captured=True)
    candidate = app/'target/published-task-candidate.json'
    candidate.parent.mkdir(exist_ok=True)
    lock = resolve(app, candidate, dotnet=compiler.dotnet, tools=tools)
    rows = published.selected(lock)
    require({name: row['original'] for name, row in rows.items()} == ORIGINALS,
        'dotnet-aggregate-original-published-archives')
    for name, row in rows.items():
        expected_assets = {ASSETS[name]: {'related': '.pdb;.xml'}}
        require(row['metadata']['targets'] == {target: {'compile': expected_assets, 'runtime': expected_assets}
            for target in ('net10.0', 'net10.0/wasi-wasm')}, 'dotnet-aggregate-exact-published-assets')
    require(authoring.review(app, candidate, digest(candidate.read_bytes()))['status'] == 'reviewed'
        and authoring.status(app)['status'] == 'verified' and (app/'sdk-lock.json').read_bytes() == sdk,
        'dotnet-aggregate-normal-reviewed-capture')
    compiler.check_unchanged()
    require(published.selected(inputs.verify_inputs(app, 'dotnet').lock) == rows,
        'dotnet-aggregate-accepted-published-closure')
    return app, {'schemaVersion': 'latent.dotnet.aggregate-task-waits.fixture.v1',
        'packages': {name: {'original': row['original'], 'dependencies': row['dependencies'],
            'metadata': row['metadata']} for name, row in rows.items()},
        'sdkLockDigest': digest(sdk), 'sourceDigest': digest(source),
        'acceptedLockDigest': digest((app/inputs.LOCK).read_bytes()),
        'normalResolverWorkspaceEphemeral': True, 'applicationSchedulerReplacement': False,
        'httpDeclaration': False, 'cases': list(CASES)}
