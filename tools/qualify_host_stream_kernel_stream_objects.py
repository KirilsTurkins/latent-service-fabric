#!/usr/bin/env python3
"""One fixed hosted C object check; no image, boot, consumer or qualification."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE = '013c3866942f1654b0effeebc93986b1c5268c2c'
BASELINE_TREE = 'ee776dfd184e4f3128561ba5213f95988962c98e'
CHECKPOINT = 'a92632a589ceb4db69207f9d6ff5dba286b8eaa5'
BRANCH = 'test/sdk-738-stream-objects-20261026'
WORKFLOW = '.github/workflows/stream-provider-objects.yml'
SOURCE_PATHS = ('research/standard-outbound/linux-6.12-lineage/device-prepaid.h', 'research/standard-outbound/linux-6.12-lineage/factory-stream-find-vqs.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-material-arena.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-material-plan.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-address.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-core.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-cpu.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-fixed.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-name.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-operations.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-retirement.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-root-final-free.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-rss.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-rx-preallocate.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-stop.c', 'research/standard-outbound/linux-6.12-lineage/factory-stream-udp-cork.c', 'research/standard-outbound/linux-6.12-lineage/stream-material-geometry-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-net-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-net-material-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-core-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-cpu-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-cpu.c', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-geometry-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-fixed-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-name-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-netdev-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-operation-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-owned-ring.c', 'research/standard-outbound/linux-6.12-lineage/stream-pci-material-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-protocol-allocation.c', 'research/standard-outbound/linux-6.12-lineage/stream-ring-geometry.c', 'research/standard-outbound/linux-6.12-lineage/stream-ring-profile-private.h', 'research/standard-outbound/linux-6.12-lineage/stream-skb-dispatch.c', 'research/standard-outbound/linux-6.12-lineage/stream-udp-cork-private.c', 'research/standard-outbound/linux-6.12-lineage/stream-udp-private.c', 'tools/host_stream_kernel_stream_core.py', 'tools/host_stream_kernel_stream_cpu.py', 'tools/host_stream_kernel_stream_fixed_netdev.py', 'tools/host_stream_kernel_stream_name.py', 'tools/host_stream_kernel_stream_netdev.py', 'tools/host_stream_kernel_stream_operations.py', 'tools/host_stream_kernel_stream_protocol.py', 'tools/host_stream_kernel_stream_rss_failure.py', 'tools/host_stream_kernel_stream_rx.py', 'tools/host_stream_kernel_stream_skb.py', 'tools/host_stream_kernel_stream_udp.py')
SOURCE_SHA = '0d297733d0d376b952cafd03ae8e4c9477b979e5afd90d79d53e938ef34e4397'
SOURCE_BYTES = 337639
CLASSDIR_SOURCE_PATHS = tuple(sorted((*SOURCE_PATHS,
    'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-classdir.c',
    'research/standard-outbound/linux-6.12-lineage/stream-netdev-classdir-private.h',
    'tools/host_stream_kernel_stream_classdir.py',
)))
CLASSDIR_SOURCE_SHA = 'c0245686c1c5c5217c778215a151888a853d1ec21f15a2a372330ad7693aedca'
CLASSDIR_SOURCE_BYTES = 367882
CLASSDIR_BRANCH = 'test/sdk-738-classdir-objects-20261026'
CLASSDIR_TARGETS = ('net/factory.o','drivers/base/core.o','lib/kobject.o','net/core/net-sysfs.o')
REGISTRATION_SOURCE_PATHS = tuple(sorted((*CLASSDIR_SOURCE_PATHS,
    'research/standard-outbound/linux-6.12-lineage/factory-stream-classdir-registration.c',
    'research/standard-outbound/linux-6.12-lineage/stream-classdir-registration-private.h',
)))
REGISTRATION_SOURCE_SHA = '6784ec02a37b8c845edaab608f086ac7950ffb9e8afd5de36ce54fc2e90a8fdd'
REGISTRATION_SOURCE_BYTES = 415655
REGISTRATION_BRANCH = 'test/sdk-738-classdir-kernfs-objects-20261026'
REGISTRATION_TARGETS = ('net/factory.o','drivers/base/core.o','lib/kobject.o',
    'fs/sysfs/dir.o','fs/kernfs/dir.o','lib/idr.o','lib/radix-tree.o',
    'security/security.o','security/selinux/hooks.o')
DIRECTORY_SOURCE_PATHS = tuple(sorted((*REGISTRATION_SOURCE_PATHS,
    'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-directory.c',
    'research/standard-outbound/linux-6.12-lineage/stream-netdev-directory-private.h',
    'tools/host_stream_kernel_stream_netdev_directory.py',
)))
DIRECTORY_SOURCE_SHA = '4a84771d1697ca00215256d1ea50f5edd7b442cd258fb862053f0a7cd2297f38'
DIRECTORY_SOURCE_BYTES = 464637
DIRECTORY_DERIVED_SHA = 'c30c57f07a10aefb5ad736bb6362f002b5110292b2be0305cf685dd76c5a7147'
DIRECTORY_BRANCH = 'test/sdk-738-netdev-directory-objects-20261026'
# These are precisely the nine changed compiler TUs (two new files are included
# by net/factory.c and the existing header consumers, not separate objects).
DIRECTORY_TARGETS = REGISTRATION_TARGETS
CHECKPOINT45_SHA = '1ec18c5c933a74a8378cfa0da8893cb6612a84d6e14f02614a769365f6b30f62'
NOTIFY_SOURCE_PATHS = tuple(sorted((*DIRECTORY_SOURCE_PATHS,
    'tools/host_stream_kernel_stream_netdev_notify.py',
    'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-notify.c',
    'research/standard-outbound/linux-6.12-lineage/stream-netdev-notify-private.h')))
NOTIFY_SOURCE_SHA = '45264bcdf2c038a38dcdd1da2ecab1a1ba0523c075bf5e48fad821e4b06a316f'
NOTIFY_SOURCE_BYTES = 487700
NOTIFY_DERIVED_SHA = '8c34faa41636437aeeca9602af1dd63b1b251354a69b25c7c5745e63e20fb677'
LAYOUT_SOURCE_PATHS = tuple(sorted((*NOTIFY_SOURCE_PATHS,'tools/host_stream_kernel_stream_layout.py')))
LAYOUT_SOURCE_SHA = '3a978598c09bfdf44846bb8009345d2bf4a4d76799ac2b43c3bcfec5674d8d19'
LAYOUT_SOURCE_BYTES = 515419
LAYOUT_DERIVED_SHA = '177ea9d8a3e32ad77f5a081c82538bbcaaeccf957553e899986d9215889a04d7'
LAYOUT_BRANCH = 'test/sdk-738-netdev-layout-objects-20261026'
LAYOUT_TARGETS = ('drivers/net/virtio_net.o','drivers/virtio/virtio_ring.o','net/core/dev.o',
    'net/factory.o','drivers/base/core.o','fs/kernfs/dir.o','security/selinux/hooks.o',
    'drivers/virtio/virtio_pci_common.o','drivers/acpi/glue.o','drivers/base/swnode.o',
    'drivers/usb/core/usb-acpi.o')

POST_INIT_SOURCE_PATHS = tuple(sorted((*LAYOUT_SOURCE_PATHS,
    'tools/host_stream_kernel_stream_post_init.py',
    'research/standard-outbound/linux-6.12-lineage/factory-stream-netdev-post-init.c',
    'research/standard-outbound/linux-6.12-lineage/stream-netdev-post-init-private.h')))
POST_INIT_SOURCE_SHA = 'd52dcf0ce66a21ec460c38c5e9bc04059e70caa272cd06b5ae2292e588b56f00'
POST_INIT_SOURCE_BYTES = 534589
POST_INIT_DERIVED_SHA = '0f3276228e4952a8ffed4ddd725022db50aa7e6c6f28086c12f81f46aed88637'
POST_INIT_BRANCH = 'test/sdk-738-netdev-post-init-objects-20261026'
POST_INIT_TARGETS = ('net/core/dev.o','drivers/net/virtio_net.o','net/ipv4/fib_frontend.o',
    'net/factory.o','net/ipv4/devinet.o','net/ipv6/addrconf.o','net/core/rtnetlink.o',
    'drivers/virtio/virtio.o')

# New cumulative physical source freeze, distinct from all dated raw tuples.
CONSTRUCTOR_MMIO_SOURCE_PATHS = tuple(sorted((*POST_INIT_SOURCE_PATHS,
    'tools/host_stream_kernel_stream_constructor.py',
    'tools/host_stream_kernel_stream_vwindow.py',
    'research/standard-outbound/linux-6.12-lineage/stream-constructor-sources.json')))
CONSTRUCTOR_MMIO_SOURCE_SHA = 'c82f02df5177559c573e21fa4b068b7e4dbfba00aecd43c1fb779b53f69b0adb'
CONSTRUCTOR_MMIO_SOURCE_BYTES = 827370
CONSTRUCTOR_MMIO_ADDED_LIMITS = {
    'tools/host_stream_kernel_stream_constructor.py':73498,
    'tools/host_stream_kernel_stream_vwindow.py':37074,
    'research/standard-outbound/linux-6.12-lineage/stream-constructor-sources.json':182209}
CONSTRUCTOR_MMIO_LOGICAL_SHA = '9eb7fe5dd786082feaca723ffcff9c4ff6bf5f52e7e7e9350737894a4651c4e0'
CONSTRUCTOR_MMIO_BRANCH = 'test/sdk-738-constructor-mmio-objects-20261027'
CONSTRUCTOR_MMIO_TARGETS = ('net/factory.o', 'drivers/base/dd.o', 'drivers/pci/bus.o', 'drivers/pci/pci-driver.o', 'drivers/pci/pci-sysfs.o', 'drivers/pci/pci.o', 'drivers/pci/proc.o', 'drivers/pci/iomap.o', 'drivers/virtio/virtio.o', 'drivers/virtio/virtio_pci_common.o', 'drivers/virtio/virtio_pci_modern_dev.o', 'drivers/net/virtio_net.o', 'kernel/resource.o', 'arch/x86/mm/pat/memtype.o', 'arch/x86/mm/pat/memtype_interval.o', 'arch/x86/mm/ioremap.o', 'mm/vmalloc.o', 'lib/kobject.o', 'lib/idr.o', 'lib/radix-tree.o', 'fs/proc/generic.o', 'fs/proc/inode.o')
CONSTRUCTOR_MMIO_DERIVED = (
    ('constructor-admission',398,'f9820d0e9a9d9d0eedeb469c6fe03556ba25d09be91932da5b2b31ee255d5df9'),
    ('constructor-resource-pat',407,'6741a2f5cf10b1810dbe7d78d64cb65f326071a9fccdcf7fc0abbc4c5c1a02c6'),
    ('constructor-vwindow',410,'1f802d58d9912ee5e03ab4d7ecfd9279e6be4afe64dc6c28d8fda753ccd0a496'),
    ('constructor-ancestors',414,'aec9bff62f308b66acd801067c55798b1adf0afed994317288d944b906337b11'),
    ('constructor-leaf',417,'4df5a1974e6d0ba7f568d64962f02c57aac7b85b076ae7f3bd9e8407bb4013dc'),
    ('constructor-mmio',427,'17fb144ef54af90af8ac9c338bcf7315f702bea92049dfcbe1da37e20a9db0a0'))

CONFIG = {'bytes':143135, 'sha256':'0015c9ac3b9af98af1e4a0f88788321e96193ce6a387c5a6cec6eaa358cdc1d6'}
TARGETS = ('net/factory.o','net/socket.o','net/core/sock.o','net/ipv4/af_inet.o',
    'net/ipv6/af_inet6.o','net/ipv4/ip_output.o','net/ipv4/route.o','net/core/dev.o',
    'net/core/dev_addr_lists.o','net/core/net-sysfs.o','net/core/skbuff.o','net/ethernet/eth.o',
    'drivers/net/virtio_net.o','drivers/virtio/virtio_ring.o','drivers/virtio/virtio_pci_common.o',
    'drivers/virtio/virtio_pci_modern.o','drivers/base/core.o','lib/kobject.o')
MAX_PUBLIC, MAX_DOCUMENT, MAX_OBJECT = 128*1024**2, 1024**2, 16*1024**2
MAX_SOURCE, MAX_FILE, MAX_ENTRIES = 16*1024**2, 4*1024**2, 512
MAX_COMMANDS = 32
STAGES = ('source-head','source-tree','source-clean','baseline-object','baseline-tree',
    'baseline-worktree','baseline-head','baseline-clean-before','baseline-clean-after',
    'baseline-tree-after','locked-python-dependencies','normal-prerequisite-update',
    'normal-prerequisite-install','gcc-version','make-version','as-version','ld-version',
    'rustc-version','official-source','extract-source','original-defconfig','selected-olddefconfig',
    'pure-baseline','eighteen-objects','classdir-objects','source-clean-after','source-tree-after','source-head-after')
REGISTRATION_STAGES = (*STAGES,'baseline-fetch','classdir-kernfs-objects')
DIRECTORY_STAGES = (*tuple(s for s in REGISTRATION_STAGES if s not in
    {'eighteen-objects','classdir-objects','classdir-kernfs-objects'}),'netdev-directory-objects')
LAYOUT_STAGES = (*tuple(s for s in DIRECTORY_STAGES if s!='netdev-directory-objects'),'netdev-layout-objects')
POST_INIT_STAGES = (*tuple(s for s in DIRECTORY_STAGES if s!='netdev-directory-objects'),'netdev-post-init-objects')
CONSTRUCTOR_MMIO_STAGES = (*tuple(s for s in DIRECTORY_STAGES if s!='netdev-directory-objects'),'constructor-mmio-objects')
DOCUMENTS = {'receipt.json':MAX_DOCUMENT,'source-inputs.json':16*MAX_DOCUMENT,
    'derived-inputs.json':4*MAX_DOCUMENT,'baseline-inputs.json':16*MAX_DOCUMENT,
    'commands.json':MAX_DOCUMENT,'baseline.config':MAX_DOCUMENT,'selected.config':MAX_DOCUMENT,
    'generated-autoconf.h':MAX_DOCUMENT}



# Separate current VP stage; all dated constructor source/mode constants above
# remain immutable. New execution files are pinned outside their own reader.
VP_BRANCH = 'test/sdk-738-vp-transport-objects-20261027'
VP_ADDED_PINS = {
    'tools/host_stream_kernel_vp_transport.py': (7753, '75e8badd708595c5bf91e554f5b7726bb0ce509697e01919ec29a739b5b0d097'),
    'research/standard-outbound/linux-6.12-lineage/stream-vp-transport-sources.json':
        (26247, '9944ebe14f466f6a02e52d574f1ce86d79bc3f73ea32905bb705b689a5a1da58')}
VP_PHYSICAL_SHA = 'ba53e8b7d08b03c15e743bd521189469c6c5cfb375d9485ba9bd17c35014df54'
VP_PHYSICAL_BYTES = 861370
VP_LOGICAL_SHA = '3ce0a7679df01a4ac357000bf2cd73225288cf1b79a75f16c905e4dfdbb920af'
VP_DERIVED_SHA = '0768391742d6748633a9af27da9c5f60430ff37ecca83f74d8d1b60b20ac8441'
VP_TARGETS = CONSTRUCTOR_MMIO_TARGETS
VP_STAGES = tuple('vp-transport-objects' if stage=='constructor-mmio-objects' else stage
    for stage in CONSTRUCTOR_MMIO_STAGES)


# Separate closed MSI prefix; historical VP67/94/430 remains immutable.
MSI_BRANCH = 'test/sdk-738-msi-context-objects-20261027'
MSI_ADDED_PINS = {'tools/host_stream_kernel_msi_context.py': (11421, '61861cb7fdc59fb644a1d666e4de89cc15226eb3d3a0b2dc458129e166a0daa9'), 'research/standard-outbound/linux-6.12-lineage/stream-msi-context-sources.json': (25294, 'fe53902ca7a2b9546abea71797613790addb75fec030bc7d04972ec26749cf42')}
MSI_PHYSICAL_SHA = 'edef0dac800ead7ad1a684bf395e7b0fdc51a2240e06a6e18469d7df52baac49'
MSI_PHYSICAL_BYTES = 898085
MSI_LOGICAL_SHA = '9d3bec2cf79dd75624a8ef5f7e15a44ba30753aea0445a66ba8ab723a5fd6434'
MSI_DERIVED_SHA = '926cbb1c339cf059b8e18f9da2b397edce740e2b56142a6b643243f5151d326b'
MSI_TARGETS = ('kernel/irq/msi.o','drivers/base/devres.o','drivers/base/core.o',
    'drivers/pci/msi/irqdomain.o','fs/sysfs/group.o','net/factory.o')
MSI_STAGES = tuple('msi-context-objects' if stage=='constructor-mmio-objects' else stage
    for stage in CONSTRUCTOR_MMIO_STAGES)


# New direct-vector child-domain/table mode; dated MSI69/100/439 stays exact.
Q35_BRANCH = 'test/sdk-738-q35-msi-domain-objects-20261027'
Q35_MODULE = 'research/standard-outbound/linux-6.12-lineage/q35-msi/projector.py'
Q35_PINS = {'research/standard-outbound/linux-6.12-lineage/q35-msi/projector.py': (12287, '8b5b99144e29e0235a7d5c729431f3ec57b4d214bf4a5fdd5467af37707a7f9a'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-msi-parent.c': (727, '48a6a08199e571f270250009e5e6499728b54c9132e73f17eb677a2beed7317d'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-vector.c': (245, 'b4fd06a4e1c7fc0ad28c22be89cc62bae4433e3faeac6e83e4866db3307bd289'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-table.c': (4238, '7f529fc8a21eea42b510029a25691b6f081ca955d0bacca3be005172a90ecafc'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-template.c': (210, 'a4c6f19f41bd6cffe1a40c3c37270a745c10079d05a05ee74e2e16819dda22ba'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf_stream_q35_msi_private.h': (2566, '79ba3712b1dfe5c89e1a5085d6e6593861aed3c9f795878eba0b2294448f9889'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-domain.c': (10375, '1e70a5f85018dc0adcb6a0150cf041026442a4d9626671b421f914abcf4ae23b'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/lsf-stream-q35-msi.c': (7276, '0c3ca78cc13032f8e9d0075f7bb889c9a70bc330cdc0beb2127921208af7653a'), 'research/standard-outbound/linux-6.12-lineage/q35-msi/factory-stream-q35-msi.c': (11271, '20ed7fe146a97bc545e963e807920db421c9b42e94ae7d46fca81b478a4a7eae')}
Q35_PHYSICAL_SHA = 'a0e7b990eecf947a8028d534e884c6f80bac70d96ac4722356b191372ef01a28'
Q35_PHYSICAL_BYTES = 947280
Q35_LOGICAL_SHA = 'a1e5cdca109709a447b8d12c0d2ea2d1b198e5b1eee384a512ffab736685a817'
Q35_DERIVED_SHA = 'ca7d71dce015fe73d00d389ba196d8411cd32a16580d1fe04b39aee5b7425cda'
Q35_TARGETS = ('kernel/irq/msi.o','kernel/irq/irqdomain.o','drivers/pci/msi/msi.o',
    'drivers/pci/msi/irqdomain.o','arch/x86/kernel/apic/msi.o',
    'arch/x86/kernel/apic/vector.o','net/factory.o')
Q35_STAGES = tuple('q35-msi-domain-objects' if s=='msi-context-objects' else s for s in MSI_STAGES)


# Closed descriptor/device-XArray prefix; historical Q35 remains exact.
MSI_DESCRIPTOR_BRANCH = 'test/sdk-738-msi-descriptor-objects-20261027'
MSI_DESCRIPTOR_MODULE = 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/projector.py'
MSI_DESCRIPTOR_PINS = {'research/standard-outbound/linux-6.12-lineage/msi-descriptor/projector.py': (12029, 'b1801e7b1a8a350054098e935d4ab34d4f8c8d57c2dbe9d9e5d6efdb6f5205e9'), 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf-stream-msi-descriptor.c': (5728, '099950aa9e5c88f6758b2c48568a219c20dfe5101b7baec75025635754bc42b5'), 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf-stream-msi-xarray.c': (4414, '09e4c0998d9d0d30551df5c1d01e97f6377fb7c2ab66186d472fe43b5fd34b86'), 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/factory-stream-msi-descriptor.c': (18511, '2c675f2606b9aa3f237593528bc62c751573819d6e27bb20621ab380d877a954'), 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf_stream_msi_descriptor_private.h': (1800, 'e26a1b1a11207344a76be4516a7edf1e1b36dada7c1f71851de07b2c54ba468d')}
MSI_DESCRIPTOR_MATERIAL_PATHS = {'kernel/irq/lsf-stream-msi-descriptor.c': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf-stream-msi-descriptor.c', 'lib/lsf-stream-msi-xarray.c': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf-stream-msi-xarray.c', 'net/factory-stream-msi-descriptor.c': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/factory-stream-msi-descriptor.c', 'include/net/lsf_stream_msi_descriptor_private.h': 'research/standard-outbound/linux-6.12-lineage/msi-descriptor/lsf_stream_msi_descriptor_private.h'}
MSI_DESCRIPTOR_PHYSICAL_SHA = '10748554a3dffbc68ac47bdec7fdcf8cf6b3a20fb222b5104a25e6b294839e4b'
MSI_DESCRIPTOR_PHYSICAL_BYTES = 989762
MSI_DESCRIPTOR_LOGICAL_SHA = '7249adcaa4e0711aa7c68327dcdebd4c4752ea3c6d8cb8ce064f3db643614cbb'
MSI_DESCRIPTOR_DERIVED_SHA = '00c140d029413ea9acfbf31f19504073b3c3a499e248599a958245ae16b85bba'
MSI_DESCRIPTOR_NATIVE_PINS = {'lib/xarray.c': (61079, 'b35b4f31434c62d4dfb08a65b5df8074cc55011d6814d4980b6444f8234ecf7a'), 'include/linux/xarray.h': (59453, '3b98cad8f1a4234b7520720819012bc1344dfa4b0df16b215df7c994d798eb36')}
MSI_DESCRIPTOR_TARGETS = ('kernel/irq/msi.o', 'drivers/pci/msi/irqdomain.o', 'drivers/pci/msi/msi.o', 'lib/xarray.o', 'lib/radix-tree.o', 'net/factory.o')
MSI_DESCRIPTOR_STAGES = tuple('msi-descriptor-objects' if s=='q35-msi-domain-objects' else s for s in Q35_STAGES)


def require(value, code):
    if not value:
        raise ValueError('stream-object-'+code)


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()


def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def read(path, maximum):
    require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode), 'regular-input')
    with path.open('rb') as stream:
        raw=stream.read(maximum+1)
    require(len(raw)<=maximum, 'input-bound')
    return raw


def write_json(path, value, maximum=16*MAX_DOCUMENT):
    raw=canonical(value)
    require(len(raw)<=maximum,'document-bound')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)


def deadline(started, now=None):
    now=time.monotonic() if now is None else now
    require(type(started) is float and math.isfinite(started) and 0<=started<=now,
        'original-start')
    end=started+1320.0
    require(now<end-5.0,'original-deadline')
    return end


def mode_targets(classdir=False, classdir_kernfs=False, netdev_directory=False, netdev_layout=False, netdev_post_init=False, constructor_mmio=False, vp_transport=False, msi_context=False, q35=False, msi_descriptor=False):
    require(all(type(value) is bool for value in
        (classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init,constructor_mmio,vp_transport,msi_context,q35,msi_descriptor)) and
        sum((classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init,constructor_mmio,vp_transport,msi_context,q35,msi_descriptor))<=1,'closed-classdir-mode')
    return MSI_DESCRIPTOR_TARGETS if msi_descriptor else Q35_TARGETS if q35 else MSI_TARGETS if msi_context else VP_TARGETS if vp_transport else CONSTRUCTOR_MMIO_TARGETS if constructor_mmio else POST_INIT_TARGETS if netdev_post_init else LAYOUT_TARGETS if netdev_layout else DIRECTORY_TARGETS if netdev_directory else REGISTRATION_TARGETS if classdir_kernfs else CLASSDIR_TARGETS if classdir else TARGETS


def selected_sources(root, *, classdir=False, classdir_kernfs=False, netdev_directory=False, netdev_layout=False, netdev_post_init=False, constructor_mmio=False):
    mode_targets(classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init,constructor_mmio)
    if constructor_mmio:
        require(len(CONSTRUCTOR_MMIO_SOURCE_PATHS)==len(set(CONSTRUCTOR_MMIO_SOURCE_PATHS))==65,
            'constructor-physical-path-count')
        rows={name:identity(read(root/name,CONSTRUCTOR_MMIO_ADDED_LIMITS.get(name,65536)))
            for name in CONSTRUCTOR_MMIO_SOURCE_PATHS}
        require(sum(row['bytes'] for row in rows.values())==CONSTRUCTOR_MMIO_SOURCE_BYTES and
            hashlib.sha256(canonical(rows)).hexdigest()==CONSTRUCTOR_MMIO_SOURCE_SHA,
            'frozen-65-constructor-physical-source')
        historical={name:rows[name] for name in POST_INIT_SOURCE_PATHS}
        require(len(historical)==62 and sum(row['bytes'] for row in historical.values())==POST_INIT_SOURCE_BYTES and
            hashlib.sha256(canonical(historical)).hexdigest()==POST_INIT_SOURCE_SHA,
            'historical-62-post-init-source-exact')
        return rows
    paths = POST_INIT_SOURCE_PATHS if netdev_post_init else LAYOUT_SOURCE_PATHS if netdev_layout else DIRECTORY_SOURCE_PATHS if netdev_directory else REGISTRATION_SOURCE_PATHS if classdir_kernfs else CLASSDIR_SOURCE_PATHS if classdir else SOURCE_PATHS
    count = 62 if netdev_post_init else 59 if netdev_layout else 55 if netdev_directory else 52 if classdir_kernfs else 50 if classdir else 47
    expected_bytes = POST_INIT_SOURCE_BYTES if netdev_post_init else LAYOUT_SOURCE_BYTES if netdev_layout else DIRECTORY_SOURCE_BYTES if netdev_directory else REGISTRATION_SOURCE_BYTES if classdir_kernfs else CLASSDIR_SOURCE_BYTES if classdir else SOURCE_BYTES
    expected_sha = POST_INIT_SOURCE_SHA if netdev_post_init else LAYOUT_SOURCE_SHA if netdev_layout else DIRECTORY_SOURCE_SHA if netdev_directory else REGISTRATION_SOURCE_SHA if classdir_kernfs else CLASSDIR_SOURCE_SHA if classdir else SOURCE_SHA
    require(len(paths)==len(set(paths))==count,'source-path-count')
    rows={name:identity(read(root/name,65536)) for name in paths}
    require(sum(r['bytes'] for r in rows.values())==expected_bytes and
        hashlib.sha256(canonical(rows)).hexdigest()==expected_sha,'frozen-'+str(count)+'-source')
    if netdev_layout:
        frozen={n:rows[n] for n in NOTIFY_SOURCE_PATHS}
        require(len(frozen)==58 and sum(r['bytes'] for r in frozen.values())==NOTIFY_SOURCE_BYTES and
            hashlib.sha256(canonical(frozen)).hexdigest()==NOTIFY_SOURCE_SHA,'frozen-58-notify-source')
    if netdev_post_init:
        historical={n:rows[n] for n in LAYOUT_SOURCE_PATHS}
        require(len(historical)==59 and sum(r['bytes'] for r in historical.values())==LAYOUT_SOURCE_BYTES and
            hashlib.sha256(canonical(historical)).hexdigest()==LAYOUT_SOURCE_SHA,'historical-59-layout-source-exact')
    return rows


def safe_name(name):
    p=PurePosixPath(name)
    require(type(name) is str and p.as_posix()==name and not p.is_absolute() and
        '..' not in p.parts and '\\' not in name and ':' not in name and name!='.','source-path')
    return name


def derived_write(output, values):
    require(type(values) is dict and 1<=len(values)<=MAX_ENTRIES,'derived-count')
    rows={};total=0
    output.mkdir()
    for name,raw in sorted(values.items()):
        safe_name(name)
        require(type(raw) is bytes and 0<len(raw)<=MAX_FILE,'derived-file-bound')
        total+=len(raw);require(total<=MAX_SOURCE,'derived-total-bound')
        q=output/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        rows[name]=identity(raw)
    return rows


def derived_read(output, rows):
    require(type(rows) is dict and 1<=len(rows)<=MAX_ENTRIES,'derived-count')
    result={};total=0
    for name,bound in sorted(rows.items()):
        safe_name(name);raw=read(output/name,MAX_FILE);total+=len(raw)
        require(total<=MAX_SOURCE and identity(raw)==bound,'derived-bound-identity')
        result[name]=raw
    return result


def input_files(root):
    # Fixed repository source families; these are metadata, never uploaded code.
    paths=set((root/'tools').rglob('*.py'))
    paths.update((root/'tools/tests/fixtures').glob('host_stream_kernel*.json'))
    paths.update(q for q in (root/'research/standard-outbound/linux-6.12-lineage').iterdir()
        if q.is_file())
    paths.add(root/'tools/requirements.lock')
    require(len(paths)<=4096,'recipe-count')
    total=0;result={}
    for q in sorted(paths):
        raw=read(q,MAX_FILE);total+=len(raw);require(total<=128*1024**2,'recipe-total')
        result[q.relative_to(root).as_posix()]=identity(raw)
    return result


def baseline_worker(recipe, tree, config, output):
    # Fresh Python process: no current tools module/global is replaced. Only
    # regular, byte-bound data files cross back to the current controller.
    require(recipe.is_absolute() and tree.is_absolute() and output.is_absolute(),'worker-paths')
    sys.path.insert(0,str(recipe))
    from tools import host_stream_kernel_cleanup_native_programme as programme
    from tools import host_stream_kernel_return_source as source
    from tools import host_stream_kernel_retirement_observation as observation
    objects=programme.baseline.objects
    require(programme.ROOT.resolve()==recipe.resolve(),'worker-original-root')
    before=input_files(recipe)
    actual=read(config,MAX_DOCUMENT);require(identity(actual)==CONFIG,'worker-actual-config')
    manifest=objects.maintained.manifest()
    names=set(manifest['source'])|{'net/Kconfig','net/Makefile'}|set(objects.packet_source.fixture()['source'])
    original={n:objects.paths.read(tree,n,objects.maintained.MAX_FILE) for n in names}
    base,frozen,originals=programme.baseline_source(tree,original)
    for n in sorted(programme.source_names()-{'selected.config'}):
        if n not in originals:originals[n]=objects.paths.read(tree,n,objects.maintained.MAX_FILE)
    require(sum(map(len,originals.values()))<=objects.maintained.MAX_SELECTED,'worker-selected-originals')
    canonical_config,probes=source.compiler_probe_projection(actual)
    fixture,fixture_proof=programme.source_fixture_configuration(canonical_config)
    normal=programme.compose(base,originals,fixture)
    normal=observation.transform(normal)
    rows=derived_write(output/'derived',normal)
    require(before==input_files(recipe),'worker-source-mutated')
    write_json(output/'baseline.json',{'sourceRevision':BASELINE,'tree':BASELINE_TREE,
        'sourceBefore':before,'sourceAfter':before,'normalSourceFreeze':frozen,
        'normalOwnedFreeze':programme.local_freeze(),'actualConfiguration':identity(actual),
        'sourceFixtureConfiguration':fixture_proof,'compilerProbeDataOnly':probes,
        'derived':rows,'compilerInvocations':0,'runtimeInvocations':0,
        'qualificationProjectionApplied':False})


def udp_source(values, tree):
    # This TU is genuinely absent from the original normal derived map. Add
    # ONLY its exact original primary; never reset an already-transformed TU.
    from tools.host_stream_kernel_stream_udp import IP
    require(IP not in values,'fresh-udp-ip-primary')
    raw=read(tree/IP,MAX_FILE)
    require(identity(raw)=={'bytes': 43820, 'sha256': 'f5d4f5dee6e0995e5b82dc53519ba1480026085b9ea14e472c956f7db93c20b8'},'whole-original-udp-ip-primary')
    result=dict(values);result[IP]=raw
    return result


def current_compose(values, tree, *, classdir=False, classdir_kernfs=False, netdev_directory=False, netdev_layout=False, netdev_post_init=False):
    mode_targets(classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init)
    from tools import host_stream_kernel_stream_operations as operations
    from tools import host_stream_kernel_stream_protocol as protocol
    from tools import host_stream_kernel_stream_udp as udp
    from tools import host_stream_kernel_stream_rx as rx
    from tools import host_stream_kernel_stream_netdev as address
    from tools import host_stream_kernel_stream_cpu as cpu
    from tools import host_stream_kernel_stream_fixed_netdev as fixed
    from tools import host_stream_kernel_stream_name as name
    from tools import host_stream_kernel_stream_rss_failure as rss
    from tools import host_stream_kernel_stream_core as core
    values=operations.transform(values)
    values=protocol.transform(values,read(tree/protocol.IPV6,MAX_FILE))
    values=udp.transform(udp_source(values,tree))
    values=rx.transform(values,{n:read(tree/n,MAX_FILE) for n in rx.PREIMAGES})
    values=address.transform(values,read(tree/address.SOURCE,MAX_FILE))
    values=cpu.transform(values,{n:read(tree/n,MAX_FILE) for n in cpu.PREIMAGES})
    values=fixed.transform(values,{n:read(tree/n,MAX_FILE) for n in fixed.PRIMARY})
    values=core.transform(rss.transform(name.transform(values)))
    if classdir or classdir_kernfs or netdev_directory or netdev_layout or netdev_post_init:
        from tools import host_stream_kernel_stream_classdir
        values=host_stream_kernel_stream_classdir.transform(values)
    from tools.host_stream_kernel_stream_skb import finish
    values=finish(values)
    if classdir_kernfs or netdev_directory or netdev_layout or netdev_post_init:
        values=host_stream_kernel_stream_classdir.registration_transform(values)
    if netdev_directory or netdev_layout or netdev_post_init:
        from tools import host_stream_kernel_stream_netdev_directory
        values=host_stream_kernel_stream_netdev_directory.transform(values)
        require(len(values)==371 and hashlib.sha256(canonical({n:identity(raw)
            for n,raw in sorted(values.items())})).hexdigest()==DIRECTORY_DERIVED_SHA,
            'frozen-371-directory-derived')
    if netdev_layout or netdev_post_init:
        from tools import host_stream_kernel_stream_netdev_notify as notify
        values=notify.transform(values,{n:read(tree/n,MAX_FILE) for n in notify.PRIMARY})
        require(len(values)==375 and hashlib.sha256(canonical({n:identity(raw)
            for n,raw in sorted(values.items())})).hexdigest()==NOTIFY_DERIVED_SHA,
            'frozen-375-notify-derived')
    if netdev_layout:
        from tools import host_stream_kernel_stream_layout as layout
        values=layout.transform(values)
        require(len(values)==375 and hashlib.sha256(canonical({n:identity(raw)
            for n,raw in sorted(values.items())})).hexdigest()==LAYOUT_DERIVED_SHA,
            'frozen-375-layout-derived')
    if netdev_post_init:
        from tools import host_stream_kernel_stream_post_init as post_init
        values=post_init.transform(values,{n:read(tree/n,MAX_FILE) for n in post_init.PRIMARY})
        require(len(values)==381 and hashlib.sha256(canonical({n:identity(raw)
            for n,raw in sorted(values.items())})).hexdigest()==POST_INIT_DERIVED_SHA,
            'frozen-381-post-init-derived')
    require(b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in
        values['net/factory-private.h'], 'unselected-consumer')
    return values



def constructor_materials(root):
    physical=selected_sources(root,constructor_mmio=True)
    # Pin actual current code BEFORE importing the new reader. The physical
    # freeze above is external to that reader's own identity computation.
    sys.path.insert(0,str(root))
    from tools import host_stream_kernel_stream_constructor as constructor
    require(Path(constructor.__file__).resolve()==(root/'tools/host_stream_kernel_stream_constructor.py').resolve(),
            'constructor-current-reader-origin')
    materials=constructor.constructor_input_materials()
    require(type(materials) is dict and set(materials)=={'physicalInputs','logicalIdentities',
        'logicalOrigins','projectionOutputCount','runtimeOrFundingQualified'} and
        materials['physicalInputs']==physical and len(materials['logicalIdentities'])==90 and
        len(materials['logicalOrigins'])==90 and materials['projectionOutputCount']==427 and
        materials['runtimeOrFundingQualified'] is False and
        hashlib.sha256(canonical(materials['logicalIdentities'])).hexdigest()==CONSTRUCTOR_MMIO_LOGICAL_SHA,
        'constructor-current-material-model')
    return materials


def constructor_compose(values, tree):
    require(len(values)==381 and hashlib.sha256(canonical({name:identity(raw)
        for name,raw in values.items()})).hexdigest()==POST_INIT_DERIVED_SHA,
        'constructor-original-381-input')
    constructor_materials(ROOT) # Whole container and actual current code before projection.
    from tools import host_stream_kernel_stream_constructor as constructor
    from tools import host_stream_kernel_stream_vwindow as window
    records=[]
    def checked(result):
        stage,count,sha=CONSTRUCTOR_MMIO_DERIVED[len(records)]
        rows={name:identity(raw) for name,raw in result.items()}
        require(len(rows)==count and hashlib.sha256(canonical(rows)).hexdigest()==sha,
                'constructor-intermediate-'+stage)
        records.append({'stage':stage,'files':count,'actualDerivedIdentity':identity(canonical(rows))})
        return result
    values=checked(constructor.transform(values,{name:read(tree/name,MAX_FILE) for name in constructor.PRIMARY}))
    values=checked(constructor.mapping_transform(values,{name:read(tree/name,MAX_FILE) for name in constructor.MAPPING_PRIMARY}))
    values=checked(window.transform(values,read(tree/'include/linux/kasan.h',MAX_FILE)))
    values=checked(window.ancestor_transform(values,{name:read(tree/name,MAX_FILE) for name in window.ANCESTOR_PRIMARY}))
    values=checked(window.leaf_transform(values))
    values=checked(window.mmio_transform(values,{name:read(tree/name,MAX_FILE) for name in window.MMIO_PRIMARY}))
    require(len(records)==6 and len(values)==427 and b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in
        values['net/factory-private.h'],'constructor-unselected-final-projection')
    return values,records


def vp_selected_sources(root):
    rows=selected_sources(root,constructor_mmio=True)
    for name,(length,sha) in VP_ADDED_PINS.items():
        require(name not in rows,'vp-new-physical-only')
        raw=read(root/name,length)
        require(identity(raw)=={'bytes':length,'sha256':sha},'vp-added-source-identity')
        rows[name]=identity(raw)
    require(len(rows)==67 and sum(row['bytes'] for row in rows.values())==VP_PHYSICAL_BYTES and
        hashlib.sha256(canonical(rows)).hexdigest()==VP_PHYSICAL_SHA,'vp-frozen-67-physical')
    return rows


def vp_materials(root):
    # Pin BOTH new actual execution files before importing their projector.
    physical=vp_selected_sources(root)
    sys.path.insert(0,str(root))
    from tools import host_stream_kernel_vp_transport as stage
    require(Path(stage.__file__).resolve()==(root/'tools/host_stream_kernel_vp_transport.py').resolve(),
        'vp-current-reader-origin')
    base=constructor_materials(root)
    payloads=stage.materials(root)
    require(type(payloads) is dict and len(payloads)==3,'vp-three-logical-materials')
    logical=dict(base['logicalIdentities']);origins=dict(base['logicalOrigins'])
    module='tools/host_stream_kernel_vp_transport.py'
    require(module not in logical,'vp-new-projector-logical-only')
    logical[module]=physical[module];origins[module]={'kind':'physical-file','path':module}
    for ordinal,(name,raw) in enumerate(payloads.items()):
        key='vp-transport:'+name
        require(key not in logical and type(raw) is bytes,'vp-new-payload-logical-only')
        logical[key]=identity(raw)
        origins[key]={'kind':'utf8-source-bundle','path':stage.BUNDLE_PATH,
            'ordinal':ordinal,'sourceType':'h' if name.endswith('.h') else 'c'}
    require(len(logical)==len(origins)==94 and
        hashlib.sha256(canonical(logical)).hexdigest()==VP_LOGICAL_SHA,'vp-frozen-94-logical')
    return {'physicalInputs':physical,'logicalIdentities':logical,'logicalOrigins':origins,
        'prior65Physical':base['physicalInputs'],'prior90Logical':base['logicalIdentities'],
        'projectionOutputCount':430,'runtimeOrFundingQualified':False}


def vp_compose(values):
    require(len(values)==427 and hashlib.sha256(canonical({n:identity(raw)
        for n,raw in values.items()})).hexdigest()==CONSTRUCTOR_MMIO_DERIVED[-1][2],
        'vp-original-427-input')
    vp_materials(ROOT)
    from tools import host_stream_kernel_vp_transport as stage
    result=stage.transform(values)
    rows={n:identity(raw) for n,raw in result.items()}
    require(len(rows)==430 and hashlib.sha256(canonical(rows)).hexdigest()==VP_DERIVED_SHA and
        b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in result['net/factory-private.h'],
        'vp-unselected-final-430')
    return result,{'stage':'vp-transport','files':430,'actualDerivedIdentity':identity(canonical(rows))}


def msi_selected_sources(root):
    rows=vp_selected_sources(root)
    for name,(length,sha) in MSI_ADDED_PINS.items():
        require(name not in rows,'msi-new-physical-only')
        raw=read(root/name,length)
        require(identity(raw)=={'bytes':length,'sha256':sha},'msi-added-source-identity')
        rows[name]=identity(raw)
    require(len(rows)==69 and sum(row['bytes'] for row in rows.values())==MSI_PHYSICAL_BYTES and
        hashlib.sha256(canonical(rows)).hexdigest()==MSI_PHYSICAL_SHA,'msi-frozen-69-physical')
    return rows


def msi_materials(root):
    # Authenticate both current files before importing any new execution code.
    physical=msi_selected_sources(root)
    sys.path.insert(0,str(root))
    from tools import host_stream_kernel_msi_context as stage
    require(Path(stage.__file__).resolve()==(root/'tools/host_stream_kernel_msi_context.py').resolve(),
        'msi-current-reader-origin')
    base=vp_materials(root)
    payloads=stage.materials(root)
    require(type(payloads) is dict and len(payloads)==5,'msi-five-logical-materials')
    logical=dict(base['logicalIdentities']);origins=dict(base['logicalOrigins'])
    module='tools/host_stream_kernel_msi_context.py'
    require(module not in logical,'msi-new-projector-logical-only')
    logical[module]=physical[module];origins[module]={'kind':'physical-file','path':module}
    for ordinal,(name,raw) in enumerate(payloads.items()):
        key='msi-context:'+name
        require(key not in logical and type(raw) is bytes,'msi-new-payload-logical-only')
        logical[key]=identity(raw)
        origins[key]={'kind':'utf8-source-bundle','path':stage.BUNDLE_PATH,
            'ordinal':ordinal,'sourceType':'h' if name.endswith('.h') else 'c'}
    require(len(logical)==len(origins)==100 and
        hashlib.sha256(canonical(logical)).hexdigest()==MSI_LOGICAL_SHA,'msi-frozen-100-logical')
    return {'physicalInputs':physical,'logicalIdentities':logical,'logicalOrigins':origins,
        'prior67Physical':base['physicalInputs'],'prior94Logical':base['logicalIdentities'],
        'projectionOutputCount':439,'runtimeOrFundingQualified':False}


def msi_compose(values, tree):
    require(len(values)==430 and hashlib.sha256(canonical({n:identity(raw)
        for n,raw in values.items()})).hexdigest()==VP_DERIVED_SHA,'msi-original-430-input')
    msi_materials(ROOT)
    from tools import host_stream_kernel_msi_context as stage
    primary={name:read(tree/name,MAX_FILE) for name in stage.PRIMARY}
    require(all(identity(raw)=={'bytes':stage.PRIMARY[name][0],'sha256':stage.PRIMARY[name][1]}
        for name,raw in primary.items()),'msi-four-native-primary-identities')
    result=stage.transform(values,primary)
    rows={n:identity(raw) for n,raw in result.items()}
    require(len(rows)==439 and hashlib.sha256(canonical(rows)).hexdigest()==MSI_DERIVED_SHA and
        b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in result['net/factory-private.h'],
        'msi-unselected-final-439')
    return result,{'stage':'msi-context','files':439,'actualDerivedIdentity':identity(canonical(rows)),
        'nativePrimaryInputs':{n:identity(raw) for n,raw in primary.items()}}


def q35_stage(root):
    # Authenticate all78 physical inputs BEFORE any new research code executes.
    base=msi_materials(root);physical=dict(base['physicalInputs']);captured=None
    for name,(length,sha) in Q35_PINS.items():
        require(name not in physical,'q35-new-physical')
        raw=read(root/name,length)
        require(identity(raw)=={'bytes':length,'sha256':sha},'q35-physical-identity')
        physical[name]=identity(raw)
        if name==Q35_MODULE:captured=raw
    require(len(physical)==78 and sum(v['bytes'] for v in physical.values())==Q35_PHYSICAL_BYTES and
        hashlib.sha256(canonical(physical)).hexdigest()==Q35_PHYSICAL_SHA,'q35-78-physical')
    require(type(captured) is bytes,'q35-captured-code')
    import importlib.abc
    import importlib.util
    path=str((root/Q35_MODULE).resolve())
    class Captured(importlib.abc.SourceLoader):
        def get_filename(self,fullname):
            require(fullname=='_lsf_q35_projector','q35-module-name');return path
        def get_data(self,name):
            require(name==path,'q35-no-alternate-source');return captured
        def path_stats(self,name):
            raise OSError('q35-no-bytecode')
    spec=importlib.util.spec_from_file_location('_lsf_q35_projector',path,loader=Captured())
    require(spec is not None and spec.loader is not None,'q35-source-spec')
    stage=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stage)
    require(Path(stage.__file__).resolve()==Path(path) and stage.ROOT==root.resolve(),
        'q35-reader-origin')
    return stage,physical,base


def q35_materials(root):
    stage,physical,base=q35_stage(root)
    logical=dict(base['logicalIdentities']);origins=dict(base['logicalOrigins'])
    logical[Q35_MODULE]=physical[Q35_MODULE];origins[Q35_MODULE]={'kind':'physical-file','path':Q35_MODULE}
    parts=stage.materials(root)
    require(set(parts)==set(stage.MATERIAL_PINS) and len(parts)==8,'q35-eight-materials')
    for name,raw in parts.items():
        key='q35-msi:'+name;path=stage.MATERIAL_PATHS[name]
        require(key not in logical and identity(raw)==physical[path],'q35-material-git-source')
        logical[key]=identity(raw);origins[key]={'kind':'physical-file','path':path}
    require(len(logical)==len(origins)==109 and
        hashlib.sha256(canonical(logical)).hexdigest()==Q35_LOGICAL_SHA,'q35-109-logical')
    return dict(base,physicalInputs=physical,logicalIdentities=logical,logicalOrigins=origins,
        prior69Physical=base['physicalInputs'],prior100Logical=base['logicalIdentities'],
        projectionOutputCount=451)


def q35_compose(values, tree):
    require(len(values)==439 and hashlib.sha256(canonical({n:identity(b) for n,b in values.items()})).hexdigest()==MSI_DERIVED_SHA,
        'q35-old-439')
    q35_materials(ROOT)
    stage,_,_=q35_stage(ROOT)
    native={n:read(tree/n,MAX_FILE) for n in (*stage.PRIMARY,*stage.CONTEXT)}
    result=stage.transform(values,native)
    rows={n:identity(b) for n,b in result.items()}
    require(len(rows)==451 and hashlib.sha256(canonical(rows)).hexdigest()==Q35_DERIVED_SHA and
        b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in result['net/factory-private.h'],
        'q35-unselected-451')
    return result,{'stage':'q35-msi-domain','files':451,'actualDerivedIdentity':identity(canonical(rows)),
        'nativePrimaryInputs':{n:identity(b) for n,b in native.items()},
        'runtimeOrFundingQualified':False}


def msi_descriptor_capture(root):
    base=q35_materials(root)
    physical=dict(base['physicalInputs']);captured={}
    for name,(length,sha) in MSI_DESCRIPTOR_PINS.items():
        require(name not in physical,'msi-descriptor-new-physical')
        physical[name]={'bytes':length,'sha256':sha}
    require(len(physical)==83 and sum(v['bytes'] for v in physical.values())==MSI_DESCRIPTOR_PHYSICAL_BYTES and
        hashlib.sha256(canonical(physical)).hexdigest()==MSI_DESCRIPTOR_PHYSICAL_SHA,'msi-descriptor-83-physical')
    # All83 actual byte strings are captured BEFORE the new projector loads.
    for name,row in physical.items():
        raw=read(root/name,row['bytes'])
        require(len(raw)==row['bytes'] and identity(raw)==row,'msi-descriptor-captured-physical')
        captured[name]=raw
    return base,physical,captured


def msi_descriptor_materials(root):
    base,physical,captured=msi_descriptor_capture(root)
    logical=dict(base['logicalIdentities']);origins=dict(base['logicalOrigins'])
    logical[MSI_DESCRIPTOR_MODULE]=physical[MSI_DESCRIPTOR_MODULE]
    origins[MSI_DESCRIPTOR_MODULE]={'kind':'physical-file','path':MSI_DESCRIPTOR_MODULE}
    for name,path in MSI_DESCRIPTOR_MATERIAL_PATHS.items():
        key='msi-descriptor:'+name
        require(key not in logical and path in captured,'msi-descriptor-new-logical')
        logical[key]=physical[path];origins[key]={'kind':'physical-file','path':path}
    require(len(logical)==len(origins)==114 and hashlib.sha256(canonical(logical)).hexdigest()==MSI_DESCRIPTOR_LOGICAL_SHA,
        'msi-descriptor-114-logical')
    return dict(base,physicalInputs=physical,logicalIdentities=logical,logicalOrigins=origins,
        prior78Physical=base['physicalInputs'],prior109Logical=base['logicalIdentities'],
        projectionOutputCount=456)


def msi_descriptor_stage(root,native):
    require(type(native) is dict and set(native)==set(MSI_DESCRIPTOR_NATIVE_PINS),'msi-descriptor-native-members')
    for name,(length,sha) in MSI_DESCRIPTOR_NATIVE_PINS.items():
        raw=native[name]
        require(type(raw) is bytes and len(raw)==length and identity(raw)=={'bytes':length,'sha256':sha},
            'msi-descriptor-native-preimage')
    base,physical,captured=msi_descriptor_capture(root)
    import importlib.abc
    import importlib.util
    path=str((root/MSI_DESCRIPTOR_MODULE).resolve())
    code=captured[MSI_DESCRIPTOR_MODULE]
    class Captured(importlib.abc.SourceLoader):
        def get_filename(self,fullname):
            require(fullname=='_lsf_msi_descriptor_projector','msi-descriptor-module-name');return path
        def get_data(self,name):
            require(name==path,'msi-descriptor-no-alternate-source');return code
        def path_stats(self,name):
            raise OSError('msi-descriptor-no-bytecode')
    spec=importlib.util.spec_from_file_location('_lsf_msi_descriptor_projector',path,loader=Captured())
    require(spec is not None and spec.loader is not None,'msi-descriptor-source-spec')
    stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
    require(Path(stage.__file__).resolve()==Path(path) and stage.ROOT==root.resolve() and
        stage.MATERIAL_PATHS==MSI_DESCRIPTOR_MATERIAL_PATHS,'msi-descriptor-fixed-origin')
    # Projector material reads also use the retained verified bytes, never a
    # post-load source reopen. Original material hash/length guards still run.
    def captured_material(source,maximum):
        names=[n for n,p in MSI_DESCRIPTOR_MATERIAL_PATHS.items() if source==root/p]
        require(len(names)==1,'msi-descriptor-captured-material-path')
        physical_path=MSI_DESCRIPTOR_MATERIAL_PATHS[names[0]]
        require(maximum==physical[physical_path]['bytes'],'msi-descriptor-captured-material-bound')
        return captured[physical_path]
    stage.read_file=captured_material
    return stage


def msi_descriptor_compose(values,tree,capture):
    require(len(values)==451 and hashlib.sha256(canonical({n:identity(b) for n,b in values.items()})).hexdigest()==Q35_DERIVED_SHA,
        'msi-descriptor-old451')
    native={n:read(tree/n,pin[0]) for n,pin in MSI_DESCRIPTOR_NATIVE_PINS.items()}
    stage=msi_descriptor_stage(ROOT,native) #83+native2 captured before new code.
    capture.mkdir(mode=0o700)
    for name,raw in native.items():
        q=capture/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
    result=stage.transform(values,native)
    rows={n:identity(b) for n,b in result.items()}
    require(len(rows)==456 and hashlib.sha256(canonical(rows)).hexdigest()==MSI_DESCRIPTOR_DERIVED_SHA and
        b'lsf_factory_selected_consumer(void)\n{\n    return NULL;\n}' in result['net/factory-private.h'],
        'msi-descriptor-unselected456')
    return result,{'stage':'msi-descriptor','files':456,'actualDerivedIdentity':identity(canonical(rows)),
        'prior451Identity':{'sha256':Q35_DERIVED_SHA},
        'nativePrimaryBefore':{n:identity(raw) for n,raw in native.items()},
        'nativePrimaryAfter':None,'capturedNativePreimagesAfter':None,
        'nativePrimaryAfterMeaning':'actual kernel source after append/compile; xarray.c intentionally projected',
        'runtimeOrFundingQualified':False}


def msi_descriptor_after(tree,capture,values,record):
    retained={n:identity(read(capture/n,pin[0])) for n,pin in MSI_DESCRIPTOR_NATIVE_PINS.items()}
    require(retained==record['nativePrimaryBefore'],'msi-descriptor-captured-native-mutated')
    after={n:identity(read(tree/n,MAX_FILE)) for n in MSI_DESCRIPTOR_NATIVE_PINS}
    expected={n:identity(values[n]) if n in values else record['nativePrimaryBefore'][n]
        for n in MSI_DESCRIPTOR_NATIVE_PINS}
    require(after==expected,'msi-descriptor-actual-native-postimages-mutated')
    require({n:identity(read(tree/n,MAX_FILE)) for n in values}=={n:identity(raw) for n,raw in values.items()},
        'msi-descriptor-456-actual-inputs-mutated')
    record.update(nativePrimaryAfter=after,capturedNativePreimagesAfter=retained)
    return record


def object_identity(path):
    raw=read(path,MAX_OBJECT)
    require(len(raw)>=64 and raw[:7]==b'\x7fELF\x02\x01\x01' and
        struct.unpack_from('<HHI',raw,16)==(1,62,1),'relocatable-x86-64-object')
    shoff=struct.unpack_from('<Q',raw,40)[0]
    size,count=struct.unpack_from('<HH',raw,58)
    require(size==64 and count>0 and shoff>=64 and shoff+size*count<=len(raw),'object-section-table')
    # SHN_UNDEF is ordinary in ET_REL; no link/whole-symbol claim is made.
    return identity(raw)


def public_allowed(name, *, classdir=False, classdir_kernfs=False, netdev_directory=False, netdev_layout=False, netdev_post_init=False, constructor_mmio=False, vp_transport=False, msi_context=False, q35=False, msi_descriptor=False):
    targets=mode_targets(classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init,constructor_mmio,vp_transport,msi_context,q35,msi_descriptor)
    if name in DOCUMENTS:return DOCUMENTS[name]
    if netdev_layout and name=='layout.json':return 64*1024
    if name in {'objects/'+n for n in targets}:return MAX_OBJECT
    match=re.fullmatch(r'logs/([0-9]{2})-([a-z0-9-]+)\.(stdout|stderr)\.txt',name)
    if match and int(match[1])<MAX_COMMANDS and match[2] in (MSI_DESCRIPTOR_STAGES if msi_descriptor else Q35_STAGES if q35 else MSI_STAGES if msi_context else VP_STAGES if vp_transport else CONSTRUCTOR_MMIO_STAGES if constructor_mmio else POST_INIT_STAGES if netdev_post_init else LAYOUT_STAGES if netdev_layout else DIRECTORY_STAGES if netdev_directory else REGISTRATION_STAGES if classdir_kernfs else STAGES):return 4*1024**2
    return None


def admit(output, *, classdir=False, classdir_kernfs=False, netdev_directory=False, netdev_layout=False, netdev_post_init=False, constructor_mmio=False, vp_transport=False, msi_context=False, q35=False, msi_descriptor=False):
    targets=mode_targets(classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init,constructor_mmio,vp_transport,msi_context,q35,msi_descriptor)
    require(not output.is_symlink() and output.is_dir(),'public-output-directory')
    rows={};total=logs=0
    for q in sorted(output.rglob('*')):
        require(not q.is_symlink(),'public-symlink')
        if q.is_dir():continue
        name=q.relative_to(output).as_posix()
        if name=='ADMISSION.json':continue
        maximum=public_allowed(name,classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init,constructor_mmio=constructor_mmio,vp_transport=vp_transport,msi_context=msi_context,q35=q35,msi_descriptor=msi_descriptor);require(maximum is not None,'public-member')
        raw=read(q,maximum);total+=len(raw)
        if name.startswith('logs/'):logs+=len(raw)
        require(total<=MAX_PUBLIC-MAX_DOCUMENT and logs<=16*1024**2,'public-union-bound')
        rows[name]=identity(raw)
    require('receipt.json' in rows and len(rows)<=len(DOCUMENTS)+int(netdev_layout)+len(targets)+2*MAX_COMMANDS,'public-inventory')
    record={'schemaVersion':'lsf.stream-object-public.v1','files':rows,'payloadBytes':total,
        'maximumUnionBytes':MAX_PUBLIC,'admissionMaximumBytes':MAX_DOCUMENT}
    raw=canonical(record);require(len(raw)<=MAX_DOCUMENT and total+len(raw)<=MAX_PUBLIC,'public-admission-bound')
    (output/'ADMISSION.json').write_bytes(raw)
    return record


def _copy_public(source, output, name, maximum):
    raw=read(source,maximum);q=output/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)


def run(output, revision, started, *, classdir=False, classdir_kernfs=False, netdev_directory=False, netdev_layout=False, netdev_post_init=False, constructor_mmio=False, vp_transport=False, msi_context=False, q35=False, msi_descriptor=False):
    targets=mode_targets(classdir,classdir_kernfs,netdev_directory,netdev_layout,netdev_post_init,constructor_mmio,vp_transport,msi_context,q35,msi_descriptor)
    end=deadline(started) # Before imports, filesystem mutation or tool probes.
    require(sys.platform=='linux' and os.environ.get('GITHUB_ACTIONS')=='true' and
        os.environ.get('GITHUB_REPOSITORY')=='KirilsTurkins/latent-service-fabric' and
        os.environ.get('GITHUB_REF_NAME')==(MSI_DESCRIPTOR_BRANCH if msi_descriptor else Q35_BRANCH if q35 else MSI_BRANCH if msi_context else VP_BRANCH if vp_transport else CONSTRUCTOR_MMIO_BRANCH if constructor_mmio else POST_INIT_BRANCH if netdev_post_init else LAYOUT_BRANCH if netdev_layout else DIRECTORY_BRANCH if netdev_directory else REGISTRATION_BRANCH if classdir_kernfs else CLASSDIR_BRANCH if classdir else BRANCH) and os.environ.get('GITHUB_EVENT_NAME')=='push',
        'fixed-hosted-origin')
    require(type(revision) is str and re.fullmatch('[0-9a-f]{40}',revision),'source-revision')
    before=msi_descriptor_materials(ROOT)['physicalInputs'] if msi_descriptor else q35_materials(ROOT)['physicalInputs'] if q35 else msi_selected_sources(ROOT) if msi_context else vp_selected_sources(ROOT) if vp_transport else selected_sources(ROOT,classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init,constructor_mmio=constructor_mmio)
    constructor_before=constructor_materials(ROOT) if constructor_mmio else None
    vp_before=vp_materials(ROOT) if vp_transport else None
    msi_before=(msi_descriptor_materials(ROOT) if msi_descriptor else q35_materials(ROOT) if q35 else msi_materials(ROOT)) if msi_context or q35 or msi_descriptor else None
    output=output.resolve()
    require(output!=ROOT and ROOT not in output.parents and output not in ROOT.parents and
        not output.exists(),'fresh-public-outside-source')
    sys.path.insert(0,str(ROOT))
    from tools import qualify_host_stream_kernel_objects as objects
    output.mkdir(mode=0o700)
    scratch=Path(tempfile.mkdtemp(prefix='stream-object-private-',dir=output.parent))
    (scratch/'tmp').mkdir(mode=0o700);(scratch/'commands').mkdir(mode=0o700)
    keep=('PATH','HOME','USER','LOGNAME','RUSTUP_HOME','RUSTUP_TOOLCHAIN','CARGO_HOME','SSL_CERT_FILE','SSL_CERT_DIR')
    environment={k:v for k,v in os.environ.items() if k in keep}
    environment.update(PYTHONDONTWRITEBYTECODE='1',LC_ALL='C',LANG='C',TMPDIR=str(scratch/'tmp'),
        KBUILD_BUILD_USER='lsf-object-check',KBUILD_BUILD_HOST='isolated-ci',
        KBUILD_BUILD_TIMESTAMP='2026-10-23 00:00:00 UTC',KCONFIG_NOTIMESTAMP='1')
    if classdir_kernfs or netdev_directory or netdev_layout or netdev_post_init or constructor_mmio or vp_transport or msi_context or q35 or msi_descriptor:
        environment.update(GIT_NO_LAZY_FETCH='1',GIT_TERMINAL_PROMPT='0')
    if vp_transport or msi_context or q35 or msi_descriptor:
        environment.update(RUSTUP_TOOLCHAIN='1.97.1',RUSTUP_AUTO_INSTALL='0')
    commands=objects.Commands(ROOT,scratch/'commands',environment,deadline_seconds=end-time.monotonic(),command_seconds=1200)
    commands.deadline=end-5.0 # ONE reserve; run_owned itself includes cleanup.
    receipt={'schemaVersion':'lsf.stream-msi-descriptor-objects.v1' if msi_descriptor else 'lsf.stream-q35-msi-domain-objects.v1' if q35 else 'lsf.stream-msi-context-objects.v1' if msi_context else 'lsf.stream-vp-transport-objects.v1' if vp_transport else 'lsf.stream-constructor-mmio-objects.v1' if constructor_mmio else 'lsf.stream-netdev-post-init-objects.v1' if netdev_post_init else 'lsf.stream-netdev-layout-objects.v1' if netdev_layout else 'lsf.stream-netdev-directory-objects.v1' if netdev_directory else 'lsf.stream-classdir-kernfs-objects.v1' if classdir_kernfs else 'lsf.stream-classdir-objects.v1' if classdir else 'lsf.stream-normal-objects.v1','status':'in-progress','stage':'preflight',
        'sourceRevision':revision,'checkpoint':CHECKPOINT,'baselineRecipeRevision':BASELINE,
        'baselineRecipeTree':BASELINE_TREE,'sourceBefore':before,'sourceAfter':None,'checkpoint45SourceDigest':CHECKPOINT45_SHA,
        'objectTargets':list(targets),'products':{},'compiledObjectsOnly':True,'kernelLinked':False,
        'imageBuilt':False,'booted':False,'normalOperationsExecuted':False,'compiledUsefulFit':False,
        'physicalRootRetirementQualified':False,'consumerSelected':False,'productionInstallation':False,
        'whole738Complete':False,'hermetic':False,'compilerImplicitInputsAttested':False,
        'originalStartedMonotonic':started,'originalDeadlineMonotonic':end,'maximumOwnerSeconds':1320,
        'maximumCompileSeconds':1200,'privateScratchRetained':True}
    error=None;tools={};public_sources={}
    def command(stage,*argv,cap=120,root=None):
        require(stage in (MSI_DESCRIPTOR_STAGES if msi_descriptor else Q35_STAGES if q35 else MSI_STAGES if msi_context else VP_STAGES if vp_transport else CONSTRUCTOR_MMIO_STAGES if constructor_mmio else POST_INIT_STAGES if netdev_post_init else LAYOUT_STAGES if netdev_layout else DIRECTORY_STAGES if netdev_directory else REGISTRATION_STAGES if classdir_kernfs else STAGES) and len(commands.records)<MAX_COMMANDS,'fixed-command-count')
        require(time.monotonic()<commands.deadline,'original-deadline')
        commands.root=ROOT if root is None else root
        commands.command_seconds=min(cap,1200)
        receipt['stage']=stage
        return commands.run(stage,*argv)
    try:
        current_inputs=input_files(ROOT)
        source_record={'currentBefore':current_inputs,'currentAfter':None,
            ('current83Physical' if msi_descriptor else 'current78Physical' if q35 else 'current69Physical' if msi_context else 'current67Physical' if vp_transport else 'current65Physical' if constructor_mmio else 'current62' if netdev_post_init else 'current59' if netdev_layout else 'current55' if netdev_directory else 'current52' if classdir_kernfs else 'current50' if classdir else 'current47'):before,'currentSourceRevision':revision,'originalBaselineSourceRevision':BASELINE}
        if msi_context or q35 or msi_descriptor:
            require(msi_before['physicalInputs']==before,'msi-initial-materials')
            source_record.update(**{('current114Logical' if msi_descriptor else 'current109Logical' if q35 else 'current100Logical'):msi_before['logicalIdentities']},
                logicalOrigins=msi_before['logicalOrigins'],prior67PhysicalBefore=msi_before['prior67Physical'],
                prior94LogicalBefore=msi_before['prior94Logical'],prior67PhysicalAfter=None,
                prior94LogicalAfter=None,logicalOriginsAfter=None,
                **{('current83PhysicalAfter' if msi_descriptor else 'current78PhysicalAfter' if q35 else 'current69PhysicalAfter'):None,
                   ('current114LogicalAfter' if msi_descriptor else 'current109LogicalAfter' if q35 else 'current100LogicalAfter'):None})
            receipt.update(currentPhysicalSourceCount=83 if msi_descriptor else 78 if q35 else 69,currentLogicalSourceCount=114 if msi_descriptor else 109 if q35 else 100,
                sourceStorage='captured-msi-descriptor-research-plus-prior-bundles' if msi_descriptor else 'pinned-q35-research-plus-prior-bundles' if q35 else 'closed-msi-vp-and-constructor-utf8-bundles',msiProjectionStages=None)
            if q35:
                source_record.update(current109Logical=msi_before['logicalIdentities'],
                    prior69PhysicalBefore=msi_before['prior69Physical'],prior100LogicalBefore=msi_before['prior100Logical'])
            elif msi_descriptor:
                source_record.update(prior78PhysicalBefore=msi_before['prior78Physical'],
                    prior109LogicalBefore=msi_before['prior109Logical'],
                    prior69PhysicalBefore=msi_before['prior69Physical'],prior100LogicalBefore=msi_before['prior100Logical'])
        elif vp_transport:
            require(vp_before['physicalInputs']==before,'vp-initial-materials')
            source_record.update(current94Logical=vp_before['logicalIdentities'],
                logicalOrigins=vp_before['logicalOrigins'],prior65PhysicalBefore=vp_before['prior65Physical'],
                prior90LogicalBefore=vp_before['prior90Logical'],prior65PhysicalAfter=None,
                prior90LogicalAfter=None,current67PhysicalAfter=None,
                current94LogicalAfter=None,logicalOriginsAfter=None)
            receipt.update(currentPhysicalSourceCount=67,currentLogicalSourceCount=94,
                sourceStorage='closed-vp-and-constructor-utf8-bundles',vpProjectionStages=None)
        elif constructor_mmio:
            require(constructor_before['physicalInputs']==before,'constructor-initial-materials')
            source_record.update(current90Logical=constructor_before['logicalIdentities'],
                logicalOrigins=constructor_before['logicalOrigins'],current65PhysicalAfter=None,
                current90LogicalAfter=None,logicalOriginsAfter=None)
            receipt.update(currentPhysicalSourceCount=65,currentLogicalSourceCount=90,
                sourceStorage='closed-utf8-new-fragments-only',constructorProjectionStages=None)
        write_json(scratch/'source-inputs.json',source_record)
        public_sources['source-inputs.json']=scratch/'source-inputs.json'
        git=shutil.which('git');require(git,'git-tool')
        require(command('source-head',git,'rev-parse','HEAD',cap=15).decode().strip()==revision,'actual-checkout')
        tree_before=command('source-tree',git,'ls-tree','-rz','--full-tree','HEAD',cap=30)
        command('source-clean',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30)
        if classdir_kernfs or netdev_directory or netdev_layout or netdev_post_init or constructor_mmio or vp_transport or msi_context or q35 or msi_descriptor:
            # ONE exact shallow acquisition, never history search/lazy fallback.
            # A growing current branch is not baseline authority. Same owner,
            # original absolute1320s deadline and single5s reserve apply.
            command('baseline-fetch',git,'-c','gc.auto=0','fetch','--no-tags',
                '--no-recurse-submodules','--depth=1',
                'https://github.com/KirilsTurkins/latent-service-fabric.git',BASELINE,cap=90)
        command('baseline-object',git,'--no-lazy-fetch','cat-file','-e',BASELINE+'^{commit}',cap=15)
        require(command('baseline-tree',git,'rev-parse',BASELINE+'^{tree}',cap=15).decode().strip()==BASELINE_TREE,'original-tree')
        recipe=scratch/'baseline-recipe'
        command('baseline-worktree',git,'-c','gc.auto=0','worktree','add','--detach',recipe,BASELINE,cap=90)
        require(command('baseline-head',git,'rev-parse','HEAD',cap=15,root=recipe).decode().strip()==BASELINE,'baseline-checkout')
        command('baseline-clean-before',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30,root=recipe)
        command('locked-python-dependencies',sys.executable,'-m','pip','install','--requirement',ROOT/'tools/requirements.lock',cap=180)
        command('normal-prerequisite-update','sudo','apt-get','update',cap=180)
        command('normal-prerequisite-install','sudo','apt-get','install','--yes','--no-install-recommends',
            'gcc','make','flex','bison','bc','libelf-dev','libssl-dev','binutils','libc6-dev','curl','xz-utils',cap=600)
        for name in ('gcc','make','as','ld','rustc','tar','curl'):
            found=shutil.which(name);require(found,'normal-tool-'+name)
            tools[name]=Path(found)
            require(tools[name].is_absolute(),'normal-tool-invocation')
        # argv[0] is observable (GCC config text and rustc/rustup proxy mode).
        # Invoke the discovered spelling; hash its real target separately.
        receipt['tools']={n:{'invocationPath':str(q),'resolvedPath':str(q.resolve()),
            **identity(read(q.resolve(),256*1024**2))} for n,q in tools.items()}
        for name in ('gcc','make','as','ld','rustc'):
            raw=command(name+'-version',tools[name],'--version',cap=30)
            receipt.setdefault('toolVersions',{})[name]=raw.decode('utf8','strict').strip()
        require(receipt['toolVersions']['rustc'].startswith('rustc 1.97.1 '),'original-rust-detector')
        manifest=objects.maintained.manifest();archive=scratch/'linux.tar.xz'
        command('official-source',tools['curl'],'--fail','--location','--proto','=https','--tlsv1.2',
            '--max-time','175','--output',archive,manifest['archive']['url'],cap=180)
        require(commands.deadline-time.monotonic()>=180,'source-auth-parent-reserve')
        originals=objects.maintained.authenticate_archive(archive,manifest,
            tuple(sorted(({'net/Kconfig','net/Makefile'}|set(objects.packet_source.fixture()['source']))-set(manifest['source']))))
        require(time.monotonic()<commands.deadline,'source-auth-deadline')
        receipt['originalArchive']=identity(read(archive,objects.maintained.MAX_ARCHIVE))
        extract=scratch/'kernel';extract.mkdir()
        command('extract-source',tools['tar'],'--extract','--xz','--file',archive,'--directory',extract,
            '--no-same-owner','--no-same-permissions',cap=180)
        tree=extract/('linux-'+manifest['version'])
        require(all(read(tree/n,MAX_FILE)==raw for n,raw in originals.items()),'extracted-originals')
        for name,suffix in [('net/Kconfig',objects.KCONFIG),('net/Makefile',objects.MAKEFILE)]:
            raw=originals[name];require(objects.SELECTED.encode() not in raw,'private-config-fresh')
            (tree/name).write_bytes(raw+suffix.encode())
        build=scratch/'objects';common=[tools['make'],'O='+str(build),'ARCH=x86_64','CC='+str(tools['gcc'])]
        command('original-defconfig',*common,'x86_64_defconfig',root=tree)
        base_config=read(build/'.config',MAX_DOCUMENT);public_sources['baseline.config']=build/'.config'
        (scratch/'baseline.config').write_bytes(base_config);public_sources['baseline.config']=scratch/'baseline.config'
        selected=base_config.replace(b'# CONFIG_LSF_STREAM_FACTORY is not set\n',b'CONFIG_LSF_STREAM_FACTORY=y\n')
        require(selected!=base_config,'private-select-only')
        (build/'.config').write_bytes(selected)
        command('selected-olddefconfig',*common,'olddefconfig',root=tree)
        selected=read(build/'.config',MAX_DOCUMENT);require(identity(selected)==CONFIG,'actual-config-byte-drift')
        (scratch/'selected.config').write_bytes(selected);public_sources['selected.config']=scratch/'selected.config'
        receipt['actualConfiguration']=identity(selected)
        baseline_output=scratch/'baseline';baseline_output.mkdir()
        command('pure-baseline',sys.executable,'-B',Path(__file__).resolve(),'--baseline-worker',
            '--recipe',recipe,'--kernel-tree',tree,'--config',scratch/'selected.config','--output',baseline_output,cap=180)
        baseline=json.loads(read(baseline_output/'baseline.json',16*MAX_DOCUMENT))
        require(baseline['sourceRevision']==BASELINE and baseline['tree']==BASELINE_TREE and
            baseline['sourceBefore']==baseline['sourceAfter'] and baseline['actualConfiguration']==CONFIG and
            baseline['compilerInvocations']==baseline['runtimeInvocations']==0 and
            baseline['qualificationProjectionApplied'] is False,'pure-baseline-identity')
        public_sources['baseline-inputs.json']=baseline_output/'baseline.json'
        command('baseline-clean-after',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30,root=recipe)
        require(command('baseline-tree-after',git,'rev-parse','HEAD^{tree}',cap=15,root=recipe).decode().strip()==BASELINE_TREE,'baseline-tree-after')
        values=current_compose(derived_read(baseline_output/'derived',baseline['derived']),tree,
            classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init or constructor_mmio or vp_transport or msi_context or q35 or msi_descriptor)
        if constructor_mmio or vp_transport or msi_context or q35 or msi_descriptor:
            values,actual_stages=constructor_compose(values,tree)
            if vp_transport or msi_context or q35 or msi_descriptor:
                values,vp_stage=vp_compose(values)
                if msi_context or q35 or msi_descriptor:
                    values,msi_stage=msi_compose(values,tree)
                    receipt['msiProjectionStages']=[*actual_stages,vp_stage,msi_stage]
                    if q35 or msi_descriptor:
                        values,q35_stage=q35_compose(values,tree)
                        receipt['msiProjectionStages'].append(q35_stage)
                        if msi_descriptor:
                            values,descriptor_stage=msi_descriptor_compose(values,tree,scratch/'msi-native-preimages')
                            receipt['msiProjectionStages'].append(descriptor_stage)
                else:
                    receipt['vpProjectionStages']=[*actual_stages,vp_stage]
            else:
                receipt['constructorProjectionStages']=actual_stages
        rows=derived_write(scratch/'current-derived',values)
        for name,raw in values.items():
            q=tree/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(raw)
        write_json(scratch/'derived-inputs.json',rows,4*MAX_DOCUMENT);public_sources['derived-inputs.json']=scratch/'derived-inputs.json'
        command('msi-descriptor-objects' if msi_descriptor else 'q35-msi-domain-objects' if q35 else 'msi-context-objects' if msi_context else 'vp-transport-objects' if vp_transport else 'constructor-mmio-objects' if constructor_mmio else 'netdev-post-init-objects' if netdev_post_init else 'netdev-layout-objects' if netdev_layout else 'netdev-directory-objects' if netdev_directory else 'classdir-kernfs-objects' if classdir_kernfs else 'classdir-objects' if classdir else 'eighteen-objects',
            *common,*(['-k'] if constructor_mmio or vp_transport or msi_context or q35 or msi_descriptor else []),'-j2',*targets,root=tree,cap=1200)
        require(read(build/'.config',MAX_DOCUMENT)==selected,'actual-config-mutated')
        autoconf=read(build/'include/generated/autoconf.h',MAX_DOCUMENT)
        require(b'#define CONFIG_LSF_STREAM_FACTORY 1\n' in autoconf and b'#define CONFIG_RUST ' not in autoconf,
            'actual-selected-autoconf')
        (scratch/'generated-autoconf.h').write_bytes(autoconf);public_sources['generated-autoconf.h']=scratch/'generated-autoconf.h'
        receipt['products']={name:object_identity(build/name) for name in targets}
        require(len(receipt['products'])==len(targets),'six-msi-descriptor-exact-products' if msi_descriptor else 'seven-q35-exact-products' if q35 else 'six-msi-exact-products' if msi_context else 'twenty-two-vp-exact-products' if vp_transport else 'twenty-two-constructor-exact-products' if constructor_mmio else 'eight-post-init-exact-products' if netdev_post_init else 'eleven-layout-exact-products' if netdev_layout else 'nine-directory-exact-products' if netdev_directory else 'nine-exact-products' if classdir_kernfs else 'four-exact-products' if classdir else 'eighteen-exact-products')
        for name in targets:public_sources['objects/'+name]=build/name
        if netdev_layout:
            receipt['stage']='readonly-layout'
            require(time.monotonic()<commands.deadline,'layout-parent-deadline')
            from tools import host_stream_kernel_stream_layout as layout
            decoded={}
            for tu,fields in layout.DESCRIPTOR:
                if not fields:continue
                target=tu[:-2]+'.o'
                raw=read(build/target,MAX_OBJECT)
                require(identity(raw)==receipt['products'][target],'layout-actual-product-identity')
                decoded[tu]=layout.decode(raw,tu)
            report=layout.report_bytes(decoded)
            require(time.monotonic()<commands.deadline,'layout-parent-deadline')
            (scratch/'layout.json').write_bytes(report)
            public_sources['layout.json']=scratch/'layout.json'
            receipt['readonlyLayout']={'report':identity(report),'descriptorSource':before['tools/host_stream_kernel_stream_layout.py'],
                'dataProducers':len(decoded),'objectExecution':False,'prefixComplete':False,
                'knownMinimumStatus':json.loads(report)['knownMinimum']['status']}
        command('source-clean-after',git,'diff','--no-ext-diff','--exit-code','HEAD','--',cap=30)
        require(command('source-tree-after',git,'ls-tree','-rz','--full-tree','HEAD',cap=30)==tree_before,'source-tree-mutated')
        require(command('source-head-after',git,'rev-parse','HEAD',cap=15).decode().strip()==revision,'source-head-mutated')
        receipt['sourceAfter']=msi_descriptor_materials(ROOT)['physicalInputs'] if msi_descriptor else q35_materials(ROOT)['physicalInputs'] if q35 else msi_selected_sources(ROOT) if msi_context else vp_selected_sources(ROOT) if vp_transport else selected_sources(ROOT,classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init,constructor_mmio=constructor_mmio)
        require(receipt['sourceAfter']==before and input_files(ROOT)==current_inputs,'current-source-mutated')
        require(time.monotonic()<commands.deadline,'original-deadline')
        if msi_context or q35 or msi_descriptor:
            msi_after=msi_descriptor_materials(ROOT) if msi_descriptor else q35_materials(ROOT) if q35 else msi_materials(ROOT)
            require(msi_after==msi_before,'msi-materials-mutated')
            source_record.update(**{('current83PhysicalAfter' if msi_descriptor else 'current78PhysicalAfter' if q35 else 'current69PhysicalAfter'):msi_after['physicalInputs'],
                ('current114LogicalAfter' if msi_descriptor else 'current109LogicalAfter' if q35 else 'current100LogicalAfter'):msi_after['logicalIdentities']},
                prior67PhysicalAfter=msi_after['prior67Physical'],prior94LogicalAfter=msi_after['prior94Logical'],
                logicalOriginsAfter=msi_after['logicalOrigins'])
            if q35:
                source_record.update(current78PhysicalAfter=msi_after['physicalInputs'],
                    current109LogicalAfter=msi_after['logicalIdentities'],
                    prior69PhysicalAfter=msi_after['prior69Physical'],prior100LogicalAfter=msi_after['prior100Logical'])
            elif msi_descriptor:
                source_record.update(prior78PhysicalAfter=msi_after['prior78Physical'],
                    prior109LogicalAfter=msi_after['prior109Logical'],
                    prior69PhysicalAfter=msi_after['prior69Physical'],prior100LogicalAfter=msi_after['prior100Logical'],
                    msiDescriptorNative=msi_descriptor_after(tree,scratch/'msi-native-preimages',values,descriptor_stage))
        elif vp_transport:
            vp_after=vp_materials(ROOT)
            require(vp_after==vp_before,'vp-materials-mutated')
            source_record.update(current67PhysicalAfter=vp_after['physicalInputs'],
                current94LogicalAfter=vp_after['logicalIdentities'],
                prior65PhysicalAfter=vp_after['prior65Physical'],prior90LogicalAfter=vp_after['prior90Logical'],
                logicalOriginsAfter=vp_after['logicalOrigins'])
        elif constructor_mmio:
            constructor_after=constructor_materials(ROOT)
            require(constructor_after==constructor_before,'constructor-materials-mutated')
            source_record.update(current65PhysicalAfter=constructor_after['physicalInputs'],
                current90LogicalAfter=constructor_after['logicalIdentities'],
                logicalOriginsAfter=constructor_after['logicalOrigins'])
        source_record.update(currentAfter=current_inputs,currentGitTreeInventory=identity(tree_before))
        write_json(scratch/'source-inputs.json',source_record)
        public_sources['source-inputs.json']=scratch/'source-inputs.json'
        receipt['status']='passed';receipt['stage']='complete'
    except BaseException as failure:
        error=failure;receipt['status']='failed';receipt['failureType']=type(failure).__name__
        # Raw owned command channels carry the actual compiler diagnostic.
        receipt['failureReason']=str(failure)[:1024] if isinstance(failure,ValueError) else getattr(failure,'reason','controller-failed')
    finally:
        receipt['commands']=commands.records
        receipt['ownedProcessCleanupConfirmed']=all(row.get('completed') and row.get('descendantsCleaned') for row in commands.records)
        try:
            write_json(output/'receipt.json',receipt,MAX_DOCUMENT)
            write_json(output/'commands.json',commands.records,MAX_DOCUMENT)
            for name,q in public_sources.items():
                maximum=public_allowed(name,classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init,constructor_mmio=constructor_mmio,vp_transport=vp_transport,msi_context=msi_context,q35=q35,msi_descriptor=msi_descriptor);require(maximum is not None,'public-source')
                _copy_public(q,output,name,maximum)
            for q in sorted((scratch/'commands/logs').iterdir()):
                name='logs/'+q.name;maximum=public_allowed(name,classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init,constructor_mmio=constructor_mmio,vp_transport=vp_transport,msi_context=msi_context,q35=q35,msi_descriptor=msi_descriptor);require(maximum is not None,'public-command-channel')
                _copy_public(q,output,name,maximum)
            admit(output,classdir=classdir,classdir_kernfs=classdir_kernfs,netdev_directory=netdev_directory,netdev_layout=netdev_layout,netdev_post_init=netdev_post_init,constructor_mmio=constructor_mmio,vp_transport=vp_transport,msi_context=msi_context,q35=q35,msi_descriptor=msi_descriptor)
        except BaseException as retention:
            receipt['status']='failed';receipt['retentionFailure']='bounded-public-admission-failed'
            raw=canonical(receipt)
            if len(raw)<=MAX_DOCUMENT:(output/'receipt.json').write_bytes(raw)
            if error is None:error=retention
        # No deletion of scratch/worktree, especially after unknown cleanup.
    if error is not None:raise error
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--source-commit')
    parser.add_argument('--started',type=float)
    parser.add_argument('--admit',action='store_true')
    parser.add_argument('--classdir',action='store_true',help='fixed private four-object source check only')
    parser.add_argument('--classdir-kernfs',action='store_true',help='fixed private nine-object source check only')
    parser.add_argument('--netdev-directory',action='store_true',help='fixed private nine changed NETDEV directory objects only')
    parser.add_argument('--netdev-layout',action='store_true',help='fixed eleven allocating/notify objects and readonly layout data only')
    parser.add_argument('--netdev-post-init',action='store_true',help='fixed eight changed POST_INIT objects only; no readonly size-probe replay')
    parser.add_argument('--constructor-mmio',action='store_true',help='fixed22 changed cumulative constructor/MMIO objects only')
    parser.add_argument('--vp-transport',action='store_true',help='fixed22 current VP bookkeeping objects only; IRQ gate closed')
    parser.add_argument('--msi-context',action='store_true',help='fixed six actual MSI/context/group objects only; IRQ gate closed')
    parser.add_argument('--q35-msi-domain',dest='q35',action='store_true',help='fixed seven direct-vector domain/table objects; IRQ gate closed')
    parser.add_argument('--msi-descriptor',action='store_true',help='fixed six descriptor/XArray objects only; IRQ gate closed')
    parser.add_argument('--baseline-worker',action='store_true')
    parser.add_argument('--recipe',type=Path);parser.add_argument('--kernel-tree',type=Path);parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    mode_targets(args.classdir,args.classdir_kernfs,args.netdev_directory,args.netdev_layout,args.netdev_post_init,args.constructor_mmio,args.vp_transport,args.msi_context,args.q35,args.msi_descriptor)
    require(not ((args.classdir or args.classdir_kernfs or args.netdev_directory or args.netdev_layout or args.netdev_post_init or args.constructor_mmio or args.vp_transport or args.msi_context or args.q35 or args.msi_descriptor) and args.baseline_worker),'one-private-mode')
    if args.admit:
        require(not args.baseline_worker,'one-private-mode')
        try:
            admit(args.output,classdir=args.classdir,classdir_kernfs=args.classdir_kernfs,netdev_directory=args.netdev_directory,netdev_layout=args.netdev_layout,netdev_post_init=args.netdev_post_init,constructor_mmio=args.constructor_mmio,vp_transport=args.vp_transport,msi_context=args.msi_context,q35=args.q35,msi_descriptor=args.msi_descriptor)
        except BaseException:
            # Fixed fallback only; never upload any rejected directory/glob.
            require(not args.output.is_symlink(),'fallback-output-symlink')
            args.output.mkdir(mode=0o700,parents=True,exist_ok=True)
            fallback={'status':'failed','reason':'public-evidence-admission-failed',
                'compilerQualificationClaimed':False,'originalReceiptAvailable':False}
            try:
                original=read(args.output/'receipt.json',MAX_DOCUMENT)
                record=json.loads(original)
                fallback['originalReceiptAvailable']=True
                fallback['originalReceipt']=identity(original)
                for key in ('status','stage','failureType'):
                    value=record.get(key)
                    if type(value) is str and len(value)<=128:
                        fallback['original'+key[0].upper()+key[1:]]=value
            except (ValueError,OSError,TypeError):
                pass
            write_json(args.output/'FAILED.json',fallback,MAX_DOCUMENT)
            if os.environ.get('GITHUB_OUTPUT'):
                with Path(os.environ['GITHUB_OUTPUT']).open('a') as f:f.write('fallback=true\n')
            raise
        if os.environ.get('GITHUB_OUTPUT'):
            with Path(os.environ['GITHUB_OUTPUT']).open('a') as f:f.write('admitted=true\n')
    elif args.baseline_worker:
        require(args.recipe and args.kernel_tree and args.config,'worker-fixed-inputs')
        baseline_worker(args.recipe,args.kernel_tree,args.config,args.output)
    else:run(args.output,args.source_commit,args.started,classdir=args.classdir,classdir_kernfs=args.classdir_kernfs,netdev_directory=args.netdev_directory,netdev_layout=args.netdev_layout,netdev_post_init=args.netdev_post_init,constructor_mmio=args.constructor_mmio,vp_transport=args.vp_transport,msi_context=args.msi_context,q35=args.q35,msi_descriptor=args.msi_descriptor)


if __name__=='__main__':
    main()
