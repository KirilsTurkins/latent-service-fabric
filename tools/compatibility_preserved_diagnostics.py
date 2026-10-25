"""Current passive diagnostics on three fixed prior executions; never a guest run.

The caller must first authenticate the exact immutable archives. Original
reports, build owners, runtime receipts and qualified.json are never rewritten.
Only a fresh diagnostic copy receives the two current derived sidecars.
"""
from pathlib import Path
import json
import re
import sys
import time

from tools import guest_api_analysis as api, guest_compatibility as compatibility
from tools import guest_compatibility_context as context, guest_emitted_code as emitted
from tools.build_observation import build_environment
from tools.dev_workflow.common import digest, require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, canonical, fresh, read_file, write_json

CELLS = ('java', 'typescript', 'go-queues')
CODE = ('tools/compatibility_preserved_diagnostics.py', 'tools/guest_api_analysis.py',
    'tools/guest_compatibility.py', 'tools/guest_compatibility_context.py',
    'tools/guest_compiler_capture.py', 'tools/guest_compiler_edges.py',
    'tools/guest_emitted_code.py', 'tools/java_guest/reachability.py')


def diagnose(source, output, *, cell, source_commit):
    require(cell in CELLS and type(source_commit) is str
        and re.fullmatch('[0-9a-f]{40}', source_commit), 'preserved-diagnostic-closed-source-cell')
    source = Path(source).resolve(strict=True); output = Path(output).absolute()
    require(source.is_dir() and not source.is_symlink() and output != source
        and output not in source.parents and source not in output.parents,
        'preserved-diagnostic-separated-copy')
    output = fresh(output); total = 0; original_files = {}
    # Only direct public JSON metadata plus the original component are needed.
    # No package, compiler, tool, source workspace or executable is copied/run.
    entries = sorted(source.iterdir(), key=lambda path: path.name)
    require(len(entries) <= 128, 'preserved-diagnostic-file-count')
    for path in entries:
        require(not path.is_symlink(), 'preserved-diagnostic-no-link')
        if path.is_dir(): continue
        require(path.is_file(), 'preserved-diagnostic-regular')
        if path.suffix != '.json' and path.name != 'component.wasm': continue
        raw = read_file(path, 64 * 1024**2); total += len(raw)
        require(total <= 128 * 1024**2, 'preserved-diagnostic-copy-bound')
        original_files[path.name] = {'bytes': len(raw), 'sha256': digest(raw)}
        (output / path.name).write_bytes(raw)
    report = compatibility.read(read_file(output / 'compatibility-report.json', 65536))
    selected = context.read(read_file(output / 'compatibility-context.json', 65536), report=report)
    require(report['language'] == ('go' if cell == 'go-queues' else cell),
        'preserved-diagnostic-original-language')
    # Authenticate original owner/material references before deriving anything.
    old, compiler, owner, build_raw, component = api.inputs(output, report, selected)
    old_api = api.validate(json.loads(read_file(output / api.NAME, api.MAX_BYTES)))
    current = emitted.analyze(component, report['sourceDigest'], old['runtimeProfile'],
        report['runtimeProfile'], graph_digest=old['graphDigest'], recipe_digest=old['recipeDigest'])
    projection = api.create(report, selected, current, build_observation=build_raw,
        component=component, compiler_records=compiler, owner_records=owner)
    (output / 'compatibility-reachability.json').write_bytes(canonical(current))
    (output / api.NAME).write_bytes(canonical(projection))
    api.read(read_file(output / api.NAME, api.MAX_BYTES), output, report, selected)
    # The same ordinary sanitized CLI is exercised, with no analysis selector.
    started = time.monotonic()
    commands = Commands(ROOT, fresh(output / 'diagnostic-commands'), build_environment(output),
        deadline_seconds=120, command_seconds=30)
    commands.deadline = min(commands.deadline, started + 115)  # existing cleanup within 120s
    raw = commands.run('preserved-current-default-presentation', sys.executable, '-B',
        ROOT / 'tools/guest_compatibility.py', output / 'compatibility-report.json')
    require(b'API implementation observations;' in raw and len(raw) <= 1024**2,
        'preserved-diagnostic-default-presentation')
    for name, identity in original_files.items():
        require(file_identity(source / name, 64 * 1024**2) == identity,
            'preserved-diagnostic-original-mutated')
    result = {'cell': cell, 'sourceCommit': source_commit,
        'scope': 'current-passive-diagnostics-on-original-component-and-owner-inputs',
        'component': file_identity(source / 'component.wasm', 64 * 1024**2),
        'originalAPIIdentity': old_api['identity'], 'originalRootIdentity': old['identity'],
        'currentAPI': projection, 'currentRootIdentity': current['identity'],
        'diagnosticCode': {name: file_identity(ROOT / name, 1024**2) for name in CODE},
        'defaultPresentation': {'bytes': len(raw), 'sha256': digest(raw), 'explicitAnalysisSelector': False},
        'commands': commands.records, 'originalInputsUnchanged': True,
        'compilerInvocations': 0, 'guestInvocations': 0, 'originalRuntimeSourceRelabeled': False}
    write_json(output / 'DIAGNOSTIC-REANALYSIS.json', result)
    return result
