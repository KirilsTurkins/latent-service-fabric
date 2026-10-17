#!/usr/bin/env python3
"""Compile the finite typed-HTTP context fixture with the maintained Go owner.

This receipt deliberately records compile-only qualification. Signed pending
I/O, context races and default net/http/library qualification remain separate.
"""
import argparse
import json
import os
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.go_guest.activation import INITIALIZER_PROFILE
from tools.go_guest.compiler import Compiler
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json
from tools.stage_runtime_wit import stage

RECIPE = ('tools/qualify_go_http_context.py', 'tools/go_guest/compiler.py', 'tools/go_guest/runtime.py',
          'tools/go_guest/sdk.py', 'tools/go_guest/activation.py', 'tools/go_guest/checkpoints.py',
          'tools/go_guest/timers.py', 'tools/go_guest/initializers.py', 'tools/go_guest/http_context.py', 'tools/go_guest/http.py')


def qualify(output: Path, *, fixture_name='http-context-conformance'):
    if fixture_name not in {'http-context-conformance', 'standard-http-conformance'}:
        raise ValueError('unsupported-Go-HTTP-compile-fixture')
    output = fresh(output)
    fixture = ROOT / 'sdk/go-guest/runtime' / fixture_name
    source = snapshot(fixture)
    sdk_before = inventory(snapshot(ROOT / 'sdk/go-guest'))
    recipe_before = inventory({name: read_file(ROOT / name) for name in RECIPE})
    record = {'schemaVersion': 'latent.go.http-context.compile.v1', 'status': 'in-progress',
        'profile': INITIALIZER_PROFILE, 'qualification': 'compile-only', 'signedExecution': 'not-run',
        'defaultNetHttpQualification': False, 'sourceDigest': digest(inventory(source)),
        'fixture': fixture_name,
        'sdkDigest': digest(sdk_before), 'recipeDigest': digest(recipe_before),
        'commandLimits': {'overallSeconds': 900, 'perCommandSeconds': 600}}
    (output / 'recipe-inputs.json').write_bytes(recipe_before)
    try:
        (output / 'src').mkdir()
        (output / 'src/main.go').write_bytes(source['main.go'])
        for name in ('go.mod', 'go.sum'):
            (output / name).write_bytes(read_file(ROOT / 'sdk/go-guest/runtime-deps' / name))
        stage(output / 'wit', fixture)
        commands = Commands(output, output, dict(os.environ), deadline_seconds=900, command_seconds=600)
        compiler = Compiler(output / 'compiler', ROOT / 'sdk/go-guest', commands, runtime_profile=INITIALIZER_PROFILE)
        world = 'tests:go-standard-http/service@1.0.0' if fixture_name == 'standard-http-conformance' else 'tests:go-http-context/service@1.0.0'
        component, bindings = compiler.compile(output / 'src', output / 'wit',
            world, output / 'build', runtime_profile=INITIALIZER_PROFILE)
        compiler.check_unchanged()
        if (source != snapshot(fixture) or sdk_before != inventory(snapshot(ROOT / 'sdk/go-guest'))
                or recipe_before != inventory({name: read_file(ROOT / name) for name in RECIPE})):
            raise ValueError('go-http-context-captured-source-changed')
        record.update(status='passed', componentDigest=digest(read_file(component, 64*1024*1024)),
            bindingDigest=digest(json.dumps(bindings, sort_keys=True).encode()), tools=compiler.materials)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException:
        record['status'] = 'failed'
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', choices=('http-context-conformance', 'standard-http-conformance'), default='http-context-conformance')
    args = parser.parse_args()
    print(json.dumps(qualify(args.output.resolve(), fixture_name=args.fixture)))
