"""Execute native ownership checks and fresh C project/binding conformance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from tools.c_guest.bindings import check_lock, generate
from tools.c_guest.compiler import Compiler, SDK, ROOT, CAPABILITIES, safe_output
from tools.c_guest.project import build, bindings
from tools.c_guest_authoring import create, TEMPLATES


def qualify(output: Path, update: bool = False) -> dict:
    output = safe_output(output)
    output.mkdir(parents=True)
    compiler = Compiler(output / 'tmp', 900)
    generated, lock = generate(compiler.run, SDK / 'wit', 'latent:c-guest/sdk@1.0.0', output / 'reference')
    check_lock(SDK / 'bindings.lock.json', lock, update=update)
    # The native test deliberately supplies import doubles, while compiling the
    # public helpers against generated (never handwritten) ABI declarations.
    cc = shutil.which('clang')
    if cc is None:
        raise ValueError('native C ownership qualification requires clang')
    executable = output / 'ownership'
    subprocess.run([cc, '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I', str(generated), '-I', str(SDK / 'include'),
        str(SDK / 'tests/ownership.c'), '-o', str(executable)], check=True, timeout=120)
    subprocess.run([str(executable)], check=True, timeout=30)
    capabilities = {}
    for name in CAPABILITIES:
        profile = ROOT / 'tools/toolchain-smoke/examples' / ('guest_' + name)
        document = json.loads((profile / 'profile.json').read_text())
        _, capability_lock = generate(compiler.run, profile, document['world'], output / ('binding-' + name))
        capabilities[name] = capability_lock
    check_lock(SDK / 'capabilities.lock.json', {'formatVersion': 1, 'capabilities': capabilities}, update=update)
    receipts = {}
    for name in TEMPLATES:
        project = output / ('project-' + name)
        create(project, name)
        actual = bindings(project, output / ('lock-' + name), update=True)
        check_lock(SDK / 'projects' / name / 'c-bindings.lock.json', actual, update=update)
        receipts[name] = build(project, output / ('build-' + name))
        print('PASS C project: ' + name, flush=True)
    result = {'formatVersion': 1, 'nativeOwnership': 'passed', 'projects': receipts}
    (output / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--update-bindings', action='store_true')
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, args.update_bindings), sort_keys=True))


if __name__ == '__main__':
    main()
