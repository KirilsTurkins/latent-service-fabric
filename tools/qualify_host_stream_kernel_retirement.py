"""Compile only the changed maintained factory translation unit; never install."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_host_stream_kernel_objects as objects
from tools import host_stream_kernel_device_retirement as source

ROOT = Path(__file__).resolve().parents[1]
BRANCH = 'feat/stream-kernel-recipient-retirement-20261022'
WORKFLOW = '.github/workflows/stream-kernel-retirement.yml'
PARENT_RECIPE = 'tools/qualify_host_stream_kernel_objects.py'
PARENT_RECIPE_SHA = '2a5f32b7797677ceaf8c4f1f0343859b1456ab00a54ff9ee52516b317e0e9cd7'
TARGET = 'net/factory.o'
require = objects.require
paths = objects.paths
maintained = objects.maintained


def object_selection():
    parent = objects.object_selection(False, recipient=True)
    require(len(parent) == 56 and sum(map(len, parent.values())) == 243,
        'retirement-original-recipient-oracle-drift')
    require(len(parent[TARGET]) == 87 and len(set(parent[TARGET])) == 87,
        'retirement-original-factory-oracle-drift')
    return {TARGET: parent[TARGET]}


def recipe_inputs():
    selected = (PARENT_RECIPE, 'tools/qualify_host_stream_kernel_retirement.py', WORKFLOW)
    result = {name: objects.identity(ROOT / name) for name in selected}
    require(result[PARENT_RECIPE]['sha256'] == PARENT_RECIPE_SHA,
        'retirement-reviewed-parent-recipe-changed')
    return result


def derive_frozen(tree, original):
    members = (Path(source.__file__).resolve(), source.FIXTURE.resolve())
    require(all(ROOT in path.parents for path in members), 'retirement-source-outside-checkout')
    before = {path.relative_to(ROOT).as_posix(): objects.identity(path) for path in members}
    try:
        derived, frozen, selected = objects.recipient_derive_frozen(tree, original)
        require(len(frozen) == 132 and len(derived) == 189 and len(selected) == 161,
            'retirement-original-material-membership')
        changed = source.transform(derived)
        require(set(changed) == set(derived) and
            {name for name in changed if changed[name] != derived[name]} ==
            set(source.preimages()['selectedWholeDerivedFiles']), 'retirement-seven-fragment-scope')
    finally:
        require(before == {path.relative_to(ROOT).as_posix(): objects.identity(path) for path in members},
            'retirement-source-changed-during-derivation')
    require(not (set(frozen) & set(before)), 'retirement-duplicate-source-freeze')
    return changed, {**frozen, **before}, selected


def configuration(before, after):
    for guard in (objects.selected_configuration, objects.netlabel_configuration,
            objects.sidcache_configuration, objects.audit_configuration,
            objects.route_configuration, objects.device_configuration,
            objects.registration_configuration, objects.recipient_configuration):
        guard(before, after)


def generated_configuration(raw):
    required = set((*objects.REQUIRED, objects.SELECTED, 'CONFIG_NETLABEL', 'CONFIG_XFRM',
        *objects.AUDIT_REQUIRED, *objects.DEVICE_REQUIRED, *objects.REGISTRATION_REQUIRED,
        *objects.RECIPIENT_REQUIRED))
    disabled = set((*objects.DEVICE_DISABLED, *objects.REGISTRATION_DISABLED,
        'CONFIG_NET_DEV_REFCNT_TRACKER', 'CONFIG_LWTUNNEL', 'CONFIG_PREEMPT_RT'))
    require(all(('#define ' + name + ' 1\n').encode() in raw for name in required),
        'retirement-generated-original-code-disabled')
    require(all(('#define ' + name + ' ').encode() not in raw for name in disabled),
        'retirement-generated-original-disabled-code-drift')
    require(b'#define CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE 256\n' in raw,
        'retirement-generated-original-sidcache-profile-drift')


def defined_symbols(raw, expected):
    result = {}
    for line in raw.decode('utf8').splitlines():
        if not line.strip():
            continue
        fields = line.split()
        require(len(fields) == 3 and re.fullmatch(r'[0-9a-fA-F]+', fields[0]) and
            re.fullmatch(r'[ABCDGIRSTVW]', fields[1]) and fields[2] not in result,
            'retirement-invalid-or-duplicate-external-symbol')
        result[fields[2]] = fields[1]
    require(len(expected) == len(set(expected)) == 87 and
        all(result.get(name) == 'T' for name in expected), 'retirement-original-global-functions-missing')
    return result


def run(archive, output):
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true' and
        os.environ.get('RUNNER_OS') == 'Linux', 'hosted-linux-only')
    origin = {name: os.environ.get(name) for name in ('GITHUB_REPOSITORY',
        'GITHUB_EVENT_NAME', 'GITHUB_REF_NAME')}
    require(origin == {'GITHUB_REPOSITORY': 'KirilsTurkins/latent-service-fabric',
        'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': BRANCH}, 'retirement-fixed-owning-origin')
    selected_objects, recipe = object_selection(), recipe_inputs()
    value = maintained.manifest()
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
        'outside-checkout-output')
    paths.new_directory(output)
    archive = objects.snapshot_archive(archive, output / 'source.tar.xz', value['archive'])
    additional = ('net/Kconfig', 'net/Makefile') + tuple(name
        for name in objects.packet_source.fixture()['source'] if name not in value['source'])
    original = maintained.authenticate_archive(archive, value, additional)
    archive_identity = objects.identity(archive)
    require(archive_identity == {key: value['archive'][key] for key in ('bytes', 'sha256')},
        'archive-identity-drift')
    log, source_root = output / 'commands', output / 'source'
    log.mkdir()
    source_root.mkdir()
    tools = {name: shutil.which(name) for name in ('tar', 'make', 'gcc', 'nm')}
    require(all(tools.values()), 'missing-kbuild-tool')
    env = objects.build_environment(output)
    env.update(KBUILD_BUILD_USER='lsf-object-check', KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-21 00:00:00 UTC', KCONFIG_NOTIMESTAMP='1')
    commands = objects.Commands(source_root, log, env, deadline_seconds=900, command_seconds=300)
    receipt = {'schemaVersion': 'lsf.maintained-kernel-retirement-object-check.v1',
        'status': 'in-progress', 'profile': 'original-device-final-return-resumption-source',
        'upstreamCommit': maintained.COMMIT, 'archive': archive_identity,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
            timeout=15).decode().strip(), 'origin': origin,
        'manifestSha256': maintained.MANIFEST_SHA, 'recipeInputs': recipe,
        'additionalArchiveSources': list(additional),
        'additionalSourcesIndependentlyGitCorroborated': False,
        'historicalRecipientObjectSource': '1625510fc6b6bcd32505511729ea355cae226b38',
        'historicalRecipientObjects': 56, 'historicalRecipientDefinedSymbols': 243,
        'historicalRecipientBuildReexecuted': False,
        'retirementResumptionSourceImplemented': True,
        'kernelLinked': False, 'kernelBooted': False, 'factoryInstalled': False,
        'productionInstallation': False, 'completeAllocationClosure': False,
        'actualSharedWorkqueueAccounted': False, 'actualRecipientCallbackClosure': False,
        'instrumentationAdmissionQualified': False, 'physicalQueueQualified': False}
    receipt.update({gate: False for gate in source.GATES})
    stage, failed = 'extract', False
    try:
        commands.run('extract-authenticated-source', tools['tar'], '--extract', '--xz',
            '--file', str(archive), '--directory', str(source_root),
            '--no-same-owner', '--no-same-permissions')
        tree = source_root / ('linux-' + value['version'])
        commands.root = tree
        require(objects.identity(archive) == archive_identity, 'snapshot-changed-during-extraction')
        require(all((tree / name).read_bytes() == raw for name, raw in original.items()),
            'extracted-preimage-drift')
        stage = 'derive'
        derived, frozen, original = derive_frozen(tree, original)
        receipt['retirementSourceFreeze'] = frozen
        receipt['selectedOriginalInputs'] = {name: objects.identity(tree / name) for name in original}
        receipt['changedFactoryFragments'] = sorted(source.preimages()['selectedWholeDerivedFiles'])
        receipt['derived'] = {}
        for name, raw in derived.items():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            receipt['derived'][name] = objects.identity(target)
        for name, suffix in (('net/Kconfig', objects.KCONFIG), ('net/Makefile', objects.MAKEFILE)):
            require(objects.SELECTED.encode() not in original[name], 'private-config-already-present')
            (tree / name).write_bytes(original[name] + suffix.encode())
        build = output / 'objects'
        common = [tools['make'], 'O=' + str(build), 'ARCH=x86_64', 'CC=' + tools['gcc']]
        stage = 'configuration'
        receipt['compiler'] = commands.run('compiler-identity', tools['gcc'], '--version').decode('utf8')
        commands.run('original-defconfig', *common, 'x86_64_defconfig')
        baseline = (build / '.config').read_bytes()
        (output / 'baseline.config').write_bytes(baseline)
        before = objects.configuration(baseline)
        require(before.get(objects.SELECTED) == 'n', 'private-default-enabled')
        selected = baseline.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',
            b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected != baseline, 'missing-private-config')
        (build / '.config').write_bytes(selected)
        commands.run('resolve-selected-config', *common, 'olddefconfig')
        final = (build / '.config').read_bytes()
        configuration(before, objects.configuration(final))
        (output / 'selected.config').write_bytes(final)
        receipt['configuration'] = {'baseline': objects.identity(output / 'baseline.config'),
            'selected': objects.identity(output / 'selected.config'),
            'onlyChangedSymbol': objects.SELECTED}
        paths.write_new(output / 'selection.json', (json.dumps(receipt, indent=2) + '\n').encode())
        stage = 'single-factory-object'
        commands.run('single-factory-real-kbuild-object', *common, '-j2', *selected_objects)
        generated_configuration((build / 'include/generated/autoconf.h').read_bytes())
        require((build / '.config').read_bytes() == final, 'build-mutated-config')
        product = build / TARGET
        require(product.read_bytes()[:4] == b'\x7fELF', 'elf-product-required')
        symbols = commands.run('symbols-factory', tools['nm'], '--extern-only',
            '--defined-only', str(product))
        defined_symbols(symbols, selected_objects[TARGET])
        receipt['objects'] = {TARGET: {**objects.identity(product),
            'requiredDefinedSymbols': list(selected_objects[TARGET])}}
        require(objects.identity(archive) == archive_identity, 'archive-changed')
        require(all(objects.identity(tree / name) == row for name, row in receipt['derived'].items()),
            'derived-source-changed')
        require(all(objects.identity(ROOT / name) == row for name, row in frozen.items()),
            'retirement-source-changed-during-build')
        require(recipe_inputs() == recipe, 'retirement-recipe-changed-during-build')
        receipt['status'] = 'passed'
        paths.write_new(output / 'qualification.json', (json.dumps(receipt, indent=2) + '\n').encode())
        return receipt
    except BaseException:
        failed = True
        try:
            paths.write_new(output / 'FAILED.json',
                (json.dumps({**receipt, 'status': 'failed', 'stage': stage}, indent=2) + '\n').encode())
        except BaseException:
            pass
        raise
    finally:
        try:
            paths.write_new(output / 'commands.json', (json.dumps(commands.records, indent=2) + '\n').encode())
        except BaseException:
            if not failed:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.archive.resolve(strict=True), args.output)
