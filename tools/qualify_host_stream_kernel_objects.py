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
from tools import host_stream_kernel_netport as netport_source
from tools import host_stream_kernel_sidcache as sidcache_source
from tools import host_stream_kernel_avc as avc_source
from tools import host_stream_kernel_audit as audit_source
from tools import host_stream_kernel_bind as bind_source
from tools import host_stream_kernel_route as route_source
from tools import host_stream_kernel_route_cache as route_cache_source
from tools import host_stream_kernel_packet as packet_source
from tools import host_stream_kernel_device as device_source
from tools import host_stream_kernel_device_firmware as firmware_source
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
NETPORT_OBJECTS = {
    'security/selinux/netport.o': ('lsf_prepaid_netport_sid', 'lsf_prepaid_netport_drain'),
    'security/selinux/hooks.o': (),
}
NETPORT_FACTORY = ('lsf_factory_netport_publish', 'lsf_factory_netport_queue',
                   'lsf_factory_netport_candidate', 'lsf_factory_netport_current')
SIDCACHE_FACTORY = ('lsf_factory_sidcache_publish', 'lsf_factory_sidcache_queue',
    'lsf_factory_sidcache_destroy', 'lsf_factory_sidcache_candidate', 'lsf_factory_sidcache_current')
SIDCACHE_SERVICES = ('lsf_prepaid_audit_dup', 'lsf_prepaid_audit_string_return',
    'lsf_prepaid_sidcache_drain', 'lsf_prepaid_security_sid_to_context')
SIDCACHE_OBJECTS = {'security/selinux/ss/sidtab.o':
    ('lsf_prepaid_sid2str_put', 'lsf_prepaid_sid2str_get', 'lsf_prepaid_sidcache_detach')}
AVC_FACTORY = ('lsf_factory_avc_member', 'lsf_factory_avc_phase',
    'lsf_factory_avc_replace', 'lsf_factory_avc_publish', 'lsf_factory_avc_queue',
    'lsf_factory_avc_candidate', 'lsf_factory_avc_current')
AVC_OBJECTS = {'security/selinux/avc.o':
    ('lsf_prepaid_avc_has_perm', 'lsf_prepaid_avc_drain')}
AUDIT_OBJECTS = {
    'net/core/skbuff.o': ('lsf_prepaid_audit_skb_new',),
    'kernel/audit.o': ('lsf_prepaid_audit_log_start', 'lsf_prepaid_audit_log_end'),
    'security/lsm_audit.o': ('lsf_prepaid_common_lsm_audit',),
    'net/netlink/af_netlink.o': ('netlink_unicast', 'netlink_broadcast_filtered'),
}
AUDIT_REQUIRED = ('CONFIG_AUDIT', 'CONFIG_AUDITSYSCALL')
BIND_OBJECTS = {
    'net/ipv4/inet_hashtables.o': ('lsf_prepaid_bind_check', 'lsf_prepaid_bind_owned',
        'lsf_prepaid_bind_bucket_create', 'lsf_prepaid_bind2_allocate', 'lsf_prepaid_bind_return'),
    'net/ipv4/inet_connection_sock.o': ('inet_csk_get_port',),
}
ROUTE_OBJECTS = {
    'net/ipv4/route.o': ('lsf_prepaid_route_key', 'lsf_prepaid_route_xfrm', 'ip_route_output_flow'),
    'net/core/dst.o': ('dst_release',),
}
ROUTE_FACTORY = ('lsf_factory_route_queue', 'lsf_factory_route_return')
ROUTE_CACHE_FACTORY = ('lsf_factory_route_parent_attach', 'lsf_factory_route_cache_publish',
    'lsf_factory_route_current', 'lsf_factory_route_parent_take')
ROUTE_CACHE_FUNCTIONS = ('lsf_prepaid_route_cache_return', 'lsf_prepaid_route_cache_drain')
PACKET_FACTORY = ('lsf_factory_packet_birth', 'lsf_factory_packet_head_current')
PACKET_SKBUFF = ('lsf_prepaid_packet_skb_new', 'lsf_prepaid_packet_alloc_sock',
    'lsf_prepaid_packet_linear', 'lsf_prepaid_packet_for_sock')
PACKET_OBJECTS = {
    'net/ipv4/tcp.o': ('lsf_prepaid_tcp_stream_alloc_skb',
        'lsf_prepaid_tcp_sendmsg_locked', 'tcp_stream_alloc_skb', 'tcp_sendmsg_locked'),
    'net/ipv4/tcp_output.o': ('tcp_send_fin',),
    'net/ipv4/tcp_input.o': ('tcp_rcv_established',),
}


DEVICE_FACTORY = ('lsf_factory_device_pci_ready', 'lsf_factory_device_pci_enter',
    'lsf_factory_device_pci_leave', 'lsf_factory_device_pci_allocate',
    'lsf_factory_device_pci_return', 'lsf_factory_device_pci_owned')
DEVICE_OBJECTS = {
    'drivers/pci/probe.o': ('lsf_prepaid_pci_alloc_dev', 'lsf_prepaid_pci_setup_device',
        'lsf_prepaid_pci_scan_single_device', 'pci_alloc_dev', 'pci_setup_device', 'pci_scan_single_device'),
    'drivers/base/core.o': ('dev_set_name', 'device_add', 'device_initialize'),
    'lib/kobject.o': ('kobject_set_name_vargs', 'kobject_put'),
    'mm/util.o': ('kstrdup', 'kstrdup_const', 'kfree_const'),
    'lib/kasprintf.o': ('kvasprintf', 'kvasprintf_const'),
}
DEVICE_REQUIRED = ('CONFIG_PCI', 'CONFIG_ACPI', 'CONFIG_PCI_QUIRKS', 'CONFIG_STRICT_KERNEL_RWX')
DEVICE_DISABLED = ('CONFIG_PCI_IOV', 'CONFIG_OF')

FIRMWARE_FACTORY = ('lsf_factory_device_firmware_begin', 'lsf_factory_device_firmware_get',
    'lsf_factory_device_firmware_current', 'lsf_factory_device_firmware_invalidate',
    'lsf_factory_device_firmware_retire', 'lsf_factory_device_firmware_constructor_enter',
    'lsf_factory_device_firmware_constructor_leave')
FIRMWARE_OBJECTS = {
    'drivers/acpi/scan.o': ('lsf_prepaid_acpi_scan_enter', 'lsf_prepaid_acpi_scan_leave',
        'lsf_prepaid_acpi_reference'),
    'drivers/acpi/bus.o': ('lsf_prepaid_acpi_dev_for_each_child', 'acpi_dev_for_each_child'),
    'drivers/acpi/glue.o': ('lsf_prepaid_acpi_find_child_device', 'acpi_find_child_device'),
    'drivers/acpi/osl.o': ('lsf_prepaid_acpi_queue_reference_put',
        'lsf_prepaid_acpi_reference_queue_ready', 'acpi_queue_hotplug_work'),
    'drivers/pci/pci-acpi.o': ('lsf_prepaid_pci_set_acpi_fwnode', 'pci_set_acpi_fwnode'),
}
FIRMWARE_EXTRACTED = ('drivers/acpi/bus.c', 'drivers/acpi/glue.c', 'drivers/acpi/internal.h',
    'drivers/acpi/osl.c', 'drivers/acpi/scan.c', 'drivers/pci/pci-acpi.c',
    'include/acpi/acpi_bus.h', 'include/linux/acpi.h', 'include/linux/fwnode.h',
    'include/linux/kref.h', 'include/linux/pci-acpi.h', 'include/linux/workqueue.h', 'lib/klist.c')


def object_selection(netlabel, netport=False, sidcache=False, avc=False, audit=False, bind=False, route=False, route_cache=False, packet=False, device=False, firmware=False):
    require(all(type(value) is bool for value in (netlabel, netport, sidcache, avc, audit, bind, route, route_cache, packet, device, firmware)), 'closed-profile-selector')
    require(sum((netlabel, netport, sidcache, avc, audit, bind, route, route_cache, packet, device, firmware)) <= 1, 'exclusive-profile-selector')
    if firmware:
        selected = object_selection(False, device=True)
        selected.update(FIRMWARE_OBJECTS)
        selected['net/factory.o'] += FIRMWARE_FACTORY
        selected['drivers/base/core.o'] += ('get_device', 'put_device', 'device_for_each_child', 'set_primary_fwnode')
        selected['lib/kobject.o'] += ('kobject_get',)
        return selected
    if device:
        selected = object_selection(False, False, False, False, False, False, False, False, True)
        selected.update(DEVICE_OBJECTS)
        selected['net/factory.o'] += DEVICE_FACTORY
        return selected
    if packet:
        selected = object_selection(False, False, False, False, False, False, False, True)
        selected.update(PACKET_OBJECTS)
        selected['net/factory.o'] += PACKET_FACTORY
        selected['net/core/skbuff.o'] += PACKET_SKBUFF
        return selected
    if route_cache:
        selected = object_selection(False, False, False, False, False, False, True)
        selected['net/factory.o'] += ROUTE_CACHE_FACTORY
        selected['net/ipv4/route.o'] += ROUTE_CACHE_FUNCTIONS
        return selected
    if route:
        selected = object_selection(False, False, False, False, False, True)
        selected.update(ROUTE_OBJECTS)
        selected['net/factory.o'] += ROUTE_FACTORY
        return selected
    if bind:
        selected = object_selection(False, False, False, False, True)
        selected.update(BIND_OBJECTS)
        return selected
    if audit:
        selected = object_selection(False, False, False, True)
        selected.update(AUDIT_OBJECTS)
        selected['net/factory.o'] += ('lsf_factory_audit_head_current',)
        selected['security/selinux/avc.o'] += ('lsf_prepaid_avc_audit',)
        return selected
    if avc:
        selected = object_selection(False, False, True)
        selected.update(AVC_OBJECTS)
        selected['net/factory.o'] += AVC_FACTORY
        return selected
    if sidcache:
        selected = object_selection(False, True)
        selected.update(SIDCACHE_OBJECTS)
        selected['net/factory.o'] += SIDCACHE_FACTORY
        selected['security/selinux/ss/services.o'] += SIDCACHE_SERVICES
        return selected
    if netport:
        return {**OBJECTS, **NETLABEL_OBJECTS, **NETPORT_OBJECTS,
            'net/factory.o': OBJECTS['net/factory.o'] + NETLABEL_FACTORY + NETPORT_FACTORY}
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


def sidcache_configuration(before, after):
    require(before.get('CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE') ==
            after.get('CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE') == '256',
            'sidcache-original-256-entry-profile-required')


def audit_configuration(before, after):
    require(all(before.get(name) == after.get(name) == 'y' for name in AUDIT_REQUIRED),
            'audit-originally-disabled')


def route_configuration(before, after):
    require(before.get('CONFIG_XFRM') == after.get('CONFIG_XFRM') == 'y',
            'route-xfrm-originally-disabled')
    require(all(before.get(name) == after.get(name) == 'n'
        for name in ('CONFIG_NET_DEV_REFCNT_TRACKER', 'CONFIG_LWTUNNEL')),
        'route-original-nonallocating-profile-required')


def device_configuration(before, after):
    require(all(before.get(name) == after.get(name) == 'y' for name in DEVICE_REQUIRED),
        'device-original-config-required')
    require(all(before.get(name) == after.get(name) == 'n' for name in DEVICE_DISABLED),
        'device-original-disabled-config-required')


def device_extracted_inputs(tree, original):
    # The old 32-extra archive authenticator remains byte-exact. These NINE
    # compile-time names are read only from its already SHA/count-verified,
    # privately extracted archive, before any make or source effect.
    expected = set(maintained.manifest()['source']) | {'net/Kconfig', 'net/Makefile'} | set(packet_source.fixture()['source'])
    require(set(original) == expected, 'device-original-archive-membership')
    missing = set(device_source.fixture()['source']) - set(original)
    require(missing == device_source.EXTRAS and len(missing) == 9, 'device-fixed-extracted-membership')
    selected = dict(original)
    for name in sorted(missing):
        selected[name] = paths.read(tree, name, maintained.MAX_FILE)
    require(sum(map(len, selected.values())) <= maintained.MAX_SELECTED, 'device-total-selected-byte-bound')
    device_source.authenticate({name: selected[name] for name in device_source.fixture()['source']})
    return selected


def firmware_extracted_inputs(tree, original):
    # The original acquisition and nine-device-path extension stay unchanged.
    # These THIRTEEN fixed names belong to the SAME whole authenticated archive;
    # they cannot expand acquisition limits or come from a different path/source.
    expected = (set(maintained.manifest()['source']) | {'net/Kconfig', 'net/Makefile'} |
        set(packet_source.fixture()['source']) | set(device_source.EXTRAS))
    require(set(original) == expected, 'firmware-original-archive-membership')
    missing = set(firmware_source.fixture()['source']) - set(original)
    require(missing == set(FIRMWARE_EXTRACTED) == firmware_source.EXTRAS and
        len(missing) == 13, 'firmware-fixed-extracted-membership')
    selected = dict(original)
    for name in FIRMWARE_EXTRACTED:
        selected[name] = paths.read(tree, name, maintained.MAX_FILE)
    require(sum(map(len, selected.values())) <= maintained.MAX_SELECTED, 'firmware-total-selected-byte-bound')
    firmware_source.authenticate({name: selected[name] for name in firmware_source.fixture()['source']})
    return selected


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'regular-product-required')
    with path.open('rb') as stream:
        return {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}


def run(archive, output, *, netlabel=False, netport=False, sidcache=False, avc=False, audit=False, bind=False, route=False, route_cache=False, packet=False, device=False, firmware=False):
    selected_objects = object_selection(netlabel, netport, sidcache, avc, audit, bind, route, route_cache, packet, device, firmware)
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
    if netlabel or netport or sidcache or avc or audit or bind or route or route_cache or packet or device or firmware:
        recipe = packet_source if packet or device or firmware else route_cache_source if route_cache else route_source if route else bind_source if bind else audit_source if audit else avc_source if avc else sidcache_source if sidcache else netport_source if netport else netlabel_source
        additional_sources += tuple(name for name in recipe.fixture()['source'] if name not in value['source'])
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
        if firmware:
            original = device_extracted_inputs(tree, original)
            original = firmware_extracted_inputs(tree, original)
            derived = firmware_source.derive({name: original[name] for name in firmware_source.fixture()['source']})
            receipt['profile'] = 'nodefixed-cached-acpi-companion-source'
            receipt['postExtractionDeviceArchiveSources'] = sorted(device_source.EXTRAS)
            receipt['postExtractionFirmwareArchiveSources'] = list(FIRMWARE_EXTRACTED)
            receipt['deviceEnumerationSourceImplemented'] = True
            receipt['cachedFirmwareReferenceSourceImplemented'] = True
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
            receipt['actualPortOrTimewaitExecuted'] = False
            receipt['actualRouteOrXfrmExecuted'] = False
            receipt['actualParentCacheDrainExecuted'] = False
            receipt['actualPacketExchangeExecuted'] = False
            receipt['actualRxDmaExecuted'] = False
            receipt['actualDeviceInitialized'] = False
            receipt['actualFirmwareExecuted'] = False
            receipt['completeFirmwareClosure'] = False
            receipt['sharedHotplugQueuePhysicalAccountingQualified'] = False
            receipt['trustedNativeBootstrapAuthenticated'] = False
            receipt['actualRodataPlacementProved'] = False
            receipt['actualPciIovExecuted'] = False
            receipt['finalFreeCertified'] = False
        elif device:
            original = device_extracted_inputs(tree, original)
            derived = device_source.derive({name: original[name] for name in device_source.fixture()['source']})
            receipt['profile'] = 'nodefixed-pci-enumeration-source'
            receipt['postExtractionDeviceArchiveSources'] = sorted(device_source.EXTRAS)
            receipt['deviceEnumerationSourceImplemented'] = True
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
            receipt['actualPortOrTimewaitExecuted'] = False
            receipt['actualRouteOrXfrmExecuted'] = False
            receipt['actualParentCacheDrainExecuted'] = False
            receipt['actualPacketExchangeExecuted'] = False
            receipt['actualRxDmaExecuted'] = False
            receipt['actualDeviceInitialized'] = False
            receipt['trustedNativeBootstrapAuthenticated'] = False
            receipt['actualRodataPlacementProved'] = False
            receipt['actualPciIovExecuted'] = False
            receipt['finalFreeCertified'] = False
        elif packet:
            derived = packet_source.derive({name: original[name] for name in packet_source.fixture()['source']})
            receipt['profile'] = 'linear-copied-tcp-packet-source'
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['linearCopiedPacketSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
            receipt['actualPortOrTimewaitExecuted'] = False
            receipt['actualRouteOrXfrmExecuted'] = False
            receipt['actualParentCacheDrainExecuted'] = False
            receipt['actualPacketExchangeExecuted'] = False
            receipt['actualRxDmaExecuted'] = False
            receipt['finalFreeCertified'] = False
        elif route_cache:
            derived = route_cache_source.derive({name: original[name] for name in route_cache_source.fixture()['source']})
            receipt['profile'] = 'ipv4-route-cache-parent-source'
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
            receipt['actualPortOrTimewaitExecuted'] = False
            receipt['actualRouteOrXfrmExecuted'] = False
            receipt['actualParentCacheDrainExecuted'] = False
        elif route:
            derived = route_source.derive({name: original[name] for name in route_source.fixture()['source']})
            receipt['profile'] = 'ipv4-route-owner-source'
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
            receipt['actualPortOrTimewaitExecuted'] = False
            receipt['actualRouteOrXfrmExecuted'] = False
        elif bind:
            derived = bind_source.derive({name: original[name] for name in bind_source.fixture()['source']})
            receipt['profile'] = 'bind-bucket-owner-source'
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
            receipt['actualPortOrTimewaitExecuted'] = False
        elif audit:
            derived = audit_source.derive({name: original[name] for name in audit_source.fixture()['source']})
            receipt['profile'] = 'mandatory-audit-owner-source'
            receipt['mandatoryAuditSourceImplemented'] = True
            receipt['actualAuditExecuted'] = False
            receipt['actualLinuxRcuExecuted'] = False
        elif avc:
            derived = avc_source.derive({name: original[name] for name in avc_source.fixture()['source']})
            receipt['profile'] = 'avc-nested-owner-source'
        elif sidcache:
            derived = sidcache_source.derive({name: original[name] for name in sidcache_source.fixture()['source']})
            receipt['profile'] = 'sidcache-audit-string-owner-source'
        elif netport:
            derived = netport_source.derive({name: original[name] for name in netport_source.fixture()['source']})
            receipt['profile'] = 'netport-cache-owner-source'
        else:
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
        if netlabel or netport or sidcache or avc or audit or bind or route or route_cache or packet or device or firmware:
            netlabel_configuration(before, configuration(final))
            receipt['netlabelEnabledBeforeAndAfter'] = True
        if sidcache or avc or audit or bind or route or route_cache or packet or device or firmware:
            sidcache_configuration(before, configuration(final))
            receipt['sidcacheOriginalEntries'] = 256
        if audit or bind or route or route_cache or packet or device or firmware:
            audit_configuration(before, configuration(final))
            receipt['auditEnabledBeforeAndAfter'] = list(AUDIT_REQUIRED)
        if route or route_cache or packet or device or firmware:
            route_configuration(before, configuration(final))
            receipt['routeXfrmEnabledBeforeAndAfter'] = True
            receipt['routeTrackerAndLwtOriginallyDisabled'] = True
        if device or firmware:
            device_configuration(before, configuration(final))
            receipt['deviceRequiredBeforeAndAfter'] = list(DEVICE_REQUIRED)
            receipt['deviceDisabledBeforeAndAfter'] = list(DEVICE_DISABLED)
        (output / 'selected.config').write_bytes(final)
        receipt['configuration'] = {'baseline': identity(output / 'baseline.config'),
            'selected': identity(output / 'selected.config'), 'onlyChangedSymbol': SELECTED,
            'securityAndInetPreserved': list(REQUIRED)}
        receipt['compiler'] = compiler
        paths.write_new(output / 'selection.json', (json.dumps(receipt, indent=2)+'\n').encode())
        stage = 'thirty-seven-firmware-objects' if firmware else 'thirty-two-device-objects' if device else 'twenty-seven-packet-objects' if packet else 'twenty-four-route-cache-objects' if route_cache else 'twenty-four-route-objects' if route else 'twenty-two-bind-objects' if bind else 'twenty-audit-objects' if audit else 'sixteen-avc-objects' if avc else 'fifteen-sidcache-objects' if sidcache else 'fourteen-netport-objects' if netport else 'twelve-netlabel-objects' if netlabel else 'six-objects'
        commands.run('thirty-seven-selected-real-kbuild-objects' if firmware else 'thirty-two-selected-real-kbuild-objects' if device else 'twenty-seven-selected-real-kbuild-objects' if packet else 'twenty-four-selected-real-kbuild-objects' if route or route_cache else 'twenty-two-selected-real-kbuild-objects' if bind else 'twenty-selected-real-kbuild-objects' if audit else 'sixteen-selected-real-kbuild-objects' if avc else 'fifteen-selected-real-kbuild-objects' if sidcache else 'fourteen-selected-real-kbuild-objects' if netport else 'twelve-selected-real-kbuild-objects' if netlabel else 'six-selected-real-kbuild-objects',
                     *common, '-j2', *selected_objects)
        autoconf = (build / 'include/generated/autoconf.h').read_bytes()
        require(all(('#define '+name+' 1\n').encode() in autoconf for name in (*REQUIRED, SELECTED)),
            'generated-private-or-security-code-disabled')
        if netlabel or netport or sidcache or avc or audit or bind or route or route_cache or packet or device or firmware:
            require(b'#define CONFIG_NETLABEL 1\n' in autoconf, 'netlabel-generated-code-disabled')
        if sidcache or avc or audit or bind or route or route_cache or packet or device or firmware:
            require(b'#define CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE 256\n' in autoconf,
                    'sidcache-generated-profile-disabled')
        if audit or bind or route or route_cache or packet or device or firmware:
            require(all(('#define '+name+' 1\n').encode() in autoconf for name in AUDIT_REQUIRED),
                    'audit-generated-code-disabled')
        if route or route_cache or packet or device or firmware:
            require(b'#define CONFIG_XFRM 1\n' in autoconf and
                b'#define CONFIG_NET_DEV_REFCNT_TRACKER ' not in autoconf and
                b'#define CONFIG_LWTUNNEL ' not in autoconf, 'route-generated-profile-drift')
        if device or firmware:
            require(all(('#define '+name+' 1\n').encode() in autoconf for name in DEVICE_REQUIRED),
                'device-generated-code-disabled')
            require(all(('#define '+name+' ').encode() not in autoconf for name in DEVICE_DISABLED),
                'device-generated-disabled-code-drift')
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
    parser.add_argument('--netport', action='store_true', help='select the closed port-cache object-only profile')
    parser.add_argument('--sidcache', action='store_true', help='select the closed SID-cache and audit-string object-only profile')
    parser.add_argument('--avc', action='store_true', help='select the closed AVC with SID-cache object-only profile')
    parser.add_argument('--audit', action='store_true', help='select the closed mandatory audit and SKB object-only profile')
    parser.add_argument('--bind', action='store_true', help='select the closed bind-bucket and mandatory audit object-only profile')
    parser.add_argument('--route', action='store_true', help='select the closed IPv4 route and original-reference object-only profile')
    parser.add_argument('--route-cache', action='store_true', help='select the closed route-cache parent and drain object-only profile')
    parser.add_argument('--packet', action='store_true', help='select the closed linear copied-TCP packet object-only profile')
    parser.add_argument('--device', action='store_true', help='select the closed NodeFixed PCI birth and constant-name object-only profile')
    parser.add_argument('--firmware', action='store_true', help='select the closed cached-ACPI companion lifetime object-only profile')
    args = parser.parse_args()
    run(args.archive.resolve(strict=True), args.output, netlabel=args.netlabel, netport=args.netport, sidcache=args.sidcache, avc=args.avc, audit=args.audit, bind=args.bind, route=args.route, route_cache=args.route_cache, packet=args.packet, device=args.device, firmware=args.firmware)
