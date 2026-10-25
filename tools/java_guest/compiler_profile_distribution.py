"""Builder-only promotion of one immutable carrier into the existing Java bundle."""
from __future__ import annotations

from pathlib import Path
import hashlib
import ast
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.java_guest import compiler_profile as profile

PUBLIC_RECEIPT = 'java-activation-fibers/FIBERS-COMPILE.json'


def _copy_fixed(root: Path, name: str, target: Path, expected: dict, deadline: float) -> None:
    from tools.java_guest.llvm_private_store_distribution import file_identity
    profile.need(file_identity(root, name, expected['bytes'], deadline) == expected, 'prepared-copy-source')
    created = False
    try:
        with (root / name).open('rb') as source, target.open('xb') as output:
            created = True
            count = 0
            while block := source.read(65536):
                profile.need(time.monotonic() < deadline, 'build-input-deadline')
                count += len(block)
                profile.need(count <= expected['bytes'], 'prepared-copy-bound')
                output.write(block)
        target.chmod(0o600)
        profile.need(file_identity(target.parent, target.name, expected['bytes'], deadline) == expected,
                     'prepared-copy-digest')
    except BaseException:
        if created:
            target.unlink(missing_ok=True)
        raise


def _save_cache(root: Path, cache: Path | None, records: tuple, deadline: float) -> None:
    if cache is None:
        return
    from tools.java_guest.llvm_private_store_distribution import file_identity
    for name, expected in records:
        target = cache / (expected['sha256'] + '.archive')
        if target.exists() or target.is_symlink():
            profile.need(file_identity(cache, target.name, expected['bytes'], deadline) == expected,
                         'prepared-cache-digest')
        else:
            _copy_fixed(root, name, target, expected, deadline)


def acquire(output: Path, token: str, *, _deadline: float | None = None) -> None:
    """Use exact prepared bytes first; Actions is only a cold acquisition input."""
    value = profile.pin()
    profile.need(value is not None, 'unqualified-distribution')
    from tools.java_guest import llvm_private_store_inputs as inputs
    profile.need(not output.exists() and not output.is_symlink() and output.parent.is_dir(), 'fresh-input-output')
    output.mkdir(mode=0o700)
    deadline = min(time.monotonic() + 180, _deadline or float('inf'))
    producer, qualification = value['producer'], value['qualification']
    records = (('producer.zip', producer['archive']), ('public-compiler.json', qualification['publicReceipt']))
    cache_root = os.environ.get('LSF_DEV_COMPILER_CACHE', '')
    cache = Path(cache_root) / 'java-prepared' if cache_root else None
    if cache is not None:
        profile.need(not cache.is_symlink() and not cache.is_junction(), 'prepared-cache-directory')
        cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        profile.need(cache.is_dir(), 'prepared-cache-directory')
    prepared = os.environ.get('LSF_DEV_JAVA_COMPILER_INPUT', '')
    if prepared:
        source = Path(prepared)
        _check_input(source, deadline)
        for name, expected in records:
            _copy_fixed(source, name, output / name, expected, deadline)
        _save_cache(output, cache, records, deadline)
        return
    if cache is not None:
        from tools.java_guest.llvm_private_store_distribution import file_identity
        complete = True
        for _name, expected in records:
            name = expected['sha256'] + '.archive'
            target = cache / name
            present = target.exists() or target.is_symlink()
            complete = complete and present
            if present:
                profile.need(file_identity(cache, name, expected['bytes'], deadline) == expected,
                             'prepared-cache-digest')
        if complete:
            for name, expected in records:
                _copy_fixed(cache, expected['sha256'] + '.archive', output / name, expected, deadline)
            return
    # No cache is an availability guarantee. A cold build needs either the
    # exact archived prepared-input pair or a still-available original origin.
    profile.need(type(token) is str and 0 < len(token) <= 4096,
                 'cold-build-requires-prepared-input-or-origin-token')
    public = qualification['publicArtifact']
    for artifact_id, expected, head, run, name, filename in (
            (producer['artifact'], producer['archive'], producer['head'], producer['run'],
             'java-llvm-private-stores-producer-' + producer['head'], 'producer.zip'),
            (public['id'], public['archive'], qualification['publicHead'], qualification['publicRun'],
             'java-public-fiber-assembly-' + qualification['publicHead'], 'public.zip')):
        base = 'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/' + str(artifact_id)
        headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'}
        metadata = json.loads(inputs._response(urllib.request.Request(base, headers=headers), deadline,
                                               maximum=4 * 1024 ** 2))
        profile.need(metadata.get('id') == artifact_id and metadata.get('name') == name
                     and metadata.get('expired') is False and metadata.get('size_in_bytes') == expected['bytes']
                     and metadata.get('digest') == 'sha256:' + expected['sha256']
                     and metadata.get('workflow_run', {}).get('head_sha') == head
                     and metadata.get('workflow_run', {}).get('id') == run, 'build-input-origin')
        request = urllib.request.Request(base + '/zip', headers=headers)
        try:
            response = urllib.request.build_opener(inputs.NoRedirect).open(
                request, timeout=min(30, deadline - time.monotonic()))
        except urllib.error.HTTPError as error:
            try:
                profile.need(error.code == 302, 'build-input-redirect')
                location = error.headers['Location']
            finally:
                error.close()
        else:
            response.close()
            raise ValueError('Java compiler profile build-input-redirect-required')
        parsed = urllib.parse.urlsplit(location)
        profile.need(parsed.scheme == 'https' and parsed.username is None and parsed.password is None
                     and parsed.port in (None, 443) and parsed.hostname is not None
                     and (parsed.hostname.endswith('.blob.core.windows.net')
                          or parsed.hostname.endswith('.githubusercontent.com')), 'build-input-blob-origin')
        count, digest = 0, hashlib.sha256()
        # The signed blob request has no GitHub Authorization header.
        with urllib.request.urlopen(location, timeout=min(30, deadline - time.monotonic())) as incoming, \
                (output / filename).open('xb') as destination:
            while block := incoming.read1(65536):
                profile.need(time.monotonic() < deadline, 'build-input-deadline')
                count += len(block)
                profile.need(count <= expected['bytes'], 'build-input-byte-limit')
                digest.update(block)
                destination.write(block)
        profile.need(count == expected['bytes'] and digest.hexdigest() == expected['sha256'], 'build-input-digest')
        (output / filename).chmod(0o600)
    with zipfile.ZipFile(output / 'public.zip') as archive:
        entries = archive.infolist()
        profile.need(len(entries) <= 512 and len({r.filename for r in entries}) == len(entries), 'public-input-members')
        member = archive.getinfo(PUBLIC_RECEIPT)
        profile.need(member.file_size == qualification['publicReceipt']['bytes'] and not member.flag_bits & 1,
                     'public-input-receipt')
        raw = archive.read(member)
    profile.need(profile.identity(raw) == qualification['publicReceipt'], 'public-input-receipt-digest')
    (output / 'public-compiler.json').write_bytes(raw)
    (output / 'public-compiler.json').chmod(0o600)
    profile.need(time.monotonic() < deadline, 'build-input-deadline')
    _save_cache(output, cache, records, deadline)


def _check_input(source: Path, deadline: float) -> dict:
    """A build input may expire upstream; its already-authenticated bytes do not."""
    value = profile.pin()
    profile.need(value is not None, 'unqualified-distribution')
    from tools.java_guest import llvm_private_store_distribution as carrier
    from tools.rust_capsule_project import read_file
    profile.need(source.is_dir() and not source.is_symlink() and not source.is_junction(), 'prepared-input-root')
    profile.need(carrier.file_identity(source, 'producer.zip', carrier.UPLOAD_BYTES, deadline)
                 == value['producer']['archive'], 'prepared-producer-archive')
    profile.need(profile.identity(read_file(source / 'public-compiler.json', 8 * 1024 ** 2))
                 == value['qualification']['publicReceipt'], 'prepared-public-receipt')
    return value


def check_input(source: Path) -> dict:
    return _check_input(source, time.monotonic() + 600)


def extract(source: Path, directory: Path) -> tuple[Path, Path]:
    """Decode a fixed local product; no network, tools or private-root authority."""
    deadline = time.monotonic() + 600
    value = _check_input(source, deadline)
    from tools.java_guest import llvm_private_store_inputs as inputs
    from tools.java_guest import llvm_private_store_distribution as carrier
    from tools.rust_capsule_project import read_file
    pin = inputs.pinned()
    profile.need({'head': inputs.HEAD, 'tree': inputs.TREE, 'run': inputs.RUN, 'job': inputs.JOB,
                  'artifact': pin['artifactId'], 'archive': {
                      'bytes': pin['archiveBytes'], 'sha256': pin['archiveSha256']}} == value['producer'],
                 'fixed-producer-cohort')
    profile.need(pin['carrier'] == value['carrier'] and pin['manifest'] == value['manifest'], 'fixed-carrier-cohort')
    decoded = inputs.decode(source / 'producer.zip', directory, deadline)
    # Only data/paths escape. This is not an _Admitted grant for the closed
    # public consumer, whose fixed-root recheck and hosted entry remain intact.
    products = decoded.products
    selected = profile.admit(products / 'toolchain')
    profile.need(selected is not None, 'decoded-sdk-profile')
    retained = directory / 'normal-provenance'
    retained.mkdir(mode=0o700)
    for name, expected in sorted(value['notices'].items()):
        data = read_file(products / name, 1024 * 1024)
        profile.need(profile.identity(data) == expected, 'retained-notice')
        (retained / name).write_bytes(data)
        (retained / name).chmod(0o600)
    for name, maximum in [('result.json', 8 * 1024 ** 2), ('source.json', 8 * 1024 ** 2),
                          ('commands.json', 8 * 1024 ** 2), ('units.xml', 256 * 1024),
                          ('lit.xml', 256 * 1024), (carrier.MANIFEST, carrier.MANIFEST_BYTES)]:
        data = read_file(directory / name, maximum)
        if name == 'result.json':
            profile.need(profile.identity(data) == value['qualification']['producerReceipt'], 'producer-receipt')
        if name == carrier.MANIFEST:
            profile.need(profile.identity(data) == value['manifest'], 'canonical-manifest')
        (retained / name).write_bytes(data)
    public = read_file(source / 'public-compiler.json', 8 * 1024 ** 2)
    profile.need(profile.identity(public) == value['qualification']['publicReceipt'], 'public-receipt-changed')
    (retained / 'public-compiler.json').write_bytes(public)
    (retained / 'normal-compiler-profile.json').write_bytes(selected[1])
    for path in retained.iterdir():
        path.chmod(0o600)
    return products / 'toolchain', retained


def product(source: Path, directory: Path, output: Path, *, _deadline: float | None = None) -> Path:
    """Exercise the existing compiler pack/installer without executing a tool."""
    from tools import dev_managed_distribution as distribution, dev_managed_tools as installer
    from tools import dev_tool_distribution
    from tools.java_guest.compiler import Compiler
    from tools.java_guest.llvm_private_store_distribution import file_identity
    from tools.rust_capsule_project import read_file
    deadline = min(time.monotonic() + 1195, _deadline or float('inf'))

    def check():
        profile.need(time.monotonic() < deadline, 'product-deadline')

    profile.need(not directory.exists() and not output.exists(), 'fresh-product')
    directory.mkdir(mode=0o700)
    decoded = directory / 'decoded'
    decoded.mkdir(mode=0o700)
    sdk, provenance = extract(source, decoded)
    value = profile.pin()
    profile.need(value is not None, 'unqualified-product')
    linked = profile.admit(sdk)
    profile.need(linked is not None and json.loads(linked[1])['representation'] == 'linked', 'linked-product')
    payload = directory / 'payload'
    (payload / 'sdk').mkdir(mode=0o700, parents=True)
    check()
    inventory = distribution.pack({'wasi-sdk': sdk, 'java-compiler-provenance': provenance}, payload / 'sdk')
    check()
    installed = installer.unpack(payload / 'sdk', directory / 'installed', check)
    compiler = Compiler.__new__(Compiler)
    compiler.wasi_sdk = installed / 'wasi-sdk'
    version = compiler._wasi_compiler_version()  # Admission only: never __init__/run/compile.
    admitted = json.loads(compiler.wasi_compiler_profile)
    profile.need(version == profile.CLANG_VERSION and admitted['representation'] == 'managed'
                 and admitted['compilerInventory'] == value['inventories']['managed'], 'installed-product')
    # Flattening preserves each named executable's bytes; use the exact driver
    # basename selected by the previously executed public compiler.
    driver = 'bin/clang-21'
    profile.need(file_identity(sdk, driver, 128 * 1024 ** 2, deadline)
                 == file_identity(compiler.wasi_sdk, driver, 128 * 1024 ** 2, deadline), 'driver-bytes')
    # Retain the ordinary source recipe too, including its new data-only pin.
    dev_tool_distribution.recipe(payload, 'java')
    for name in ('tools/java_guest/compiler_profile.py', profile.DATA):
        profile.need(read_file(payload / 'recipe' / name) == read_file(profile.ROOT / name), 'installed-recipe')
    from tools.build_process import run_bounded_result
    from tools.build_observation import build_environment
    script = ('import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
              'from tools.java_guest.compiler import Compiler;'
              'c=Compiler.__new__(Compiler);c.wasi_sdk=Path(sys.argv[2]);'
              'print(json.dumps({"version":c._wasi_compiler_version(),'
              '"admission":json.loads(c.wasi_compiler_profile)},sort_keys=True))')
    smoke = run_bounded_result([sys.executable, '-I', '-S', '-B', '-c', script,
        str(payload / 'recipe'), str(compiler.wasi_sdk)], cwd=directory, env=build_environment(directory),
        timeout_seconds=min(55, deadline - time.monotonic() - 5), max_output_bytes=64 * 1024)
    profile.need(smoke.returncode == 0 and not smoke.stderr, 'installed-recipe-admission')
    profile.need(json.loads(smoke.stdout) == {'version': version, 'admission': admitted},
                 'installed-recipe-admission-identity')
    public = json.loads(read_file(source / 'public-compiler.json', 8 * 1024 ** 2))
    profile.need(public['componentDigest'] == 'sha256:' + value['qualification']['publicComponent']['sha256'],
                 'public-product-component')
    # Match the *actual command-construction AST* to the qualified source pin.
    # This is an equivalence check, not another compilation or a runtime claim.
    compiler_source = read_file(profile.ROOT / 'tools/java_guest/compiler.py', 1024 * 1024).decode()
    parsed = ast.parse(compiler_source)
    clang_calls = [node for node in ast.walk(parsed) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                   and node.func.value.id == 'c_failure_context' and node.func.attr == 'run']
    profile.need(len(clang_calls) == 1, 'normal-clang-call')
    command_shape = profile.identity(ast.dump(clang_calls[0], include_attributes=False).encode())
    profile.need(command_shape == value['qualification']['normalCommandShape'], 'normal-clang-shape')
    profile.recheck(compiler.wasi_compiler_profile)
    check()
    result = {'schemaVersion': 'latent.java.prepared-compiler-product.v1',
        'sourceProfile': profile.identity(profile.read()), 'linked': json.loads(linked[1]),
        'installed': admitted, 'normalCompilerVersion': version, 'driver': driver,
        'driverIdentity': file_identity(compiler.wasi_sdk, driver, 128 * 1024 ** 2, deadline),
        'normalCommandShape': command_shape, 'managedInventory': inventory,
        'isolatedInstalledRecipeAdmission': {'exitCode': smoke.returncode, 'sitePackages': False,
            'stdout': profile.identity(smoke.stdout), 'stderr': profile.identity(smoke.stderr)},
        'managedArchive': file_identity(payload / 'sdk', 'managed.zip', installer.MAX_BYTES, deadline),
        'managedInputs': profile.identity(read_file(payload / 'sdk/managed-inputs.json', installer.MAX_DOCUMENT)),
        'scope': 'existing compiler pack/unpack and normal admission; compiler subproduct only',
        'compilerExecuted': False, 'runtimeQualified': False, 'releasePublished': False}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(profile.encoded(result))
    return installed / 'wasi-sdk'


def main() -> int:
    """Builder/CI input preparation, never a second installation frontend."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    fetch = commands.add_parser('acquire')
    fetch.add_argument('--output', type=Path, required=True)
    prepare = commands.add_parser('product')
    prepare.add_argument('--input', type=Path, required=True)
    prepare.add_argument('--work', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    stage = commands.add_parser('stage')
    stage.add_argument('--root', type=Path, required=True)
    stage.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'acquire':
        acquire(args.output, os.environ.get('GH_TOKEN', ''))
    elif args.operation == 'product':
        installed = product(args.input, args.work, args.output)
        print(installed)
    else:
        profile.need(args.root.is_dir() and not any(args.root.iterdir())
                     and not args.root.is_symlink() and not args.root.is_junction(), 'fresh-stage-root')
        deadline = time.monotonic() + 1195  # Shared acquisition+packing allowance.
        acquire(args.root / 'input', os.environ.get('GH_TOKEN', ''), _deadline=deadline)
        installed = product(args.root / 'input', args.root / 'work', args.output, _deadline=deadline)
        print(installed)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
