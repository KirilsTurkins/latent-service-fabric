"""Closed real early virtual reservation, after the immutable 407-file stage.

This source stage does not install a PTE, establish physical funding, admit a
Root, adopt an upper page table, or connect MMIO. It preserves native ordinary
bodies and supplies exact static identities only for the real boot reservation.
"""
import hashlib
import json
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import OWNED, require
from tools.host_stream_kernel_stream_constructor import constructor_sources, _constructor_source

INPUT_SHA = '6741a2f5cf10b1810dbe7d78d64cb65f326071a9fccdcf7fc0abbc4c5c1a02c6'
PREIMAGE = (139665, '2d5588c305b1aa83883e646a6f788abafe23122c267e4801ebb12dfc86923f10')
KASAN = (22075, 'f4da73c3d176d3bd4cd00d45bae12756fcdadc93b181b6a99ebb3554e93a60dd')
BODIES = {'static void free_vmap_area(': (450, '9dfd3763d49e5a52190b0bd9a6a5860ebc44c8233f8bc8b8e6fe22883043efcb'), 'static void free_vmap_area_noflush(': (888, '6b7de4ed01b627a3d9b49e99036b62121f50ea5bc42eef5c6e5af105256442ab'), 'static void free_unmap_vmap_area(': (276, '108309b0eb5c05a70005df2ac5177bca22f8729998b7269e612eae0bd947c599'), 'static struct vmap_area *find_unlink_vmap_area(': (500, 'a553612ef85d31be3e13375a8beee5170686cc45a8bbddefaf2d5a82fa23d915'), 'struct vm_struct *find_vm_area(': (162, 'dca0ffe8b43ecdb779d63280b9e32a3de86c17acb689e07e546ef213deec7b40'), 'struct vm_struct *remove_vm_area(': (670, '052b0dc57c1f4b44d6925ff1bc6e1f4613c4c6e38c1ffd1737ef45c6c0318a65'), 'void free_vm_area(': (141, '7d354a07a0f9382091926c85946273dbe535c51fee16ed9bd62204faa1ca4324'), 'void __init vmalloc_init(': (1449, 'b785dc99f9e35c51e91b23f28c689df6ddf97fab4c7e51a3986f5cfacc19511d'), 'void __init vm_area_register_early(': (517, 'f1466792f72ec2d8c092e501b6c39debeb3d8723a6189292b9126ce3e5f81dd6'), 'static void __init vmap_init_free_space(': (1077, '1ee32b67c6930c6cd18d68c83902802ef8d560345b6d2efbba957634cdb7999b')}
FILES = {
    'include/net/lsf_stream_constructor_vwindow_private.h': 'stream-constructor-vwindow-private.h',
    'mm/lsf-stream-constructor-vwindow.c': 'stream-constructor-vwindow.c',
}


def _bound(raw, pin):
    return type(raw) is bytes and (len(raw), hashlib.sha256(raw).hexdigest()) == pin


def _body(text, prefix):
    require(text.count(prefix) == 1, 'vwindow-full-function-prefix')
    start=text.index(prefix)
    require(start == 0 or text[start-1] == '\n', 'vwindow-complete-declaration')
    body=function(text,prefix)
    require(_bound(body.encode(),BODIES[prefix]), 'vwindow-whole-function')
    return body


def _guard(original, condition, result):
    at=original.index('\n{\n')
    return original[:at]+'\n{\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+\
        '    if ('+condition+') return'+result+';\n#endif\n'+original[at+1:]+'}\n'


def _vmlist_scope(editor):
    # Keep ONE actual native static object per selected/ordinary translation
    # unit. Its original declaration is later than the early free guards.
    declaration='static struct vm_struct *vmlist __initdata;\n'
    include='#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-constructor-vwindow.c"\n#endif\n'
    editor.edit(declaration,'#ifndef CONFIG_LSF_STREAM_FACTORY\n'+declaration+'#endif\n')
    editor.edit(include,'#ifdef CONFIG_LSF_STREAM_FACTORY\n'+declaration+
                '#include "lsf-stream-constructor-vwindow.c"\n#endif\n')


def transform(outputs, kasan):
    constructor_sources()
    require(type(outputs) is dict and len(outputs) == 407 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()),'vwindow-input-shape')
    encoded=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(encoded).hexdigest() == INPUT_SHA, 'vwindow-whole-input')
    require(_bound(kasan,KASAN), 'vwindow-kasan-whole-primary')
    before=outputs['mm/vmalloc.c']
    require(_bound(before,PREIMAGE), 'vwindow-vmalloc-whole-preimage')
    result=dict(outputs)
    editor=Editor(before.decode())
    for prefix in BODIES: _body(editor.text,prefix)
    # The actual original boot helper remains unchanged. Its real selected
    # KASAN call is authenticated by the whole header and compile-time guard.
    anchor='static void free_vmap_area(struct vmap_area *va)\n'
    editor.edit(anchor,'#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include "lsf-stream-constructor-vwindow.c"\n#endif\n\n'+anchor)
    for prefix in ['static void free_vmap_area(', 'static void free_vmap_area_noflush(',
                   'static void free_unmap_vmap_area(']:
        original=_body(editor.text,prefix)
        editor.edit(original,_guard(original,'lsf_stream_vwindow_va(va)',''))
    original=_body(editor.text,'static struct vmap_area *find_unlink_vmap_area(')
    editor.edit(original,_guard(original,'lsf_stream_vwindow_address(addr)',' NULL'))
    original=_body(editor.text,'struct vm_struct *find_vm_area(')
    editor.edit(original,_guard(original,'lsf_stream_vwindow_address((unsigned long)addr)',' NULL'))
    original=_body(editor.text,'struct vm_struct *remove_vm_area(')
    editor.edit(original,_guard(original,'lsf_stream_vwindow_address((unsigned long)addr)',' NULL'))
    original=_body(editor.text,'void free_vm_area(')
    editor.edit(original,_guard(original,'lsf_stream_vwindow_vm(area)',''))
    original=_body(editor.text,'void __init vmalloc_init(')
    changed=original
    a='\tvmap_init_nodes();\n\n\t/* Import existing vmlist entries. */'
    b='\tvmap_init_nodes();\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    b+='\tlsf_stream_vwindow_register();\n#endif\n\n\t/* Import existing vmlist entries. */'
    require(changed.count(a)==1,'vwindow-before-native-import')
    changed=changed.replace(a,b)
    a='\t\tva = kmem_cache_zalloc(vmap_area_cachep, GFP_NOWAIT);'
    b='#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    b+='\t\tif (lsf_stream_vwindow_vm(tmp))\n\t\t\tva = lsf_stream_vwindow_import(tmp);\n'
    b+='\t\telse\n#endif\n'+a
    require(changed.count(a)==1,'vwindow-exact-static-import-allocation')
    changed=changed.replace(a,b)
    a='\t\tinsert_vmap_area(va, &vn->busy.root, &vn->busy.head);'
    b=a+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
    b+='\t\tif (lsf_stream_vwindow_vm(tmp) && lsf_stream_vwindow_va(va))\n'
    b+='\t\t\tWRITE_ONCE(lsf_stream_vwindow.imported, 1);\n#endif'
    require(changed.count(a)==1,'vwindow-after-actual-native-insert')
    changed=changed.replace(a,b)
    # Editor checks the complete TU inverse. The actual native registration,
    # insertion and free-space generation still execute in their original order.
    editor.edit(original,changed)
    _vmlist_scope(editor)
    result['mm/vmalloc.c']=editor.finish().encode()
    require('include/linux/kasan.h' not in outputs,'vwindow-new-kasan-input')
    result['include/linux/kasan.h']=kasan
    for destination,name in FILES.items():
        require(destination not in outputs,'vwindow-new-private-file')
        raw=_constructor_source(name)
        require(raw and len(raw)<16384 and b'\r' not in raw,'vwindow-private-source-bound')
        result[destination]=raw
    return result


# Separately frozen static-ancestor increment. The original reservation stage
# above remains reconstructible byte-for-byte; no historical tuple is retagged.
ANCESTOR_INPUT_SHA = '1f802d58d9912ee5e03ab4d7ecfd9279e6be4afe64dc6c28d8fda753ccd0a496'
ANCESTOR_PRIMARY = {'arch/x86/include/asm/pgalloc.h': (5317, '4aab1f7de117aed2aadb1886f5b9f37b96818518dbb418763fe4afa4de9b2035'), 'include/asm-generic/pgalloc.h': (6160, '08c4b5d8812e8fd5258e40c1a50cf9f413283718e686224f2353ea940339bf57'), 'arch/x86/include/asm/pgtable_64_types.h': (6561, '7531b815a6df7664de41db97a4809b466d296bf5e66b5dd0819c401f1ac9692f'), 'init/main.c': (38923, '3c40fe882bf9d1a69b0c9972986b73b78a90c4a601c9ac0b08c9551ac505d1c5'), 'mm/mm_init.c': (77294, 'b44fc9b12eb948b588d5455fb43baf71cd4406bb2213d14402c6123457d206f3'), 'mm/init-mm.c': (1809, '51033efd18a50551f46632c9aff94dfad1cc1cb6c89c62f1d5801bfb62c613d7'), 'arch/x86/mm/pgtable.c': (23018, '76c0285ddb4b9735886cb3dc5235a8962717173724c5a46e9ee8d06a3d4ca7ba'), 'mm/memory.c': (196705, '134b138551e90a3ce3a4d9f79391d11fdec7d2d79dd34a9eca2739a2eea8c64f')}
ANCESTOR_PREIMAGES = {'mm/lsf-stream-constructor-vwindow.c': (3106, '0ef4911f9c2359a680d162d76c708df590598198f455e29350949aabae36df75'), 'net/factory.c': (37684, '9e43c389c09082c55b8b7b16f965ac8e6e17f48bba6382b37a6c9269b5ff3c26'), 'net/factory-cleanup-observer.c': (3208, 'd945e5440fecbf32ab66e17d51f3f5e6b152176797e8649edbff70dd6fefe833')}
ANCESTOR_BODIES = {'mm/lsf-stream-constructor-vwindow.c::static void __init lsf_stream_vwindow_register(': (964, 'c567adb024da144d785e71cbea21b1285b4ca58ff877c7d4ebb6ec02d0725603'), 'mm/lsf-stream-constructor-vwindow.c::int lsf_prepaid_stream_vwindow_static_geometry(': (313, '2d07e4e14cbc2bc41949d2b9d5ee4887b7c73b7958ba8ac0ab3b3ae5e32ef9e4'), 'net/factory-cleanup-observer.c::static int lsf_cleanup_bootstrap_fits(': (500, '82af88e8d247cf16f9c13571aa6ce82d968edba7c54f9435cf317427747808bd')}


def ancestor_transform(outputs, primary):
    constructor_sources()
    require(type(outputs) is dict and len(outputs) == 410 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()),'vwindow-ancestor-input-shape')
    encoded=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(encoded).hexdigest() == ANCESTOR_INPUT_SHA,'vwindow-ancestor-whole-input')
    require(type(primary) is dict and set(primary) == set(ANCESTOR_PRIMARY),'vwindow-ancestor-primary-set')
    for n,pin in ANCESTOR_PRIMARY.items():
        require(_bound(primary[n],pin),'vwindow-ancestor-whole-primary')
    for n,pin in ANCESTOR_PREIMAGES.items():
        require(_bound(outputs[n],pin),'vwindow-ancestor-whole-preimage')
    for key,pin in ANCESTOR_BODIES.items():
        n,prefix=key.split('::',1)
        text=outputs[n].decode()
        require(text.count(prefix)==1 and
            (text.index(prefix)==0 or text[text.index(prefix)-1]=='\n'),
            'vwindow-ancestor-complete-declaration')
        require(_bound(function(text,prefix).encode(),pin),'vwindow-ancestor-whole-body')
    result=dict(outputs)
    path='mm/lsf-stream-constructor-vwindow.c'
    window=Editor(outputs[path].decode())
    window.edit('#include <net/lsf_stream_constructor_vwindow_private.h>\n',
        '#include <net/lsf_stream_constructor_vwindow_private.h>\n'
        '#include <linux/overflow.h>\n#include <asm/pgalloc.h>\n')
    window.edit('    unsigned int imported;\n',
        '    unsigned int imported;\n    unsigned int ancestors_published;\n'
        '    p4d_t p4d[MAX_PTRS_PER_P4D] __aligned(PAGE_SIZE);\n'
        '    pud_t pud[PTRS_PER_PUD] __aligned(PAGE_SIZE);\n'
        '    pmd_t pmd[PTRS_PER_PMD] __aligned(PAGE_SIZE);\n')
    window.edit('} lsf_stream_vwindow;\n','} lsf_stream_vwindow;\n'
        '#include "lsf-stream-constructor-vwindow-ancestors.c"\n')
    original=function(window.text,'static void __init lsf_stream_vwindow_register(')
    # Exact original wrapper/inverse is pinned. Native first-free placement is
    # refined because a present ancestry is not owner provenance. The new
    # boot helper selects a genuine zero root slot and calls native add_early.
    window.edit(original,'''static void __init lsf_stream_vwindow_register(void)
{
    (void)lsf_stream_vwindow_preprovision();
}
''')
    result[path]=window.finish().encode()
    factory=Editor(outputs['net/factory.c'].decode())
    factory.edit('#include <linux/module.h>\n','#include <linux/module.h>\n'
        '#include <linux/overflow.h>\n#include <net/lsf_stream_constructor_vwindow_private.h>\n')
    result['net/factory.c']=factory.finish().encode()
    budget=Editor(outputs['net/factory-cleanup-observer.c'].decode())
    original=function(budget.text,'static int lsf_cleanup_bootstrap_fits(')
    anchor='    unsigned long observers = lsf_cleanup_observer_bootstrap_bytes();\n'
    require(original.count(anchor)==1,'vwindow-original-all-bootstrap-terms')
    addition=anchor+'''    unsigned long window, alignment;
    /* Same original retained bootstrap remainder, BEFORE physical entry.
     * Actual complete static object includes all arrays, native descriptors,
     * internal/tail padding and flags. Charge worst-case start alignment too;
     * no actual field is zeroed, omitted or shifted into the Root arena. */
    if (lsf_prepaid_stream_vwindow_static_geometry(&window, &alignment) != 1 ||
        !window || !alignment || alignment > PAGE_SIZE ||
        (alignment & (alignment - 1u)) ||
        check_add_overflow(window, alignment - 1u, &window) ||
        check_add_overflow(fixed, window, &fixed)) return 0;
'''
    budget.edit(original,original.replace(anchor,addition))
    result['net/factory-cleanup-observer.c']=budget.finish().encode()
    destination='mm/lsf-stream-constructor-vwindow-ancestors.c'
    require(destination not in outputs,'vwindow-ancestor-new-fragment')
    raw=_constructor_source('stream-constructor-vwindow-ancestors.c')
    require(raw and len(raw)<16384 and b'\r' not in raw,'vwindow-ancestor-fragment-bound')
    result[destination]=raw
    for n in ['arch/x86/include/asm/pgalloc.h','include/asm-generic/pgalloc.h',
              'arch/x86/include/asm/pgtable_64_types.h']:
        require(n not in outputs,'vwindow-ancestor-new-header')
        result[n]=primary[n]
    return result


# Actual Root-bank PTE attachment/retirement; intentionally separate from the
# frozen static ancestor source. Full MMIO view/caller integration is later.
LEAF_INPUT_SHA = 'aec9bff62f308b66acd801067c55798b1adf0afed994317288d944b906337b11'
LEAF_PREIMAGES = {'net/factory-stream-rx-preallocate.c': (46747, 'bc7e0042c3e730cec7e20219e35a39ae3f48b9464680409c72620c6947bcaa05'), 'net/device-prepaid.h': (19044, 'c1589dac76fd18b809bb895b73887cb6e3074a548fac4ce9958a9d8a6fc964bf'), 'net/factory.c': (37768, '61838947efcbcfc88aac08f293daa39e1fe15b35cb52822629d5c6492d8e198d'), 'drivers/pci/bus.c': (13188, '4c6ccb0c196dbb7c733b85f838456d634e799b39844691c33802899864f77f30'), 'net/factory-stream-stop.c': (6416, '0f8be0b7c85fb11cdeb725da7c00047642b567031e8ca1c716f7bb1b31c37596'), 'net/factory-stream-root-final-free.c': (14013, '8755c6b9c5102a6b5549d33e45a4ca8d699b5cb78812c67ceeea88363eb7e41d'), 'mm/lsf-stream-constructor-vwindow.c': (2543, '984507b151a7b7374750cc723efc720a982dacc31f0478a91d4cf53581eca836')}
LEAF_BODIES = {'drivers/pci/bus.c::void pci_bus_add_device(': (1382, 'c563a688f0ded7d51192c1821d1268c1b82c91771d4aa2f49ff4f7edbe3accc6'), 'net/factory-stream-stop.c::static int lsf_factory_stream_stop(': (3545, '3843c093bd0b4743a036d0f69c565937f71dfa332ec1a361cc2f42d38b790cb8'), 'net/factory-stream-root-final-free.c::static int lsf_stream_root_closed_locked(': (3092, 'd3451a19a474c9d9571113f9a7c0a2cec1e15e4ab858a826697d3c68399d1cdb')}
LEAF_FILES = {
    'include/net/lsf_stream_constructor_pte_private.h': 'stream-constructor-pte-private.h',
    'net/factory-stream-pte.c': 'factory-stream-pte.c',
    'mm/lsf-stream-constructor-vwindow-pte.c': 'stream-constructor-vwindow-pte.c',
}


def leaf_transform(outputs):
    constructor_sources()
    require(type(outputs) is dict and len(outputs) == 414 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()),'vwindow-leaf-input-shape')
    encoded=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(encoded).hexdigest() == LEAF_INPUT_SHA,'vwindow-leaf-whole-input')
    for n,pin in LEAF_PREIMAGES.items():require(_bound(outputs[n],pin),'vwindow-leaf-whole-preimage')
    for key,pin in LEAF_BODIES.items():
        n,prefix=key.split('::',1);text=outputs[n].decode()
        require(text.count(prefix)==1 and (text.index(prefix)==0 or text[text.index(prefix)-1]=='\n'),
                'vwindow-leaf-complete-declaration')
        require(_bound(function(text,prefix).encode(),pin),'vwindow-leaf-full-body')
    result=dict(outputs)
    state=Editor(outputs['net/factory-stream-rx-preallocate.c'].decode())
    state.edit('    struct task_struct *mapping_stop_task; /* Exact original synchronous stop borrow. */\n',
        '    struct task_struct *mapping_stop_task; /* Exact original synchronous stop borrow. */\n'
        '    void *vwindow_leaf;\n    struct lsf_prepaid_ticket vwindow_leaf_ticket;\n'
        '    unsigned int vwindow_live_views;\n')
    result['net/factory-stream-rx-preallocate.c']=state.finish().encode()
    kinds=Editor(outputs['net/device-prepaid.h'].decode())
    kinds.edit('#define LSF_DEVICE_STREAM_PAT 0x17au\n',
        '#define LSF_DEVICE_STREAM_PAT 0x17au\n#define LSF_DEVICE_STREAM_PTE_LEAF 0x17bu\n')
    kinds.edit('        kind == LSF_DEVICE_STREAM_RESOURCE || kind == LSF_DEVICE_STREAM_PAT ||',
        '        kind == LSF_DEVICE_STREAM_PTE_LEAF ||\n'
        '        kind == LSF_DEVICE_STREAM_RESOURCE || kind == LSF_DEVICE_STREAM_PAT ||')
    result['net/device-prepaid.h']=kinds.finish().encode()
    factory=Editor(outputs['net/factory.c'].decode())
    factory.edit('#include <linux/module.h>\n','#include <linux/module.h>\n'
        '#include <net/lsf_stream_constructor_pte_private.h>\n')
    factory.edit('#include "factory-stream-mapping.c"\n',
        '#include "factory-stream-mapping.c"\n#include "factory-stream-pte.c"\n')
    result['net/factory.c']=factory.finish().encode()
    bus=Editor(outputs['drivers/pci/bus.c'].decode())
    bus.edit('#include <linux/pci.h>\n','#include <linux/pci.h>\n'
        '#ifdef CONFIG_LSF_STREAM_FACTORY\n#include <net/lsf_stream_constructor_pte_private.h>\n#endif\n')
    bus.edit('\t\tif (error != 1) return;\n\t\tlsf_prepaid_stream_pci_bus_add_device(dev);',
        '\t\tif (error != 1) return;\n'
        '\t\terror = lsf_factory_stream_pte_prepare(dev);\n'
        '\t\tif (error != 1) {\n\t\t\tlsf_factory_stream_bind_end(&reference, error);\n'
        '\t\t\treturn;\n\t\t}\n\t\tlsf_prepaid_stream_pci_bus_add_device(dev);')
    result['drivers/pci/bus.c']=bus.finish().encode()
    stop=Editor(outputs['net/factory-stream-stop.c'].decode())
    stop.edit('            pci_stop_and_remove_bus_device_locked(pci);\n',
        '            pci_stop_and_remove_bus_device_locked(pci);\n'
        '            if (lsf_factory_stream_pte_retire(pci) != 1) result = -EOPNOTSUPP;\n')
    result['net/factory-stream-stop.c']=stop.finish().encode()
    root=Editor(outputs['net/factory-stream-root-final-free.c'].decode())
    root.edit('        state->vp_tail_object || state->mapping_stop_task) return 0;',
        '        state->vp_tail_object || state->mapping_stop_task || state->vwindow_leaf ||\n'
        '        state->vwindow_leaf_ticket.slot || state->vwindow_leaf_ticket.generation ||\n'
        '        state->vwindow_live_views) return 0;')
    result['net/factory-stream-root-final-free.c']=root.finish().encode()
    window=Editor(outputs['mm/lsf-stream-constructor-vwindow.c'].decode())
    window.edit(window.text,window.text+'\n#include "lsf-stream-constructor-vwindow-pte.c"\n')
    result['mm/lsf-stream-constructor-vwindow.c']=window.finish().encode()
    for destination,name in LEAF_FILES.items():
        require(destination not in outputs,'vwindow-leaf-new-file')
        raw=_constructor_source(name)
        require(raw and len(raw)<32768 and b'\r' not in raw,'vwindow-leaf-source-bound')
        result[destination]=raw
    return result


# Closed protected MMIO increment, after the separately frozen Root-leaf stage.
# No old definition/tuple is retagged. This stage remains unselected source.
MMIO_INPUT_SHA = '4df5a1974e6d0ba7f568d64962f02c57aac7b85b076ae7f3bd9e8407bb4013dc'
MMIO_PRIMARY = {'arch/x86/mm/ioremap.c': (25575, 'f1aaca82ffe0ae49cda91949eca5cf812686fcef76e545f8c866cd2910c4ff22'), 'drivers/pci/iomap.c': (6398, '5d6f0ebaa4d44587bbb0587b7f84454c99dbc6ce8e25f5fca4e75826ae0a3578'), 'drivers/virtio/virtio_pci_modern_dev.c': (22423, 'f13ee888d9f2d8207c714714a6497c7b44c07206b573989c572090c1e1aabc47'), 'include/linux/kmsan.h': (11793, '95dec7df4903a40aab86c3bb6a56eb5f72a0796f180d8a463ebbfb7afabe0f5e'), 'arch/x86/include/asm/vmalloc.h': (560, 'ded5d5eee94255a94a6e2bc9bcea720b29c668572704ee153c760297828a0173')}
MMIO_PREIMAGES = {'net/device-prepaid.h': (19132, '698186a8da2fa0c3905fc38d4a20362280c1db3afb1a4e8c07d9ad393c0d7bc3'), 'net/factory.c': (37852, '0d921cdfd4bc88c39300d15b14a7b50af2bdea12dbed009d421aab7a00e702ba'), 'net/factory-stream-rx-preallocate.c': (46859, 'd8fbc0ddec1ab68abb2026d5e2959f9160d8913ec7ab1b33299abfc0b0743c45'), 'mm/lsf-stream-constructor-vwindow.c': (2592, 'ac7c8f0eda8c7b89f18c86849b8899801ddb2cc9820b0edb1e25fa138a15a5e2'), 'drivers/virtio/virtio_pci_common.c': (27085, '3009396403ba596c637f6a87ae085a072a26e4ca367a0944571e5d28164cf580')}
MMIO_BODIES = {'arch/x86/mm/ioremap.c::static void __iomem *\n__ioremap_caller(': (3663, '1bf5888e8b4ced4af180ab4e53b4a6103d33762efbe160103184ee33e53f2466'), 'arch/x86/mm/ioremap.c::void __iomem *ioremap(': (512, '4e228d80cc7e503b208ff81ea7dd56a1e2e551f58d9cc62c6564e3c430ddf654'), 'arch/x86/mm/ioremap.c::void iounmap(': (1457, '15c1662a68e5ce4fd703f77cf652c419e0efec5fed485e86d9fcde32bcf54967'), 'drivers/pci/iomap.c::void __iomem *pci_iomap_range(': (635, '80e55856ab321b2fd347dc8f55db2221a0d8f8c2033ac25ed5eee28df7fb54fc'), 'drivers/virtio/virtio_pci_modern_dev.c::int vp_modern_probe(': (4421, '5c69bde310a5a7957a216594177035c2ac51588fdbd8cb3a52c0064b19324380'), 'drivers/virtio/virtio_pci_modern_dev.c::void vp_modern_remove(': (362, 'f52efaffe46dd42ae8d05ad52c3703bff2afd3860906c102f5da1182b68412af'), 'drivers/virtio/virtio_pci_common.c::static void virtio_pci_remove(': (598, '10f1c2b0a2e2092a6f2482d34def0912896cb550475830d19bcd4011a174603e')}
MMIO_CALLER_PAIRS = [['resource_size_t phys_addr, unsigned long size,', 'struct pci_dev *pci, resource_size_t phys_addr, unsigned long size,'], ['\tstruct vm_struct *area;', '\tstruct lsf_stream_mmio_view *area;\n\tstruct memtype *pat = NULL;'], ['\tretval = memtype_reserve(phys_addr, (u64)phys_addr + size,\n\t\t\t\t\t\tpcm, &new_pcm);', '\tretval = lsf_prepaid_stream_memtype_reserve(pci, phys_addr, (u64)phys_addr + size,\n\t\t\t\t\tpcm, &new_pcm, &pat);'], ['\tarea = get_vm_area_caller(size, VM_IOREMAP, caller);\n\tif (!area)\n\t\tgoto err_free_memtype;\n\tarea->phys_addr = phys_addr;\n\tvaddr = (unsigned long) area->addr;\n', '\tarea = lsf_factory_stream_mmio_allocate(pci, phys_addr, size, offset, prot, pat);\n\tif (!area)\n\t\tgoto err_free_memtype;\n\tvaddr = area->virtual_start;\n\n\t/* Preserve the real native sync call only for its source-known\n\t * no-CPA-growth branch. Unknown RAM/direct-map changes refuse. */\n\tif (!lsf_stream_ioremap_no_cpa_growth(phys_addr))\n\t\tgoto err_free_area;\n'], ['\tif (ioremap_page_range(vaddr, vaddr + size, phys_addr, prot))\n\t\tgoto err_free_area;\n', '\tif (lsf_prepaid_stream_mmio_map(area) != 1)\n\t\tgoto err_free_area;\n'], ['\tif (memtype_kernel_map_sync(phys_addr, size, pcm))\n\t\tgoto err_free_area;\n', '\tif (memtype_kernel_map_sync(phys_addr, size, pcm)) {\n\t\tlsf_factory_stream_constructor_retain_unknown();\n\t\treturn NULL; /* Unexpected global effect: retain all paid owners. */\n\t}\n'], ['err_free_area:\n\tfree_vm_area(area);\nerr_free_memtype:\n\tmemtype_free(phys_addr, phys_addr + size);', 'err_free_area:\n\t(void)lsf_stream_ioremap_cancel(area);\n\treturn NULL;\nerr_free_memtype:\n\tif (lsf_prepaid_stream_memtype_free(pci, pat))\n\t\tlsf_factory_stream_constructor_retain_unknown();']]
MMIO_DEFAULT_PAIRS = [['(resource_size_t phys_addr, unsigned long size)', '(struct pci_dev *pci, resource_size_t phys_addr, unsigned long size)'], ['\tenum page_cache_mode pcm = _PAGE_CACHE_MODE_UC_MINUS;\n', '\tenum page_cache_mode pcm = _PAGE_CACHE_MODE_UC_MINUS;\n\tif (lsf_factory_stream_mmio_pci_selected(pci) != 1) return NULL;\n'], ['__ioremap_caller(phys_addr, size, pcm,', 'lsf_stream_ioremap_caller(pci, phys_addr, size, pcm,']]
MMIO_PROBE_PAIRS = [['if ((u64)notify_length + (notify_offset % PAGE_SIZE) <= PAGE_SIZE) {', '/* SAME aggregate private window funds this complete actual capability;\n\t * oversized/overflow fails through real earlier-view rollback. */\n\t{'], ['\t} else {\n\t\tmdev->notify_map_cap = notify;\n\t}', '\t} /* Owned whole-notify branch: no per-VQ fallback. */'], ['pci_iounmap(pci_dev, mdev->notify_base);', 'lsf_stream_mmio_drop_field(mdev, &mdev->notify_base);'], ['pci_iounmap(pci_dev, mdev->isr);', 'lsf_stream_mmio_drop_field(mdev, &mdev->isr);'], ['pci_iounmap(pci_dev, mdev->common);', 'lsf_stream_mmio_drop_field(mdev, &mdev->common);']]
MMIO_REMOVE_PAIRS = [['pci_iounmap(pci_dev, mdev->device);', 'lsf_stream_mmio_drop_field(mdev, &mdev->device);'], ['pci_iounmap(pci_dev, mdev->notify_base);', 'lsf_stream_mmio_drop_field(mdev, &mdev->notify_base);'], ['pci_iounmap(pci_dev, mdev->isr);', 'lsf_stream_mmio_drop_field(mdev, &mdev->isr);'], ['pci_iounmap(pci_dev, mdev->common);', 'lsf_stream_mmio_drop_field(mdev, &mdev->common);']]
MMIO_COMMON_PAIRS = [['\tunregister_virtio_device(&vp_dev->vdev);\n', '\tunregister_virtio_device(&vp_dev->vdev);\n\tif (lsf_factory_stream_mmio_unregister_returned(pci_dev, &vp_dev->vdev) != 1 ||\n\t    READ_ONCE(vp_dev->isr) != READ_ONCE(vp_dev->mdev.isr)) {\n\t\tlsf_factory_stream_constructor_retain_unknown();\n\t\tpci_disable_device(pci_dev);\n\t\tput_device(dev);\n\t\treturn;\n\t}\n\tWRITE_ONCE(vp_dev->isr, NULL); /* IRQ/VQ borrowers ended before BAR alias return. */\n']]
MMIO_VP_GETTERS = "\nint lsf_prepaid_stream_mmio_mdev_layout(const void *object, const void *mdev,\n    const struct pci_dev *pci, const void *alias, unsigned int opening)\n{\n    const struct virtio_pci_device *vp = object;\n    static_assert(offsetof(struct virtio_pci_device, vdev) == 0);\n    static_assert(sizeof(vp->mdev.common) == sizeof(void *));\n    static_assert(sizeof(vp->mdev.isr) == sizeof(void *));\n    static_assert(sizeof(vp->mdev.device) == sizeof(void *));\n    static_assert(sizeof(vp->mdev.notify_base) == sizeof(void *));\n    /* Caller proved the exact paid complete VP type/extent before this\n     * real allocating-TU layout helper may read its immutable PCI field. */\n    if (mdev != &vp->mdev || READ_ONCE(vp->mdev.pci_dev) != pci) return 0;\n    /* A new probe must not overwrite an earlier paid mapping alias or\n     * opt back into the native per-VQ notification mapping route. */\n    if (opening && (READ_ONCE(vp->mdev.common) || READ_ONCE(vp->mdev.isr) ||\n        READ_ONCE(vp->mdev.device) || READ_ONCE(vp->mdev.notify_base) ||\n        READ_ONCE(vp->mdev.notify_map_cap))) return 0;\n    return !alias || alias == &vp->mdev.common || alias == &vp->mdev.isr ||\n        alias == &vp->mdev.device || alias == &vp->mdev.notify_base;\n}\nconst struct pci_dev *lsf_prepaid_stream_mmio_outside_mdev_pci(const void *object)\n{\n    const struct virtio_pci_modern_device *mdev = object;\n    /* Outside-bank ordinary public caller's native type contract only.\n     * Its result grants REFUSAL on mixed/private ancestry, never authority. */\n    return READ_ONCE(mdev->pci_dev);\n}\n"
MMIO_IOMAP_PAIRS = [('return __pci_ioport_map(dev, start, len);', 'return NULL; /* Protected profile admits MMIO only. */'), ('return ioremap(start, len);', 'return lsf_prepaid_stream_ioremap(dev, start, len);')]
MMIO_FILES = {
    'include/net/lsf_stream_constructor_mmio_private.h': 'stream-constructor-mmio-private.h',
    'net/factory-stream-mmio.c': 'factory-stream-mmio.c',
    'mm/lsf-stream-constructor-vwindow-mmio.c': 'stream-constructor-vwindow-mmio.c',
    'arch/x86/mm/lsf-stream-constructor-ioremap.c': 'stream-constructor-ioremap.c',
    'drivers/virtio/lsf-stream-constructor-mmio-modern.c': 'stream-constructor-mmio-modern.c',
}


def _mmio_body(raw, path, prefix):
    text=raw.decode()
    require(text.count(prefix)==1 and (text.index(prefix)==0 or text[text.index(prefix)-1]=='\n'),
            'mmio-complete-function-declaration')
    body=function(text,prefix)
    require(_bound(body.encode(),MMIO_BODIES[path+'::'+prefix]),'mmio-whole-function')
    return body


def mmio_transform(outputs, primary):
    constructor_sources()
    from tools.host_stream_kernel_stream_constructor import _clone, _wrap
    require(type(outputs) is dict and len(outputs)==417 and
        all(type(n) is str and type(b) is bytes for n,b in outputs.items()),'mmio-input-shape')
    encoded=(json.dumps({n:{'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
        for n,b in outputs.items()},sort_keys=True,separators=(',',':'))+'\n').encode()
    require(hashlib.sha256(encoded).hexdigest()==MMIO_INPUT_SHA,'mmio-whole-input')
    require(type(primary) is dict and set(primary)==set(MMIO_PRIMARY),'mmio-primary-set')
    for n,pin in MMIO_PRIMARY.items():
        require(_bound(primary[n],pin),'mmio-whole-primary')
        require(n not in outputs,'mmio-new-primary')
    for n,pin in MMIO_PREIMAGES.items(): require(_bound(outputs[n],pin),'mmio-whole-preimage')
    bodies={key:_mmio_body(primary.get(key.split('::',1)[0],outputs.get(key.split('::',1)[0])),
                *key.split('::',1)) for key in MMIO_BODIES}
    raw={}
    for destination,name in MMIO_FILES.items():
        require(destination not in outputs,'mmio-new-private-file')
        b=_constructor_source(name)
        require(b and len(b)<32768 and b'\r' not in b and b.endswith(b'\n'),'mmio-private-source-bound')
        raw[destination]=b
    caller=_clone(bodies['arch/x86/mm/ioremap.c::static void __iomem *\n__ioremap_caller('],
                  'lsf_stream_ioremap_caller',MMIO_CALLER_PAIRS)
    default=_clone(bodies['arch/x86/mm/ioremap.c::void __iomem *ioremap('],
                   'lsf_prepaid_stream_ioremap',MMIO_DEFAULT_PAIRS)
    owned=raw['arch/x86/mm/lsf-stream-constructor-ioremap.c'].decode()
    require(function(owned,'static void __iomem *\nlsf_stream_ioremap_caller(')==caller and
        function(owned,'void __iomem *lsf_prepaid_stream_ioremap(')==default,'mmio-native-ioremap-clones')
    probe='static '+_clone(bodies['drivers/virtio/virtio_pci_modern_dev.c::int vp_modern_probe('],
                          'lsf_stream_mmio_modern_probe',MMIO_PROBE_PAIRS)
    remove='static '+_clone(bodies['drivers/virtio/virtio_pci_modern_dev.c::void vp_modern_remove('],
                           'lsf_stream_mmio_modern_remove',MMIO_REMOVE_PAIRS)
    owned=raw['drivers/virtio/lsf-stream-constructor-mmio-modern.c'].decode()
    require(function(owned,'static int lsf_stream_mmio_modern_probe(')==probe and
        function(owned,'static void lsf_stream_mmio_modern_remove(')==remove,'mmio-native-modern-clones')
    result=dict(outputs)
    kinds=Editor(outputs['net/device-prepaid.h'].decode())
    kinds.edit('#define LSF_DEVICE_STREAM_PTE_LEAF 0x17bu\n',
        '#define LSF_DEVICE_STREAM_PTE_LEAF 0x17bu\n#define LSF_DEVICE_STREAM_MMIO_VIEW 0x17cu\n')
    kinds.edit('        kind == LSF_DEVICE_STREAM_PTE_LEAF ||',
        '        kind == LSF_DEVICE_STREAM_MMIO_VIEW ||\n        kind == LSF_DEVICE_STREAM_PTE_LEAF ||')
    result['net/device-prepaid.h']=kinds.finish().encode()
    state=Editor(outputs['net/factory-stream-rx-preallocate.c'].decode())
    state.edit('    unsigned int vwindow_live_views;\n',
        '    unsigned int vwindow_live_views;\n    u64 vwindow_cursor; /* Monotonic: no view range is reused. */\n'
        '    unsigned int vwindow_unregister_done; /* Actual native return witness. */\n')
    result['net/factory-stream-rx-preallocate.c']=state.finish().encode()
    factory=Editor(outputs['net/factory.c'].decode())
    factory.edit('#include <linux/module.h>\n','#include <linux/module.h>\n'
        '#include <net/lsf_stream_constructor_mmio_private.h>\n')
    factory.edit('#include "factory-stream-pte.c"\n',
        '#include "factory-stream-pte.c"\n#include "factory-stream-mmio.c"\n')
    result['net/factory.c']=factory.finish().encode()
    window=Editor(outputs['mm/lsf-stream-constructor-vwindow.c'].decode())
    window.edit(window.text,window.text+'\n#include "lsf-stream-constructor-vwindow-mmio.c"\n')
    result['mm/lsf-stream-constructor-vwindow.c']=window.finish().encode()
    path='arch/x86/mm/ioremap.c';e=Editor(primary[path].decode())
    e.edit('#include <linux/kmsan.h>\n','#include <linux/kmsan.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_constructor_mmio_private.h>\n#endif\n')
    original=bodies[path+'::static void __iomem *\n__ioremap_caller(']
    e.edit(original,_wrap(original,'    if (lsf_factory_stream_mmio_task()) return NULL;\n'))
    original=bodies[path+'::void iounmap(']
    e.edit(original,_wrap(original,'    if (lsf_prepaid_stream_iounmap(addr)) return;\n'))
    e.edit(e.text,e.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-constructor-ioremap.c"\n#endif\n')
    result[path]=e.finish().encode()
    path='drivers/pci/iomap.c';e=Editor(primary[path].decode())
    e.edit('#include <linux/io.h>\n','#include <linux/io.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_constructor_mmio_private.h>\n#endif\n')
    original=bodies[path+'::void __iomem *pci_iomap_range(']
    clone='static '+_clone(original,'lsf_stream_mmio_pci_iomap_range',MMIO_IOMAP_PAIRS)
    branch='    int selected = lsf_factory_stream_mmio_pci_selected(dev);\n'
    branch+='    if (selected) return selected == 1 ? lsf_stream_mmio_pci_iomap_range(dev, bar, offset, maxlen) : NULL;\n'
    e.edit(original,'#ifdef CONFIG_LSF_STREAM_FACTORY\n'+clone+'#endif\n'+_wrap(original,branch))
    result[path]=e.finish().encode()
    path='drivers/virtio/virtio_pci_modern_dev.c';e=Editor(primary[path].decode())
    e.edit('#include <linux/delay.h>\n','#include <linux/delay.h>\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '#include <net/lsf_stream_constructor_mmio_private.h>\n'
        '#include <net/lsf_stream_constructor_private.h>\n'
        'static int lsf_stream_mmio_modern_probe(struct virtio_pci_modern_device *mdev);\n'
        'static void lsf_stream_mmio_modern_remove(struct virtio_pci_modern_device *mdev);\n#endif\n')
    for prefix,opening,branch in [('int vp_modern_probe(',1,
        '    if (selected) return selected == 1 ? lsf_stream_mmio_modern_probe(mdev) : -EOPNOTSUPP;\n'),
        ('void vp_modern_remove(',0,
        '    if (selected) {\n        if (selected == 1) lsf_stream_mmio_modern_remove(mdev);\n'
        '        else lsf_factory_stream_constructor_retain_unknown();\n        return;\n    }\n')]:
        original=bodies[path+'::'+prefix]
        e.edit(original,_wrap(original,'    int selected = lsf_factory_stream_mmio_modern_selected(mdev, '+str(opening)+'u);\n'+branch))
    e.edit(e.text,e.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n#include "lsf-stream-constructor-mmio-modern.c"\n#endif\n')
    result[path]=e.finish().encode()
    path='drivers/virtio/virtio_pci_common.c';e=Editor(outputs[path].decode())
    e.edit('#include <net/lsf_stream_constructor_private.h>\n',
        '#include <net/lsf_stream_constructor_private.h>\n#include <net/lsf_stream_constructor_mmio_private.h>\n')
    original=bodies[path+'::static void virtio_pci_remove(']
    clone=_clone(original,'lsf_stream_mmio_pci_remove',MMIO_COMMON_PAIRS)
    branch='    int selected = lsf_factory_stream_mmio_pci_selected(pci_dev);\n'
    branch+='    if (selected) {\n        if (lsf_factory_stream_mmio_remove_allowed(pci_dev) == 1)\n'
    branch+='            lsf_stream_mmio_pci_remove(pci_dev);\n'
    branch+='        else lsf_factory_stream_constructor_retain_unknown();\n        return;\n    }\n'
    e.edit(original,'#ifdef CONFIG_LSF_STREAM_FACTORY\n'+clone+'#endif\n'+_wrap(original,branch))
    e.edit(e.text,e.text+'\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'+MMIO_VP_GETTERS+'#endif\n')
    result[path]=e.finish().encode()
    for path in ['include/linux/kmsan.h','arch/x86/include/asm/vmalloc.h']: result[path]=primary[path]
    result.update(raw)
    require(len(result)==427,'mmio-output-count')
    return result
