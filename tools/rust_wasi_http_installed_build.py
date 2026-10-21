"""Exercise the installed maintained Rust recipe without a checkout import.

The controller runs this file in a network-none namespace with only the staged
payload, captured application and owned work directory. This is the ordinary
installed compiler entry, not the released frontend archive or its watch loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def identity(path):
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': 'sha256:' + value, 'bytes': path.stat().st_size}


def namespace_command(sandbox, payload, capture, work, control, source, inventory_digest):
    """Expose installed inputs and host loader utilities, never a checkout tree."""
    require(re.fullmatch('[0-9a-f]{40}', source)
        and re.fullmatch('sha256:[0-9a-f]{64}', inventory_digest), 'installed-rust-namespace-selection')
    require(control.parent == work and all(path.is_absolute() for path in (payload, capture, work, control))
        and len({payload, capture, work}) == 3
        and all(a not in b.parents for a in (payload, capture, work)
            for b in (payload, capture, work) if a != b), 'installed-rust-namespace-owned-inputs')
    result = [str(sandbox), '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
        '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/home']
    for name in ('/usr', '/lib', '/lib64', '/bin'):
        if Path(name).exists():
            result += ['--ro-bind', name, name]
    result += ['--ro-bind', str(payload), str(payload), '--ro-bind', str(capture), str(capture),
        '--bind', str(work), str(work), '--ro-bind', str(control), str(control),
        '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
        '--setenv', 'HOME', '/home', '--chdir', str(work), '--', str(payload/'sdk/bin/python'),
        '-I', '-B', str(control), '--payload', str(payload), '--capture', str(capture),
        '--work', str(work), '--source', source, '--inventory-sha256', inventory_digest]
    return result


def request(denied, application, canonical, digest):
    failed = json.loads((denied/'BUILD-FAILED.json').read_bytes())
    value = json.loads((denied/'executable-input-approval-request.json').read_bytes())
    locked = json.loads((application/'latent.dependencies.lock.json').read_bytes())
    executable = [row for row in locked['artifacts'] if row['role'] == 'build-tool']
    spec = value['specification']
    require(failed['stage'] == 'executable-input-approval'
        and not any(row['stage'] == 'compile' for row in failed['commands'])
        and not (denied/'BUILD-COMPLETE.json').exists(), 'installed-rust-unapproved-before-compile')
    require(type(value['formatVersion']) is int and value['formatVersion'] == 1
        and value['identity'] == digest(canonical(spec)) and len(executable) == 16
        and spec['executableInputs'] == executable and spec['network'] == 'denied'
        and spec['ambientHome'] == 'absent' and spec['credentials'] == 'not-inherited'
        and spec['isolationProfile'] == 'linux-captured-compiler-namespaces-v1',
        'installed-rust-exact-normal-executable-review')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('payload', 'capture', 'work'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--inventory-sha256', required=True)
    parser.add_argument('--source', required=True)
    args = parser.parse_args(argv)
    require(sys.platform == 'linux' and re.fullmatch('[0-9a-f]{40}', args.source)
        and re.fullmatch('sha256:[0-9a-f]{64}', args.inventory_sha256), 'installed-rust-exact-selection')
    payload, capture, work = (path.resolve(strict=True) for path in (args.payload, args.capture, args.work))
    require(len({payload, capture, work}) == 3 and all(a not in b.parents
        for a in (payload, capture, work) for b in (payload, capture, work) if a != b),
        'installed-rust-disjoint-owned-paths')
    require(identity(payload/'guest-tools.json')['sha256'] == args.inventory_sha256,
        'installed-rust-exact-inventory-selection')
    # -I removes ambient Python paths. Only the readonly installed recipe is
    # added; the checkout is not mounted by the owning controller.
    sys.path.insert(0, str(payload/'recipe'))
    from tools.build_process import run_bounded_result
    from tools.dev_workflow import tool_inventory
    from tools.dev_workflow.common import HOST_ABI
    from tools.rust_capsule_project import canonical, digest, inventory, snapshot
    descriptor = {'language': 'rust', 'hostAbi': HOST_ABI,
        'template': {'ownerIssue': 544, 'revision': args.source},
        'build': {'inventory': {'path': 'guest-tools.json', 'sha256': args.inventory_sha256}, 'tools': []}}
    before = tool_inventory.check(payload, descriptor, 'linux-x86_64')
    captured = inventory(snapshot(capture))
    record = {'schemaVersion': 'latent.rust.wasi-http.installed-build.v1', 'status': 'incomplete',
        'entry': 'recipe/tools/dev_guest_recipe.py', 'compilerInventory': before,
        'assemblySource': args.source, 'capturedSourceDigest': digest(captured), 'commands': [],
        'qualifier': identity(Path(__file__)), 'checkoutMounted': False, 'compilerNetwork': 'denied',
        'fullReleasedFrontendQualified': False, 'guestComponentsCompiled': 0,
        'nativeProductsBuilt': 0, 'backendComponentsBuilt': 0, 'signedExecutionQualified': False}
    started = time.monotonic()
    stage = 'exact-installed-inventory'
    try:
        for name in ('home', 'tmp', 'outside-checkout', 'unapproved', 'approved'):
            (work/name).mkdir(mode=0o700)
        environment = {'PATH': os.defpath, 'HOME': str(work/'home'), 'TMPDIR': str(work/'tmp'),
            'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}

        def run(label, *arguments, expected):
            remaining = 900 - (time.monotonic()-started)
            require(remaining > 0 and len(record['commands']) < 2, 'installed-rust-original-compiler-bound')
            result = run_bounded_result([str(payload/'sdk/bin/python'), '-I', '-B', *map(str, arguments)],
                work/'outside-checkout', environment, timeout_seconds=remaining, max_output_bytes=4*1024**2)
            outputs = {}
            for suffix, body in (('stdout', result.stdout), ('stderr', result.stderr)):
                path = work/(label+'.'+suffix)
                with path.open('xb') as stream:
                    stream.write(body)
                outputs[suffix] = identity(path)
            record['commands'].append({'name': label, 'exitCode': result.returncode, **outputs})
            require(result.returncode == expected, label+'-unexpected-exit')
            value = json.loads(result.stdout)
            require(value['schemaVersion'] == 'latent.dev.compiler-result.v1'
                and value['language'] == 'rust' and value['ownerIssue'] == 544 and value['cleanup'] == 'reaped'
                and value['code'] == ('success' if expected == 0 else 'compiler-input-or-build-failed'),
                'installed-rust-normal-result-and-reaped-cleanup')

        # compile_rust owns one fresh registry/cache per attempt. A separate
        # request-only attempt avoids changing that original freshness rule.
        for name in ('unapproved', 'approved'):
            shutil.copytree(capture, work/name/'app')
            (work/name/'build-cache').mkdir(mode=0o700)
            require(inventory(snapshot(work/name/'app')) == captured, 'installed-rust-exact-capture-copy')
        recipe = payload/'recipe/tools/dev_guest_recipe.py'
        stage = 'unapproved-normal-installed-entry'
        denied = work/'unapproved/output'
        run('unapproved', recipe, '--language', 'rust', '--project', work/'unapproved/app',
            '--output', denied, expected=1)
        approval = request(denied, work/'unapproved/app', canonical, digest)
        record['approval'] = approval
        stage = 'one-approved-offline-installed-guest'
        built = work/'approved/output'
        run('approved', recipe, '--language', 'rust', '--project', work/'approved/app',
            '--output', built, '--executable-approval', approval['identity'], expected=0)
        complete = json.loads((built/'BUILD-COMPLETE.json').read_bytes())
        require(complete['packageAssembled'] is False
            and json.loads((built/'executable-input-approval-request.json').read_bytes()) == approval
            and complete['observationDigest'] == identity(built/'build-observation.json')['sha256'],
            'installed-rust-original-build-and-controller-packaging-boundary')
        record['artifacts'] = {name: identity(built/name) for name in ('component.wasm', 'source-inputs.json',
            'recipe-inputs.json', 'build-observation.json', 'BUILD-COMPLETE.json', 'rust-http-runtime.json',
            'rust-http-composition.json', 'executable-input-outputs.json')}
        require(before == tool_inventory.check(payload, descriptor, 'linux-x86_64')
            and captured == inventory(snapshot(capture))
            and all(captured == inventory(snapshot(work/name/'app')) for name in ('unapproved', 'approved'))
            and identity(Path(__file__)) == record['qualifier'] and time.monotonic()-started < 900,
            'installed-rust-final-inputs-and-deadline')
        record.update(status='passed', guestComponentsCompiled=1, elapsedSeconds=time.monotonic()-started)
        (work/'installed-build.json').write_bytes(canonical(record))
        return 0
    except BaseException:
        record.update(status='failed', stage=stage)
        try:
            (work/'installed-build-FAILED.json').write_bytes(canonical(record))
        except OSError:
            pass
        raise


if __name__ == '__main__':
    raise SystemExit(main())
