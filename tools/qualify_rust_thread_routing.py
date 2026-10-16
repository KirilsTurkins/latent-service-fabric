"""Authenticate bounded actual encoder graphs; no Rust/std/guest execution claim."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_process import run_bounded_result
from tools.dev_workflow.common import require

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ('tools/qualify_rust_thread_routing.py',
          'sdk/rust-standard-runtime/routing-fixture/world.wit',
          'sdk/rust-standard-runtime/routing-fixture/core.wat',
          'sdk/rust-standard-runtime/routing-fixture/interface.wit',
          'sdk/rust-standard-runtime/stack-transform/src/lib.rs',
          'sdk/rust-standard-runtime/stack-transform/src/thread_entry.rs',
          'sdk/rust-standard-runtime/stack-transform/src/root.rs',
          'sdk/rust-standard-runtime/stack-transform/src/admission.rs',
          'sdk/rust-standard-runtime/stack-transform/src/component.rs',
          'sdk/rust-standard-runtime/stack-transform/src/main.rs',
          'sdk/rust-standard-runtime/stack-transform/Cargo.toml',
          'sdk/rust-standard-runtime/stack-transform/Cargo.lock',
          'wit/platform/native-runtime/package.wit', 'wit/platform/activation-runtime/package.wit')


def identity(path):
    with path.open('rb') as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    require(0 < len(raw) <= 32 * 1024 * 1024, 'rust-routing-file-bound')
    return {'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def replace(text, before, after):
    require(text.count(before) == 1, 'rust-routing-encoder-preimage-drift')
    return text.replace(before, after, 1)


def append(text, body):
    require(text.endswith(')\n'), 'rust-routing-component-text-shape')
    return text[:-2] + body + '\n)\n'


def negatives(text):
    raw = re.findall(r'\(core func (\$"[^"]+") \(@name "thread.new-indirect"\)', text)
    require(len(raw) == 1, 'rust-routing-raw-creator-name')
    lift_type = '\n  (type $leak-type (func (param "entry" u32) (param "context" u32) (result u32)))\n'
    def lift(function):
        return append(text, lift_type + f'  (func $leak (type $leak-type) (canon lift (core func {function})))\n  (export "leak" (func $leak))')
    # Every mutation is on a source-known encoder graph. Inputs must still pass
    # actual Wasm validation before a verifier rejection can count as a control.
    values = {
        'unbounded-main-table': (replace(text, '    (table (;0;) 1 1 funcref)',
                                         '    (table (;0;) 1 funcref)'),
                                 'rust-component-main-finite-original-table'),
        'modified-shim': (replace(text, '      call_indirect (type 0)', '      nop\n      call_indirect (type 0)'),
                          'rust-component-private-shim-body'),
        'raw-creator-lift': (lift(raw[0]), 'rust-component-raw-or-thunk-lift-escape'),
        'raw-thunk-lift': (lift('$thread.new-indirect'), 'rust-component-raw-or-thunk-lift-escape'),
        'private-table-container': (append(text, '\n  (core instance $table-leak (export "$imports" (table $"shim table")))'),
                                    'rust-component-private-raw-or-table-escape'),
        'reused-fixup': (append(text, '\n  (core instance $second-fixup (instantiate $wit-component-fixup (with "" (instance $fixup-args))))'),
                        'rust-component-creator-provider-or-instance-fence'),
        'second-creator': (append(text, '\n  (core func $second-creator (canon thread.new-indirect $thread-start $indirect-function-table))'),
                           'rust-component-duplicate-creation'),
        'parallel-spawn': (append(text, '\n  (core type $parallel-type (shared (func (param i32))))\n  (core func $parallel (canon thread.spawn-ref $parallel-type))'),
                           'rust-component-parallel-spawn-denied'),
        'extra-module': (append(text, '\n  (core module $unexpected-module)'),
                         'rust-component-finite-three-module-profile'),
        'dynamic-module-alias': (append(text, '''
  (type $dynamic-code-type (instance
    (core type $empty (module))
    (export "module" (core module (type $empty)))
  ))
  (import "untrusted-code" (instance $dynamic-code (type $dynamic-code-type)))
  (alias export $dynamic-code "module" (core module $untrusted-module))'''),
                                 'rust-component-dynamic-code-alias-denied'),
        'repeated-main': (append(text, '''
  (core instance $main-again (instantiate $main
    (with "$root" (instance $$root))
    (with "latent:runtime-native/threads@0.1.0" (instance $latent:runtime-native/threads@0.1.0))
  ))'''), 'rust-component-main-instantiated-twice'),
        'component-start': (append(text, '''
  (alias core export $main "noop" (core func $noop))
  (type $noop-type (func))
  (func $noop (type $noop-type) (canon lift (core func $noop)))
  (start $noop)'''), 'rust-component-start-before-owned-root-denied'),
    }
    private = replace(text, '    (table (;0;) 1 1 funcref)',
                      '    (import "private-shim" "$imports" (table 2 2 funcref))\n    (table 1 1 funcref)')
    private = replace(private, '      (with "$root" (instance $$root))',
                      '      (with "private-shim" (instance $wit-component-shim-instance))\n      (with "$root" (instance $$root))')
    values['main-private-table-import'] = (private, 'rust-component-main-nonfunction-import-denied')
    # This component function has the correct Native WIT shape but comes from
    # guest code. Merely trusting the import label or same signature is unsafe.
    fake = '''  (alias core export $main "fake-native" (core func $fake-native))
  (type $fake-native-result (result (error $error)))
  (type $fake-native-type (func (param "continuation" $token) (result $fake-native-result)))
  (func $fake-native-start (type $fake-native-type) (canon lift (core func $fake-native) (memory $memory)))
'''
    marker = re.findall(r'^  \(core func [^\n]+\(canon lower \(func \$start\)', text, re.M)
    require(len(marker) == 1, 'rust-routing-provider-lower-preimage')
    # Name the original later root type before inserting two new types; printed
    # numeric comments are annotations, but actual numeric type references shift.
    original_type = re.findall(r'^  \(type \(;(\d+);\) \(func \(result u32\)\)\)$', text, re.M)
    require(len(original_type) == 1, 'rust-routing-root-type-preimage')
    number = original_type[0]
    wrong = replace(text, f'  (type (;{number};) (func (result u32)))',
                    '  (type $ordinary-run-type (func (result u32)))')
    original_run = re.findall(r'^  \(func \$run [^\n]+\(type ' + number + r'\) \(canon lift', wrong, re.M)
    require(len(original_run) == 1, 'rust-routing-root-function-preimage')
    wrong = replace(wrong, original_run[0], original_run[0].replace(f'(type {number})', '(type $ordinary-run-type)'))
    wrong = replace(wrong, marker[0], fake + marker[0])
    wrong = replace(wrong, '(canon lower (func $start)', '(canon lower (func $fake-native-start)')
    values['guest-admission-provider'] = (wrong, 'rust-component-creator-provider-or-instance-fence')
    return values


def negative(command, output, transformer, wasm_tools, name, text, reason):
    path = output / (name + '.wat'); path.write_text(text, encoding='utf-8')
    binary = output / (name + '.wasm')
    command([wasm_tools, 'parse', path, '-o', binary])
    # A parser/validator error is a failed campaign, never a passing rejection.
    command([wasm_tools, 'validate', '--features', 'all', binary])
    command([transformer, 'verify-component', binary, output / (name + '-must-not-exist.json')], expect=reason)
    return {'case': name, 'status': 'rejected', 'wasmValidated': True, 'reason': reason, 'component': identity(binary)}


def run(output: Path, transformer: Path, wasm_tools: Path):
    require(not output.exists() and not output.is_symlink(), 'rust-routing-output-not-fresh')
    source = {name: identity(ROOT / name) for name in RECIPE}
    tools = {'transformer': identity(transformer), 'wasmTools': identity(wasm_tools)}
    output.mkdir(parents=True, mode=0o700)
    deadline = time.monotonic() + 180
    used = 0
    report = {'schemaVersion': 'latent.rust.thread-routing-source-gate.v1', 'status': 'failed',
        'source': source, 'tools': tools, 'cases': [], 'coreSource': 'explicit WAT encoder control',
        'rustOrStdExecuted': False, 'canonicalThreadCreationEnabled': False, 'standardRuntimeQualified': False}

    def command(argv, *, expect=None):
        nonlocal used
        remaining = deadline - time.monotonic()
        require(remaining > 0 and used < 2 * 1024 * 1024, 'rust-routing-command-budget')
        result = run_bounded_result([str(v) for v in argv], ROOT, os.environ, remaining, 2 * 1024 * 1024 - used)
        used += len(result.stdout) + len(result.stderr)
        if expect is None:
            require(result.returncode == 0, 'rust-routing-command-failed')
        else:
            require(result.returncode != 0 and expect.encode() in result.stderr, 'rust-routing-negative-not-enforced')
        return result.stdout

    try:
        require(command([wasm_tools, '--version']).strip() == b'wasm-tools 1.254.0', 'rust-routing-tool-version')
        wit = output / 'wit'; wit.mkdir()
        (wit / 'world.wit').write_bytes((ROOT / RECIPE[1]).read_bytes())
        for key, name in [('native', RECIPE[-2]), ('runtime', RECIPE[-1])]:
            path = wit / 'deps' / key / 'package.wit'; path.parent.mkdir(parents=True)
            path.write_bytes((ROOT / name).read_bytes())
        plain = output / 'plain.wasm'
        command([wasm_tools, 'parse', ROOT / RECIPE[2], '-o', plain])
        derived = output / 'derived'
        command([transformer, 'transform-core', plain, identity(plain)['digest'], derived])

        def component(core, prefix):
            embedded = output / (prefix + '-embedded.wasm'); result = output / (prefix + '.wasm')
            command([wasm_tools, 'component', 'embed', wit, core, '-o', embedded])
            command([wasm_tools, 'component', 'new', embedded, '-o', result])
            command([wasm_tools, 'validate', '--features', 'all', result])
            return result

        positive = component(derived / 'core.wasm', 'owned')
        receipt = output / 'routing.json'
        command([transformer, 'verify-component', positive, receipt])
        proof = json.loads(receipt.read_bytes())
        require(proof['componentDigest'] == identity(positive)['digest']
                and proof['componentRoutingAuthenticated'] is True
                and proof['canonicalCreationEnabled'] is False and proof['standardRuntimeQualified'] is False,
                'rust-routing-positive-proof-scope')
        report['cases'].append({'case': 'normal-encoder-owned-routing', 'status': 'passed', 'component': identity(positive)})
        # Normal interface exports introduce nested component wrappers. They
        # remain supported while nested executable modules/creators are closed.
        interface_wit = output / 'wit-interface'; interface_wit.mkdir()
        (interface_wit / 'world.wit').write_bytes((ROOT / RECIPE[3]).read_bytes())
        for key, name in [('native', RECIPE[-2]), ('runtime', RECIPE[-1])]:
            path = interface_wit / 'deps' / key / 'package.wit'; path.parent.mkdir(parents=True)
            path.write_bytes((ROOT / name).read_bytes())
        interface_source = output / 'interface-core.wat'
        interface_source.write_text(replace((ROOT / RECIPE[2]).read_text(), '(export "run")',
                                           '(export "run") (export "tests:owned/api@0.1.0#run")'), encoding='utf-8')
        interface_plain = output / 'interface-plain.wasm'
        command([wasm_tools, 'parse', interface_source, '-o', interface_plain])
        interface_derived = output / 'interface-derived'
        command([transformer, 'transform-core', interface_plain, identity(interface_plain)['digest'], interface_derived])
        interface_embedded = output / 'interface-embedded.wasm'; interface_component = output / 'interface.wasm'
        command([wasm_tools, 'component', 'embed', interface_wit, interface_derived / 'core.wasm', '-o', interface_embedded])
        command([wasm_tools, 'component', 'new', interface_embedded, '-o', interface_component])
        command([wasm_tools, 'validate', '--features', 'all', interface_component])
        command([transformer, 'verify-component', interface_component, output / 'interface-routing.json'])
        report['cases'].append({'case': 'normal-nested-interface-export', 'status': 'passed', 'component': identity(interface_component)})
        unwrapped = component(plain, 'unwrapped')
        command([transformer, 'verify-component', unwrapped, output / 'must-not-exist.json'],
                expect='rust-child-admission-fixed-body-mismatch')
        report['cases'].append({'case': 'unwrapped-main', 'status': 'rejected', 'component': identity(unwrapped)})
        wat = command([wasm_tools, 'print', positive]).decode('utf-8')
        for name, (text, reason) in negatives(wat).items():
            report['activeCase'] = name
            report['cases'].append(negative(command, output, transformer, wasm_tools, name, text, reason))
        report.pop('activeCase', None)
        require({name: identity(ROOT / name) for name in RECIPE} == source
                and {'transformer': identity(transformer), 'wasmTools': identity(wasm_tools)} == tools,
                'rust-routing-source-or-tool-mutated')
        report['status'] = 'passed'
        return report
    finally:
        (output / 'routing-gate.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--transformer', type=Path, required=True)
    parser.add_argument('--wasm-tools', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve(), args.transformer.resolve(), args.wasm_tools.resolve())
    print(json.dumps({'status': result['status'], 'cases': result['cases'],
        'qualification': 'actual encoder/source routing controls only; engine disabled'}))


if __name__ == '__main__':
    main()
