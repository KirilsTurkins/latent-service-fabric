"""Compile selected maintained-kernel objects; never link, boot or install."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.dev_workflow import paths
from tools import host_stream_kernel_maintained as maintained
from tools import host_stream_kernel_protocol as protocol
from tools import host_stream_kernel_netlabel as netlabel_source
from tools.owned_test_process import ProcessFailure, run_owned

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ('CONFIG_INET', 'CONFIG_SECURITY', 'CONFIG_SECURITY_NETWORK', 'CONFIG_SECURITY_SELINUX')
SELECTED = 'CONFIG_LSF_STREAM_FACTORY'
KCONFIG = ('\nconfig LSF_STREAM_FACTORY\n\tbool "Uninstalled LSF private source object check"\n'
    '\tdepends on INET && SECURITY && SECURITY_NETWORK\n\tdefault n\n')
MAKEFILE = '\nobj-$(CONFIG_LSF_STREAM_FACTORY) += factory.o\n'
OBJECTS = {
    'net/socket.o': ('lsf_prepaid_sock_create',),
    'fs/inode.o': ('lsf_prepaid_new_inode',),
    'net/core/sock.o': ('lsf_prepaid_sk_alloc', 'lsf_prepaid_protocol_allocate', 'lsf_prepaid_protocol_return', 'lsf_prepaid_protocol_clear'),
    'net/ipv4/af_inet.o': ('lsf_prepaid_inet_create', 'lsf_prepaid_protocol_family'),
    'security/security.o': ('lsf_prepaid_security_inode_alloc', 'lsf_prepaid_security_sk_alloc'),
    'net/factory.o': ('lsf_factory_register', 'lsf_factory_blob_allocate', 'lsf_factory_blob_finish'),
}

NETLABEL_OBJECTS = {
    'security/selinux/netlabel.o': ('lsf_prepaid_netlabel_sock_genattr',),
    'security/selinux/ss/services.o': ('lsf_prepaid_security_sid_to_secattr',),
    'security/selinux/ss/mls.o': ('lsf_prepaid_mls_export_cat',),
    'security/selinux/ss/ebitmap.o': ('lsf_prepaid_ebitmap_export',),
    'net/netlabel/netlabel_kapi.o': ('lsf_prepaid_catmap_setlong',
        'lsf_prepaid_netlbl_sock_setattr', 'lsf_prepaid_netlbl_conn_setattr',
        'lsf_prepaid_netlabel_source', 'lsf_prepaid_label_domain_return',
        'lsf_prepaid_label_catmap_return', 'lsf_prepaid_label_secattr_return',
        'lsf_prepaid_cipso_buffer_return', 'lsf_prepaid_options_failed_return',
        'lsf_prepaid_options_retire', 'lsf_prepaid_netlabel_strdup'),
    'net/ipv4/cipso_ipv4.o': ('lsf_prepaid_cipso_sock_setattr',),
}
NETLABEL_FACTORY = ('lsf_factory_child_allocate', 'lsf_factory_protocol_parent',
    'lsf_factory_options_publish', 'lsf_factory_options_owned', 'lsf_factory_options_queue')


def object_selection(netlabel):
    require(type(netlabel) is bool, 'closed-profile-selector')
    if not netlabel:
        return dict(OBJECTS)
    return {**OBJECTS, **NETLABEL_OBJECTS,
        'net/factory.o': OBJECTS['net/factory.o'] + NETLABEL_FACTORY}



def require(value, message):
    if not value:
        raise ValueError('kernel-object-' + message)


class Commands:
    def __init__(self, root, output, environment, *, deadline_seconds=900, command_seconds=300):
        self.root, self.output, self.environment = root, output, environment
        self.deadline = time.monotonic() + deadline_seconds
        self.command_seconds, self.retained, self.records = command_seconds, 0, []
        (output/'logs').mkdir()

    def retain(self, label, result):
        self.retained += len(result.output) + len(result.stderr)
        require(len(result.output)+len(result.stderr) <= 4*1024**2 and self.retained <= 16*1024**2, 'diagnostic-bound')
        for name, raw in (('stdout',result.output),('stderr',result.stderr)):
            paths.write_new(self.output/'logs'/(label+'.'+name+'.txt'),raw)

    def run(self, stage, *command):
        timeout = min(self.command_seconds,self.deadline-time.monotonic())
        require(timeout > 0, 'original-command-deadline')
        label = f'{len(self.records):02d}-{stage}'
        try:
            result=run_owned([str(part) for part in command],cwd=self.root,env=self.environment,
                timeout=timeout,maximum=4*1024**2,separate_stderr=True)
        except ProcessFailure as failure:
            try:
                self.records.append({'stage':stage,'category':failure.category,'reason':failure.reason,'completed':False})
                if failure.result is not None:self.retain(label,failure.result)
            except BaseException:pass
            raise
        self.retain(label,result)
        self.records.append({'stage':stage,'exitCode':result.returncode,'completed':True,
            'elapsedMillis':result.elapsed_ms,'descendantsCleaned':result.cleaned})
        require(result.returncode == 0 and result.cleaned,stage+'-failed-see-original-diagnostics')
        return result.output


def snapshot_archive(source, target, expected):
    """Copy a single anchored input into a fresh private immutable snapshot."""
    checksum, used, deadline = hashlib.sha256(),0,time.monotonic()+180
    with paths.opened(source.parent,source.name) as descriptor:
        before=os.fstat(descriptor)
        require(before.st_size == expected['bytes'] <= maintained.MAX_ARCHIVE, 'snapshot-byte-bound')
        with target.open('xb') as output:
            while raw := os.read(descriptor,1024*1024):
                used += len(raw)
                require(used <= expected['bytes'] and time.monotonic() < deadline,'snapshot-read-bound')
                checksum.update(raw);output.write(raw)
        after=os.fstat(descriptor);paths.regular(after)
        require((before.st_size,before.st_mtime_ns,before.st_ctime_ns) ==
            (after.st_size,after.st_mtime_ns,after.st_ctime_ns),'snapshot-source-changed')
    require(used == expected['bytes'] and checksum.hexdigest() == expected['sha256'],'snapshot-byte-identity')
    target.chmod(0o400)
    return target


def configuration(raw):
    require(type(raw) is bytes and len(raw) <= 1024 * 1024, 'configuration-bound')
    result = {}
    for line in raw.decode('utf8').splitlines():
        if match := re.fullmatch(r'(CONFIG_[A-Za-z0-9_]+)=(.*)', line):
            name, value = match.groups()
        elif match := re.fullmatch(r'# (CONFIG_[A-Za-z0-9_]+) is not set', line):
            name, value = match[1], 'n'
        else:
            require(not line.startswith(('CONFIG_', '# CONFIG_')), 'configuration-line')
            continue
        require(name not in result, 'configuration-duplicate')
        result[name] = value
    require(result, 'configuration-empty')
    return result


def selected_configuration(before, after):
    require(all(before.get(name) == after.get(name) == 'y' for name in REQUIRED), 'security-or-inet-disabled')
    require(before.get(SELECTED) == 'n' and after.get(SELECTED) == 'y', 'private-code-not-selected')
    require({k: v for k, v in before.items() if k != SELECTED}
        == {k: v for k, v in after.items() if k != SELECTED}, 'unrelated-config-drift')


def netlabel_configuration(before, after):
    require(before.get('CONFIG_NETLABEL') == after.get('CONFIG_NETLABEL') == 'y',
            'netlabel-originally-disabled')


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'regular-product-required')
    with path.open('rb') as stream:
        return {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}


def run(archive, output, *, netlabel=False):
    selected_objects = object_selection(netlabel)
    require(sys.platform == 'linux' and os.environ.get('GITHUB_ACTIONS') == 'true'
        and os.environ.get('RUNNER_OS') == 'Linux', 'hosted-linux-only')
    value = maintained.manifest()
    output = paths.absolute(output)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents, 'outside-checkout-output')
    paths.new_directory(output)
    archive = snapshot_archive(archive,output/'source.tar.xz',value['archive'])
    # All archive readers and tar now consume this private verified snapshot,
    # never reopen the caller's mutable pathname. Recheck before any make.
    additional_sources = ('net/Kconfig', 'net/Makefile')
    if netlabel:
        additional_sources += tuple(name for name in netlabel_source.fixture()['source'] if name not in value['source'])
    original = maintained.authenticate_archive(archive, value, additional_sources)
    archive_identity = identity(archive)
    require(archive_identity == {key: value['archive'][key] for key in ('bytes', 'sha256')}, 'archive-identity-drift')
    log = output / 'commands';log.mkdir()
    source = output / 'source';source.mkdir()
    tools = {name: shutil.which(name) for name in ('tar', 'make', 'gcc', 'nm')}
    require(all(tools.values()), 'missing-kbuild-tool')
    env = build_environment(output)
    env.update(KBUILD_BUILD_USER='lsf-object-check', KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-21 00:00:00 UTC', KCONFIG_NOTIMESTAMP='1')
    commands = Commands(source, log, env, deadline_seconds=900, command_seconds=300)
    receipt = {'schemaVersion': 'lsf.maintained-kernel-object-check.v1', 'status': 'in-progress',
        'upstreamCommit': maintained.COMMIT, 'archive': archive_identity,
        'sourceCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=15).decode().strip(),
        'manifestSha256': maintained.MANIFEST_SHA,
        'additionalArchiveSources': list(additional_sources),
        'additionalSourcesIndependentlyGitCorroborated': False,
        'kernelLinked': False, 'kernelBooted': False, 'factoryInstalled': False,
        'completeAllocationClosure': False, 'productionInstallation': False}
    stage = 'extract'
    failed = False
    try:
        commands.run('extract-authenticated-source', tools['tar'], '--extract', '--xz', '--file', str(archive),
            '--directory', str(source), '--no-same-owner', '--no-same-permissions')
        tree = source / ('linux-' + value['version'])
        commands.root = tree
        require(identity(archive) == archive_identity, 'snapshot-changed-during-extraction')
        require(all((tree / name).read_bytes() == raw for name, raw in original.items()), 'extracted-preimage-drift')
        stage = 'derive'
        derived = (netlabel_source.derive({name: original[name] for name in netlabel_source.fixture()['source']})
                   if netlabel else protocol.derive({name: original[name] for name in protocol.SOURCES}))
        if netlabel:
            receipt['profile'] = 'netlabel-nested-owner-source'
        receipt['derived'] = {}
        for name, raw in derived.items():
            target = tree / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            receipt['derived'][name] = identity(target)
        for name, suffix in (('net/Kconfig', KCONFIG), ('net/Makefile', MAKEFILE)):
            require(SELECTED.encode() not in original[name], 'private-config-already-present')
            (tree / name).write_bytes(original[name] + suffix.encode())
        build = output / 'objects'
        common = [tools['make'], 'O=' + str(build), 'ARCH=x86_64', 'CC=' + tools['gcc']]
        stage = 'configuration'
        compiler = commands.run('compiler-identity', tools['gcc'], '--version').decode('utf8')
        commands.run('original-defconfig', *common, 'x86_64_defconfig')
        baseline = (build / '.config').read_bytes()
        (output / 'baseline.config').write_bytes(baseline)
        before = configuration(baseline)
        require(before.get(SELECTED) == 'n', 'private-default-enabled')
        selected = baseline.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n', b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected != baseline, 'missing-private-config')
        (build / '.config').write_bytes(selected)
        commands.run('resolve-selected-config', *common, 'olddefconfig')
        final = (build / '.config').read_bytes()
        selected_configuration(before, configuration(final))
        if netlabel:
            netlabel_configuration(before, configuration(final))
            receipt['netlabelEnabledBeforeAndAfter'] = True
        (output / 'selected.config').write_bytes(final)
        receipt['configuration'] = {'baseline': identity(output / 'baseline.config'),
            'selected': identity(output / 'selected.config'), 'onlyChangedSymbol': SELECTED,
            'securityAndInetPreserved': list(REQUIRED)}
        receipt['compiler'] = compiler
        paths.write_new(output / 'selection.json', (json.dumps(receipt, indent=2)+'\n').encode())
        stage = 'twelve-netlabel-objects' if netlabel else 'six-objects'
        commands.run('twelve-selected-real-kbuild-objects' if netlabel else 'six-selected-real-kbuild-objects',
                     *common, '-j2', *selected_objects)
        autoconf = (build / 'include/generated/autoconf.h').read_bytes()
        require(all(('#define '+name+' 1\n').encode() in autoconf for name in (*REQUIRED, SELECTED)),
            'generated-private-or-security-code-disabled')
        if netlabel:
            require(b'#define CONFIG_NETLABEL 1\n' in autoconf, 'netlabel-generated-code-disabled')
        require((build / '.config').read_bytes() == final, 'build-mutated-config')
        receipt['objects'] = {}
        for name, expected in selected_objects.items():
            product = build / name
            require(product.read_bytes()[:4] == b'\x7fELF', 'elf-product-required')
            symbols = commands.run('symbols-' + name.replace('/', '-').replace('.', '-'),
                tools['nm'], '--defined-only', str(product)).decode('utf8')
            defined = {line.split()[-1] for line in symbols.splitlines() if line.split()}
            require(set(expected) <= defined, 'private-symbols-missing-' + name)
            receipt['objects'][name] = {**identity(product), 'requiredDefinedSymbols': list(expected)}
        require(identity(archive) == archive_identity, 'archive-changed')
        require(all(identity(tree/name) == row for name, row in receipt['derived'].items()), 'derived-source-changed')
        receipt['status'] = 'passed'
        paths.write_new(output / 'qualification.json', (json.dumps(receipt, indent=2)+'\n').encode())
        return receipt
    except BaseException:
        failed = True
        try:paths.write_new(output / 'FAILED.json', (json.dumps({**receipt, 'status':'failed', 'stage':stage},indent=2)+'\n').encode())
        except BaseException:pass
        raise
    finally:
        try:paths.write_new(output / 'commands.json', (json.dumps(commands.records,indent=2)+'\n').encode())
        except BaseException:
            if not failed:raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--netlabel', action='store_true', help='select the closed nested-label object-only profile')
    args = parser.parse_args()
    run(args.archive.resolve(strict=True), args.output, netlabel=args.netlabel)
