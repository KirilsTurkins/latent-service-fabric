#!/usr/bin/env python3
"""Strict pinned-compiler controls for AbortSignal event names; no guest execution."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.qualify_typescript_fetch_runtime import project
from tools.qualify_typescript_fetch_component import WORLD
from tools.rust_capsule_project import ROOT
from tools.typescript_guest.compiler import declaration_aliases


def run(argv: list[str], directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, cwd=directory, capture_output=True, text=True, timeout=30)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def check(tools: Path) -> dict:
    tools = tools.resolve(strict=True)
    node = shutil.which('node')
    require(node is not None, 'pinned-node-required')
    pins = json.loads((ROOT/'sdk/typescript-guest/tools/package.json').read_text())
    tsc = [node, str(tools/'node_modules/typescript/bin/tsc')]
    for argv, expected in (([node, '--version'], 'v'+pins['engines']['node']),
                           (tsc+['--version'], 'Version '+pins['dependencies']['typescript'])):
        result = run(argv, ROOT)
        require(result.returncode == 0 and result.stdout.strip() == expected,
                'pinned-compiler-version: '+result.stdout+result.stderr)
    observations = []
    with tempfile.TemporaryDirectory(prefix='lsf-abort-event-types-') as temporary:
        app = project(Path(temporary)/'application')
        generated = app/'generated'
        result = run([node, str(tools/'node_modules/@bytecodealliance/jco/dist/jco.js'),
                      'types', str(app/'wit'), '--world-name', WORLD, '--name', 'capsule',
                      '--out-dir', str(generated)], app)
        require(result.returncode == 0, 'original-wit-declarations: '+result.stdout+result.stderr)
        for path in generated.rglob('*.d.ts'):
            path.write_text(declaration_aliases(path.read_text()), encoding='utf-8')
        for name in ('runtime-globals.d.ts', 'clock-globals.d.ts', 'fetch-globals.d.ts'):
            (generated/name).write_bytes((ROOT/'sdk/typescript-guest/activation'/name).read_bytes())
        config = {'compilerOptions': {'target': 'ES2022', 'module': 'ESNext',
            'moduleResolution': 'Bundler', 'strict': True, 'noEmit': True,
            'lib': ['ES2022'], 'types': []}, 'include': ['src/**/*.ts', 'generated/**/*.d.ts']}
        (app/'tsconfig.json').write_text(json.dumps(config), encoding='utf-8')

        def compile_case(label: str, accepted: bool, error: str = 'TS2345') -> None:
            result = run(tsc+['--project', str(app/'tsconfig.json'), '--pretty', 'false'], app)
            output = result.stdout+result.stderr
            require(result.returncode == 0 if accepted else
                    result.returncode in (1, 2) and 'error '+error+':' in output,
                    label+': unexpected compiler outcome\n'+output)
            observations.append({'case': label, 'accepted': accepted})

        # Check the unchanged real signed programme, not a handwritten stand-in.
        compile_case('complete-signed-fetch-source', True)
        control = app/'src/event-types.ts'
        prefix = 'const signal = new AbortController().signal;\nconst listener = () => {};\n'
        control.write_text(prefix+"const name: string = 'fanout-fill';\n"
            "signal.addEventListener(name, listener, {once: true});\n"
            "signal.removeEventListener(name, listener);\n"
            "signal.addEventListener('abort', listener, false);\n"
            "signal.removeEventListener('abort', listener);\n", encoding='utf-8')
        compile_case('string-and-abort-names', True)
        for label, statement in (
                ('numeric-add-name', 'signal.addEventListener(42, listener);'),
                ('numeric-remove-name', 'signal.removeEventListener(42, listener);'),
                ('invalid-listener', "signal.addEventListener('custom', 42);"),
                ('invalid-once', "signal.addEventListener('custom', listener, {once: 'yes'});")):
            control.write_text(prefix+statement+'\n', encoding='utf-8')
            compile_case(label, False, 'TS2322' if label == 'invalid-once' else 'TS2345')
        control.unlink()
        declaration = generated/'runtime-globals.d.ts'
        original = declaration.read_text(encoding='utf-8')
        for method in ('addEventListener', 'removeEventListener'):
            before = method+'(type: string,'
            require(before in original, 'event-name-mutation-anchor: '+method)
            declaration.write_text(original.replace(before, method+"(type: 'abort',"), encoding='utf-8')
            compile_case('reject-abort-only-'+method, False)
        declaration.write_text(original, encoding='utf-8')
        compile_case('restored-signed-fetch-source', True)
    return {'status': 'passed', 'typescript': pins['dependencies']['typescript'],
            'checks': observations, 'signedExecution': 'not-run', 'physicalRetirement': 'not-proved'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.tools), sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
