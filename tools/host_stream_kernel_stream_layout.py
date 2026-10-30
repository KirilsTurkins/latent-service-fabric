"""Fixed readonly allocating-TU probe and ELF data reader; never execute objects.

The frozen notification58/375 is an exact intermediate. This source reports a
known minimum, not a complete native cost or activation/installation authority.
"""
from __future__ import annotations
import hashlib
import json
import struct
from tools.host_stream_kernel_constructor_failure import Editor

MAGIC = 0x4c53464c41593031
VERSION = 1
MAX_OBJECT = 16*1024**2
MAX_REPORT = 64*1024
MAX_FACT = 16*1024**2
INPUT_SHA = '8c34faa41636437aeeca9602af1dd63b1b251354a69b25c7c5745e63e20fb677'
DESCRIPTOR = (('drivers/net/virtio_net.c', (('virtnet.private', 'sizeof(struct virtnet_info)', '__alignof__(struct virtnet_info)', 'embedded in actual NETDEV main; do not charge separately', None), ('rx.head', 'SKB_DATA_ALIGN(sizeof(struct virtio_net_hdr_mrg_rxbuf) + VIRTNET_RX_PAD + GOOD_PACKET_LEN) + SKB_DATA_ALIGN(sizeof(struct skb_shared_info))', '64', 'separate continuous RX backing', 'LSF_STREAM_RX_DESCRIPTORS'), ('rx.header', 'sizeof(struct sk_buff)', '__alignof__(struct sk_buff)', 'separate continuous RX headers', 'LSF_STREAM_RX_DESCRIPTORS'), ('rx.queue', 'sizeof(struct receive_queue)', '__alignof__(struct receive_queue)', 'one prepaid RX queue array', 1), ('tx.queue', 'sizeof(struct send_queue)', '__alignof__(struct send_queue)', 'one prepaid TX queue array', 1), ('skb.shared_info', 'sizeof(struct skb_shared_info)', '__alignof__(struct skb_shared_info)', 'embedded in rx.head expression; no second charge', None), ('virtio.v1_header', 'sizeof(struct virtio_net_hdr_mrg_rxbuf)', '__alignof__(struct virtio_net_hdr_mrg_rxbuf)', 'embedded in rx.head expression; no second charge', None), ('rss', 'struct_size((struct virtio_net_rss_config_hdr *)0, indirection_table, 1)', '__alignof__(struct virtio_net_rss_config_hdr)', 'actual RSS=false still one indirection entry', 1), ('temporary.vqs', '2 * sizeof(struct virtqueue *)', '__alignof__(struct virtqueue *)', 'returned before completion but cursor/record not reused', 1), ('temporary.info', '2 * sizeof(struct virtqueue_info)', '__alignof__(struct virtqueue_info)', 'returned before completion but cursor/record not reused', 1), ('temporary.ctx', '2 * sizeof(bool)', '__alignof__(bool)', 'returned before completion but cursor/record not reused', 1), ('netdev.main', 'struct_size((struct net_device *)0, priv, sizeof(struct virtnet_info))', '__alignof__(struct net_device)', 'actual flexible-tail expression, both complete types visible here', 1), ('netdev.base', 'sizeof(struct net_device)', '__alignof__(struct net_device)', 'fact-only', None), ('netdev.priv_offset', 'offsetof(struct net_device, priv)', None, 'fact-only', None), ('netdev.priv_element', 'sizeof(((struct net_device *)0)->priv[0])', None, 'fact-only', None), ('rx.descriptors', 'LSF_STREAM_RX_DESCRIPTORS', None, 'fact-only', None), ('tx.descriptors', 'LSF_STREAM_TX_DESCRIPTORS', None, 'fact-only', None), ('rx.pad', 'VIRTNET_RX_PAD', None, 'fact-only', None), ('rx.good_packet', 'GOOD_PACKET_LEN', None, 'fact-only', None), ('cache.bytes', 'SMP_CACHE_BYTES', None, 'fact-only', None), ('skb.max_frags', 'MAX_SKB_FRAGS', None, 'fact-only', None), ('page.bytes', 'PAGE_SIZE', None, 'fact-only', None))), ('drivers/virtio/virtio_ring.c', (('ring.rx', 'PAGE_ALIGN(vring_size(LSF_STREAM_RX_DESCRIPTORS, SMP_CACHE_BYTES))', 'PAGE_SIZE', 'actual separate prepaid ordered views', 1), ('ring.tx', 'PAGE_ALIGN(vring_size(LSF_STREAM_TX_DESCRIPTORS, SMP_CACHE_BYTES))', 'PAGE_SIZE', 'actual separate prepaid ordered views', 1), ('state.rx', 'sizeof(struct vring_desc_state_split) * LSF_STREAM_RX_DESCRIPTORS', '__alignof__(struct vring_desc_state_split)', 'actual separate prepaid ordered views', 1), ('state.tx', 'sizeof(struct vring_desc_state_split) * LSF_STREAM_TX_DESCRIPTORS', '__alignof__(struct vring_desc_state_split)', 'actual separate prepaid ordered views', 1), ('extra.rx', 'sizeof(struct vring_desc_extra) * LSF_STREAM_RX_DESCRIPTORS', '__alignof__(struct vring_desc_extra)', 'actual separate prepaid ordered views', 1), ('extra.tx', 'sizeof(struct vring_desc_extra) * LSF_STREAM_TX_DESCRIPTORS', '__alignof__(struct vring_desc_extra)', 'actual separate prepaid ordered views', 1), ('virtqueue', 'sizeof(struct vring_virtqueue)', '__alignof__(struct vring_virtqueue)', 'actual separate prepaid ordered views', 2), ('state.type', 'sizeof(struct vring_desc_state_split)', '__alignof__(struct vring_desc_state_split)', 'fact-only', None), ('extra.type', 'sizeof(struct vring_desc_extra)', '__alignof__(struct vring_desc_extra)', 'fact-only', None), ('cache.bytes', 'SMP_CACHE_BYTES', None, 'fact-only', None), ('page.bytes', 'PAGE_SIZE', None, 'fact-only', None), ('rx.descriptors', 'LSF_STREAM_RX_DESCRIPTORS', None, 'fact-only', None), ('tx.descriptors', 'LSF_STREAM_TX_DESCRIPTORS', None, 'fact-only', None))), ('net/core/dev.c', (('netdev.base', 'sizeof(struct net_device)', '__alignof__(struct net_device)', 'fact-only', None), ('netdev.priv_offset', 'offsetof(struct net_device, priv)', None, 'fact-only', None), ('netdev.priv_element', 'sizeof(((struct net_device *)0)->priv[0])', None, 'fact-only', None), ('netdev.flex_zero', 'struct_size((struct net_device *)0, priv, 0)', None, 'fact-only', None), ('netdev.flex_one', 'struct_size((struct net_device *)0, priv, 1)', None, 'fact-only', None), ('netdev.tx', 'sizeof(*((struct net_device *)0)->_tx)', '__alignof__(*((struct net_device *)0)->_tx)', 'actual fixed child', 1), ('netdev.rx', 'sizeof(*((struct net_device *)0)->_rx)', '__alignof__(*((struct net_device *)0)->_rx)', 'actual fixed child', 1), ('netdev.ethtool', 'sizeof(*((struct net_device *)0)->ethtool)', '__alignof__(*((struct net_device *)0)->ethtool)', 'actual fixed child', 1), ('netdev.primary_name', 'sizeof(struct netdev_name_node)', '__alignof__(struct netdev_name_node)', 'primary name only; caller bitmap remains separate', 1))), ('net/factory.c', (('root.state', 'sizeof(struct lsf_factory_device_state)', '__alignof__(struct lsf_factory_device_state)', 'actual original Root arena birth', 1), ('root.firmware', 'sizeof(struct lsf_factory_device_firmware)', '__alignof__(struct lsf_factory_device_firmware)', 'actual original PCI firmware descriptor; source path determines presence', None), ('rx.state', 'sizeof(struct lsf_stream_rx_state)', '__alignof__(struct lsf_stream_rx_state)', 'one state includes inline metadata arrays', 1), ('cpu.storage', 'sizeof(struct lsf_stream_netdev_cpu_storage)', '__alignof__(struct lsf_stream_netdev_cpu_storage)', 'one whole 64CPU object, not64 allocations', 1), ('rx.head_descriptor', 'sizeof(struct lsf_stream_rx_head)', '__alignof__(struct lsf_stream_rx_head)', 'embedded in rx.state; no second charge', None), ('rx.header_descriptor', 'sizeof(struct lsf_stream_rx_header)', '__alignof__(struct lsf_stream_rx_header)', 'embedded in rx.state; no second charge', None), ('pci.type', 'sizeof(struct pci_dev)', '__alignof__(struct pci_dev)', 'per actual original typed birth', None), ('virtio.public', 'sizeof(struct virtio_device)', '__alignof__(struct virtio_device)', 'may be embedded in private transport; no second charge', None), ('kobject.public', 'sizeof(struct kobject)', '__alignof__(struct kobject)', 'often embedded; no second charge', None), ('kernfs.public', 'sizeof(struct kernfs_node)', '__alignof__(struct kernfs_node)', 'per actual directory birth', None), ('radix.node', 'sizeof(struct radix_tree_node)', '__alignof__(struct radix_tree_node)', 'per actual growth; count not inferred from type', None), ('file.public', 'sizeof(struct file)', '__alignof__(struct file)', 'prebank/root overhead fact; not automatic infra charge', None), ('inode.public', 'sizeof(struct inode)', '__alignof__(struct inode)', 'prebank/root overhead fact; not automatic infra charge', None), ('global.factory', 'sizeof(factory)', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('global.retirement', 'sizeof(lsf_retirement)', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('global.retirement_wait', 'sizeof(lsf_retirement_wait)', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('global.rx_pointer', 'sizeof(lsf_stream_rx)', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('global.records', 'sizeof(factory.pool.records)', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('global.record', 'sizeof(factory.pool.records[0])', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('backing.bytes', 'LSF_BACKING_BYTES', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('bootstrap.ceiling', 'LSF_BOOTSTRAP_CEILING', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('infra.offset', 'LSF_FACTORY_INFRA_OFFSET', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('infra.bytes', 'LSF_FACTORY_INFRA_BYTES', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('tcp.bytes', 'LSF_TCP_BYTES', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('dns.bytes', 'LSF_DNS_BYTES', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('records.count', 'LSF_ALLOCATION_SLOTS', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('owners.count', 'LSF_OWNER_SLOTS', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('application_contexts', 'LSF_FACTORY_CONTEXTS', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('cpus', 'NR_CPUS', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('name.ifsize', 'IFNAMSIZ', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None), ('name.netclass', 'sizeof("net")', None, 'typed fact or static/bootstrap accounting; not duplicate arena allocation', None))), ('drivers/base/core.c', (('device.private', 'sizeof(struct device_private)', '__alignof__(struct device_private)', 'per actual birth; embedded device itself not extra charge', None), ('class_dir', 'sizeof(struct class_dir)', '__alignof__(struct class_dir)', 'per actual birth; embedded device itself not extra charge', None), ('device.public', 'sizeof(struct device)', '__alignof__(struct device)', 'per actual birth; embedded device itself not extra charge', None))), ('fs/kernfs/dir.c', (('kernfs.node', 'sizeof(struct kernfs_node)', '__alignof__(struct kernfs_node)', 'crosscheck factory fact; per actual selected directory birth', None), ('kernfs.root', 'sizeof(struct kernfs_root)', '__alignof__(struct kernfs_root)', 'original shared sysfs root, not private per-NETDEV birth', None), ('kernfs.iattrs', 'sizeof(struct kernfs_iattrs)', '__alignof__(struct kernfs_iattrs)', 'type fact only; current private source refuses inherited/unsupported attrs', None))), ('security/selinux/hooks.c', (('selinux.file', 'sizeof(struct file_security_struct)', '__alignof__(struct file_security_struct)', 'type fact; actual prebank/prefix/per-socket source ownership separately classified', None), ('selinux.inode', 'sizeof(struct inode_security_struct)', '__alignof__(struct inode_security_struct)', 'type fact; actual prebank/prefix/per-socket source ownership separately classified', None), ('selinux.task', 'sizeof(struct task_security_struct)', '__alignof__(struct task_security_struct)', 'type fact; actual prebank/prefix/per-socket source ownership separately classified', None), ('selinux.socket', 'sizeof(struct sk_security_struct)', '__alignof__(struct sk_security_struct)', 'type fact; actual prebank/prefix/per-socket source ownership separately classified', None))), ('drivers/virtio/virtio_pci_common.c', (('vp.private', 'sizeof(struct virtio_pci_device)', '__alignof__(struct virtio_pci_device)', 'actual private allocating TU; per real constructor birth', None), ('vq.info', 'sizeof(struct virtio_pci_vq_info)', '__alignof__(struct virtio_pci_vq_info)', 'actual private allocating TU; per real constructor birth', None), ('vp.vqs', '2 * sizeof(*((struct virtio_pci_device *)0)->vqs)', '__alignof__(* ((struct virtio_pci_device *)0)->vqs)', 'actual pointer slot and optional backing distinct; retries/counts not guessed', None), ('msix.name_element', 'sizeof(*((struct virtio_pci_device *)0)->msix_names)', '__alignof__(* ((struct virtio_pci_device *)0)->msix_names)', 'actual pointer slot and optional backing distinct; retries/counts not guessed', None), ('msix.mask_slot', 'sizeof(*((struct virtio_pci_device *)0)->msix_affinity_masks)', '__alignof__(* ((struct virtio_pci_device *)0)->msix_affinity_masks)', 'actual pointer slot and optional backing distinct; retries/counts not guessed', None), ('msix.cpumask_type', 'sizeof(struct cpumask)', '__alignof__(struct cpumask)', 'actual pointer slot and optional backing distinct; retries/counts not guessed', None), ('msix.offstack_enabled', 'IS_ENABLED(CONFIG_CPUMASK_OFFSTACK)', None, 'actual pointer slot and optional backing distinct; retries/counts not guessed', None), ('msix.optional_backing', 'IS_ENABLED(CONFIG_CPUMASK_OFFSTACK) ? cpumask_size() : 0', None, 'actual pointer slot and optional backing distinct; retries/counts not guessed', None))), ('drivers/acpi/glue.c', ()), ('drivers/base/swnode.c', ()), ('drivers/usb/core/usb-acpi.c', ()))
UNKNOWN = ('IRQ action/descriptors/domains and actual MSIX retry multiplicities', 'AVC nodes/xperms/SID caches/audit and runtime LSM blob-offset totals when reached', 'dynamic device-name bitmap/caller strings until actual sites are source-bound', 'shared IDR growth/counts and global parent provenance', 'earlier NETDEV_POST_INIT retained writers/callback descendants', 'constructor/cleanup work/kthread/RCU/stack transient costs not measured by the selected fields', 'full TCP/TX/IPv6/UDP/DNS/labels/neighbour and close/failure/overlap graphs')

def require(value, code):
    if not value:
        raise ValueError('stream-layout-'+code)


def canonical(value):
    return (json.dumps(value,sort_keys=True,separators=(',',':'))+'\n').encode()


def identity(raw):
    return {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}


def descriptor(tu):
    require(type(tu) is str,'tu-type')
    for index,(name,fields) in enumerate(DESCRIPTOR,1):
        if tu==name:return index,fields
    raise ValueError('stream-layout-closed-tu')


def symbol_name(index):
    return 'lsf_stream_layout_'+str(index)


def section_name(index):
    return '.rodata.lsf_stream_layout_'+str(index)


def table_cells(fields):
    return 4+sum(3+(alignment is not None) for _,_,alignment,_,_ in fields)


def uses_emitter(fields):
    return any(any(token in expression for token in ('vring_size(', 'struct_size(', 'cpumask_size('))
        for _,expression,_,_,_ in fields)


def source_block(tu):
    index,fields=descriptor(tu)
    if not fields:return ''
    symbol,section=symbol_name(index),section_name(index)
    size=8*table_cells(fields)
    pre='\n#ifdef CONFIG_LSF_STREAM_FACTORY\n/* Fixed READONLY compile data; no object execution or allocation authority. */\n'
    if not uses_emitter(fields):
        cells=[hex(MAGIC)+'ULL','1ULL',str(index)+'ULL',str(len(fields))+'ULL']
        for field_id,(_,expression,alignment,_,_) in enumerate(fields,1):
            cells.extend((str(field_id)+'ULL',str(1+(alignment is not None))+'ULL',
                '(unsigned long long)('+expression+')'))
            if alignment is not None:cells.append('(unsigned long long)('+alignment+')')
        raw=(pre+'static const unsigned long long '+symbol+'[]\n'
            '    __attribute__((used,section("'+section+'"),aligned(8))) = {\n    '+
            ',\n    '.join(cells)+'\n};\n_Static_assert(sizeof('+symbol+') == '+str(size)+', "layout table width");\n#endif\n')
        return raw
    # Each row uses at most TWO immediate operands (GCC's operand cap is not
    # proportional to our field count). GNU as numbered subsections give one
    # deterministic table even if asm statements are scheduled separately.
    # Every row/header is a multiple of eight, so subsection padding adds none.
    header=('.pushsection '+section+',0,"a",@progbits\n.balign 8\n.local '+symbol+
        '\n.type '+symbol+',@object\n'+symbol+':\n.quad '+str(MAGIC)+',1,'+
        str(index)+','+str(len(fields))+'\n.size '+symbol+','+str(size)+'\n.popsection\n')
    lines=[pre,'static void __attribute__((used,no_instrument_function)) lsf_stream_layout_emit_'+str(index)+'(void)\n{\n',
        '    __asm__ volatile ('+json.dumps(header)+');\n']
    for field_id,(_,expression,alignment,_,_) in enumerate(fields,1):
        asm=('.pushsection '+section+','+str(field_id)+',"a",@progbits\n.quad '+
            str(field_id)+','+str(1+(alignment is not None))+',%c0'+
            (',%c1' if alignment is not None else '')+'\n.popsection\n')
        operands=['"i" ((unsigned long long)('+expression+'))']
        if alignment is not None:operands.append('"i" ((unsigned long long)('+alignment+'))')
        lines.append('    __asm__ volatile ('+json.dumps(asm)+' : : '+', '.join(operands)+');\n')
    lines.append('}\n#endif\n')
    return ''.join(lines)


def transform(outputs):
    require(type(outputs) is dict and len(outputs)==375 and
        all(type(k) is str and type(v) is bytes for k,v in outputs.items()),'frozen-input-shape')
    require(hashlib.sha256(canonical({n:identity(raw) for n,raw in outputs.items()})).hexdigest()==INPUT_SHA,
        'frozen-375-whole-map')
    result=dict(outputs)
    for tu,fields in DESCRIPTOR:
        require(tu in outputs,'required-actual-tu')
        if not fields:continue
        block=source_block(tu)
        require('lsf_stream_layout_' not in outputs[tu].decode(),'fresh-constant-namespace')
        editor=Editor(outputs[tu].decode())
        editor.edit(editor.text,editor.text+block)
        result[tu]=editor.finish().encode()
    return result


def _name(strings, offset):
    require(type(offset) is int and 0<=offset<len(strings),'string-offset')
    end=strings.find(b'\0',offset,min(len(strings),offset+1024))
    require(end>=offset,'bounded-string')
    try:return strings[offset:end].decode('ascii')
    except UnicodeDecodeError:raise ValueError('stream-layout-ascii-symbol') from None


def decode(raw, tu):
    """Fixed table-only ELF reader. No addresses, DWARF or code execution."""
    index,fields=descriptor(tu)
    require(fields and type(raw) is bytes and 64<=len(raw)<=MAX_OBJECT,'object-bound')
    require(raw[:7]==b'\x7fELF\x02\x01\x01','elf64-little-endian')
    kind,machine,version,entry,phoff,shoff,flags,ehsize,phsize,phnum,shsize,shnum,shstr=struct.unpack_from('<HHIQQQIHHHHHH',raw,16)
    require((kind,machine,version,entry,phoff,phnum,flags,ehsize,shsize)==(1,62,1,0,0,0,0,64,64) and
        1<=shnum<=8192 and 0<shstr<shnum and 64<=shoff<=len(raw) and
        shnum*64<=len(raw)-shoff,'relocatable-section-header')
    sections=[struct.unpack_from('<IIQQQQIIQQ',raw,shoff+i*64) for i in range(shnum)]
    require(sections[0]==(0,)*10,'no-extended-section-indices')
    occupied=[(0,64),(shoff,shoff+shnum*64)]
    for _,stype,_,_,offset,size,_,_,alignment,_ in sections:
        require(offset<=len(raw) and (stype==8 or size<=len(raw)-offset),'section-file-bound')
        require(alignment==0 or alignment&(alignment-1)==0,'section-alignment')
        if stype not in (0,8) and size:occupied.append((offset,offset+size))
    occupied.sort()
    require(all(left[1]<=right[0] for left,right in zip(occupied,occupied[1:])),
        'nonoverlapping-file-backed-sections')
    strings=sections[shstr]
    require(strings[1]==3 and strings[5]>0,'section-string-table')
    names=raw[strings[4]:strings[4]+strings[5]]
    matches=[i for i,s in enumerate(sections) if _name(names,s[0])==section_name(index)]
    require(len(matches)==1,'one-layout-section')
    section_index=matches[0];section=sections[section_index]
    require(section[1]==1 and section[2]==2 and section[3]==0 and section[4]%8==0 and section[8]>=8 and
        section[9]==0 and section[5]==table_cells(fields)*8,'readonly-progbits-exact-size')
    symtabs=[i for i,s in enumerate(sections) if s[1]==2]
    require(len(symtabs)==1,'one-static-symbol-table')
    sym_index=symtabs[0];symbols=sections[sym_index]
    require(symbols[9]==24 and symbols[5]>0 and symbols[5]%24==0 and
        0<symbols[6]<shnum and sections[symbols[6]][1]==3,'symbol-table-shape')
    strings=sections[symbols[6]];names=raw[strings[4]:strings[4]+strings[5]]
    wanted=[]
    for i in range(symbols[5]//24):
        value=struct.unpack_from('<IBBHQQ',raw,symbols[4]+i*24)
        if _name(names,value[0])==symbol_name(index):wanted.append((i,value))
    require(len(wanted)==1,'one-layout-symbol')
    symbol_index,symbol=wanted[0]
    require(symbol[1]==1 and symbol[2]==0 and symbol[3]==section_index and
        symbol[4]==0 and symbol[5]==section[5],'local-object-symbol-exact-table')
    for s in sections:
        if s[1] not in (4,9):continue
        width=24 if s[1]==4 else 16
        require(s[9]==width and s[5]%width==0 and s[6]==sym_index and 0<s[7]<shnum,
            'relocation-table-shape')
        require(s[7]!=section_index or s[5]==0,'no-layout-section-relocations')
        for offset in range(s[4],s[4]+s[5],width):
            _,info=struct.unpack_from('<QQ',raw,offset)
            require(info>>32!=symbol_index,'no-layout-address-references')
    data=raw[section[4]:section[4]+section[5]]
    cells=struct.unpack('<'+'Q'*(len(data)//8),data)
    require(cells[:4]==(MAGIC,VERSION,index,len(fields)),'table-header')
    cursor=4;values={}
    for field_id,(name,_,alignment,_,_) in enumerate(fields,1):
        count=1+(alignment is not None)
        require(cells[cursor:cursor+2]==(field_id,count),'ordered-field-id-shape')
        value=cells[cursor+2];cursor+=3
        zero=name in {'rx.pad','msix.offstack_enabled','msix.optional_backing'}
        require(type(value) is int and (value>0 or zero) and value<=MAX_FACT,'fact-value-bound')
        row={'value':value}
        if alignment is not None:
            align=cells[cursor];cursor+=1
            require(0<align<=MAX_FACT and align&(align-1)==0,'fact-alignment')
            row['alignment']=align
        values[name]=row
    require(cursor==len(cells),'no-extra-cells')
    if 'msix.offstack_enabled' in values:
        enabled=values['msix.offstack_enabled']['value'];backing=values['msix.optional_backing']['value']
        require(enabled in (0,1) and (backing>0 if enabled else backing==0),'optional-backing-not-unknown-zero')
    return {'tu':tu,'tuId':index,'object':identity(raw),'section':{'name':section_name(index),
        'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'flags':section[2]},
        'symbol':symbol_name(index),'fields':values,'productExecuted':False}


def _fact(decoded, tu, name):
    require(tu in decoded and decoded[tu].get('tu')==tu,'complete-decoded-tu')
    row=decoded[tu]['fields'].get(name)
    require(type(row) is dict and type(row.get('value')) is int,'required-measured-fact')
    return row['value']


def prefix_report(decoded):
    expected={tu for tu,fields in DESCRIPTOR if fields}
    require(type(decoded) is dict and set(decoded)==expected,'all-and-only-data-producers')
    v,r,n,f='drivers/net/virtio_net.c','drivers/virtio/virtio_ring.c','net/core/dev.c','net/factory.c'
    value=lambda tu,name:_fact(decoded,tu,name)
    for name in ('netdev.base','netdev.priv_offset','netdev.priv_element'):
        require(value(v,name)==value(n,name),'cross-tu-netdev-public-layout')
    require(decoded[v]['fields']['netdev.base']['alignment']==decoded[n]['fields']['netdev.base']['alignment'],
        'cross-tu-netdev-alignment')
    for name in ('page.bytes','cache.bytes','rx.descriptors','tx.descriptors'):
        require(value(v,name)==value(r,name),'cross-tu-ring-profile')
    require(value(v,'page.bytes')==4096 and value(v,'rx.descriptors')==32 and
        value(v,'tx.descriptors')==64 and 0<value(v,'cache.bytes')<=64,'unchanged-ring-profile')
    for name,expected_value in {'backing.bytes':524288,'bootstrap.ceiling':1048576,
        'infra.offset':327680,'infra.bytes':196608,'tcp.bytes':98304,'dns.bytes':65536,
        'records.count':256,'owners.count':64,'application_contexts':4,'cpus':64}.items():
        require(value(f,name)==expected_value,'unchanged-original-partitions')
    require(value(f,'infra.offset')%4096==0,'actual-infra-base-page-alignment')
    require(value(f,'kernfs.public')==value('fs/kernfs/dir.c','kernfs.node'),'cross-tu-kernfs-layout')
    require(decoded[f]['fields']['kernfs.public']['alignment']==decoded['fs/kernfs/dir.c']['fields']['kernfs.node']['alignment'],
        'cross-tu-kernfs-alignment')
    sequence=[]
    def birth(name,tu,key,align):
        row=decoded[tu]['fields'][key]
        require(row.get('alignment',1)<=align,'allocator-cannot-represent-natural-alignment')
        sequence.append((name,row['value'],align))
    birth('original Root state',f,'root.state',64)
    birth('RX metadata state',f,'rx.state',64)
    for i in range(32):birth('RX head '+str(i),v,'rx.head',64)
    for i in range(32):birth('RX header '+str(i),v,'rx.header',64)
    for name,tu,key,align in [('RX queue',v,'rx.queue',64),('TX queue',v,'tx.queue',64),
        ('RX ring',r,'ring.rx',4096),('TX ring',r,'ring.tx',4096),
        ('RX states',r,'state.rx',64),('TX states',r,'state.tx',64),
        ('RX extras',r,'extra.rx',64),('TX extras',r,'extra.tx',64),
        ('RX vq',r,'virtqueue',64),('TX vq',r,'virtqueue',64)]:birth(name,tu,key,align)
    require(len(sequence)==76,'original-root-plus-75-rx-births')
    cursor=0;ledger=[]
    for index,(name,payload,alignment) in enumerate(sequence,1):
        start=(cursor+alignment-1)&~(alignment-1);extent=(payload+63)&~63
        require(start<=MAX_FACT and extent<=MAX_FACT and start+extent<=MAX_FACT,'ledger-arithmetic-bound')
        ledger.append({'birth':index,'name':name,'payloadBytes':payload,'requiredAlignment':alignment,
            'startPadding':start-cursor,'chargedExtent':extent,'minimumOffset':start,
            'minimumEnd':start+extent,'recordHighWater':index})
        cursor=start+extent
    require(value(f,'global.records')==value(f,'global.record')*256,'actual-record-array-shape')
    overflow=cursor>196608 or len(sequence)>256
    return {'schemaVersion':'lsf.stream-layout-data.v1','measured':decoded,
        'knownMinimum':{'scope':'isolated original Root plus fixed75 RX births; not an actual live entry cursor',
            'bytes':cursor,'recordHighWater':len(sequence),'rows':ledger,
            'status':'decisive-lower-bound-overflow' if overflow else 'insufficient-to-prove-fit'},
        'actualPreRxEntryCursor':None,'actualPreRxEntryOccupiedRecords':None,
        'constructorDemandFacts':{'scope':'measured shapes are not invented birth multiplicities',
            'mandatoryPriorBirthsAndCountsComplete':False,'returnedTemporaryBirthsReusable':False},
        'uncovered':list(UNKNOWN)+['actual prior observer/constructor occupancy before the RX reservation',
            'source-complete actual order/multiplicity of the remaining PCI/virtio/NETDEV/security births'],
        'prefixComplete':False,'compiledUsefulFit':False,'runtimeQualified':False,
        'consumerSelected':False,'whole738Complete':False,'productExecution':False}


def report_bytes(decoded):
    raw=canonical(prefix_report(decoded))
    require(len(raw)<=MAX_REPORT,'public-report-bound')
    return raw
