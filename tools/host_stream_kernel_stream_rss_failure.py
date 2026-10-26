"""Unselected exact failed-probe return of the original prepaid RSS view.

The original failed probe loses its last driver-private RSS alias at free_netdev.
Only the existing typed owner returns that view here; ordinary allocations and
the original errno, queue reset and teardown order remain unchanged.
"""
import hashlib
from tools.host_stream_kernel_constructor_failure import Editor
from tools.host_stream_kernel_device_security import function
from tools.host_stream_kernel_cleanup_native import require

NET = 'drivers/net/virtio_net.c'
RSS = 'net/factory-stream-rss.c'
NET_BYTES = 194233
NET_SHA = '476dce1e6eda799842420735412613dfce1a835b9cead68f7466c5f97cd65c84'
PROBE_BYTES = 11326
PROBE_SHA = 'd7293e198134da48a6ac75b89efc9a1d46108df0f74d48bc764ce35e0ad995e6'
RSS_PINS = {
    'int lsf_factory_stream_rss_take(': (1655,
        '7b6a5c2415e82af372e7a7f23d3ca821c802c41567df805f7721d0eeb059eefb'),
    'int lsf_factory_stream_rss_return(': (1993,
        'd848796cad5c6bf646d2da3eb05f5bd05a3789e6a4b229b13ff51e10a59b9059'),
}


def transform(outputs):
    require(type(outputs) is dict and type(outputs.get(NET)) is bytes
        and type(outputs.get(RSS)) is bytes, 'stream-rss-failure-exact-stage')
    raw = outputs[NET]
    require(len(raw) == NET_BYTES and hashlib.sha256(raw).hexdigest() == NET_SHA,
        'stream-rss-failure-net-preimage')
    # The actual selected birth rejects RSS/HASH_REPORT before allocation.
    # Its unused one-entry header never escapes to a device control queue.
    # Keep that admission and the actual parent/alias/return fences exact.
    for signature, (size, digest) in RSS_PINS.items():
        body = function(outputs[RSS].decode(), signature).encode()
        require(len(body) == size and hashlib.sha256(body).hexdigest() == digest,
            'stream-rss-failure-original-owner')
    source = raw.decode()
    original = function(source, 'static int virtnet_probe(')
    require(len(original.encode()) == PROBE_BYTES
        and hashlib.sha256(original.encode()).hexdigest() == PROBE_SHA,
        'stream-rss-failure-probe-preimage')
    probe = Editor(original)
    probe.edit('free:\n\tfree_netdev(dev);\n\treturn err;\n',
        'free:\n#ifdef CONFIG_LSF_STREAM_FACTORY\n'
        '\t/* Last probe-owned alias, before the actual NETDEV private tail dies.\n'
        '\t * Only an existing prepaid birth can return; unknown keeps its owner.\n'
        '\t * Outside allocations keep the original failed-probe behavior. */\n'
        '\t(void)lsf_factory_stream_rss_return(vdev, &vi->rss_hdr);\n'
        '#endif\n\tfree_netdev(dev);\n\treturn err;\n')
    editor = Editor(source)
    editor.edit(original, probe.finish())
    result = dict(outputs)
    result[NET] = editor.finish().encode()
    return result
