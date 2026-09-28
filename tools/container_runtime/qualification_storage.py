"""Persistent publication update, stopped snapshot and restore on real local volumes."""
import json
import time

from qualification import INSIDE

SCRIPT = '/source/tools/container_runtime/qualification_storage_inside.py'


def run(drill, node, volumes, mounts, mount, source, native):
    primitives = drill.exec_json(node, '/usr/local/bin/python3', '/source/tools/container_runtime/qualification_primitives.py', '/var/lib/lsf')
    producer = drill.container('updated-site', ['--user', '10001:10001', '-e', 'TMPDIR=/work', *source, *native,
        *mount(volumes['work'], '/work'), drill.args.frontend_image, '/source/tools/container_runtime/qualification_update.mjs'])
    drill.attached(producer, 'updated-site.json')
    update = drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'update')
    backup = drill.volume('backup')
    # Mount the fresh volume at the image's node-owned cache path so Docker copies its protected root metadata.
    snapshot_mount = mount(backup, '/var/cache/lsf')
    installation = [*mount(volumes['config'], '/installation/config', True),
        *mount(volumes['data'], '/installation/data'), *mount(volumes['cache'], '/installation/cache', True)]
    arguments = ['--entrypoint', '/usr/local/bin/python3', *source, *installation, *snapshot_mount,
        drill.args.image, '-I', '/source/tools/container_runtime/storage.py', 'snapshot', '--source', '/installation',
        '--output', '/var/cache/lsf/snapshot']
    live = drill.container('reject-live-backup', arguments)
    rejected = drill.attached(live, 'reject-live-backup.txt', codes=(1,))
    if b'container-state-is-owned-stop-the-existing-node' not in rejected:
        raise RuntimeError('live-backup-rejection-reason')
    drill.docker('stop', '--time', '10', node, timeout=15)
    time.sleep(6)
    drill.docker('start', node)
    drill.ready(node)
    after_update = drill.exec_json(node, '/usr/local/bin/python3', SCRIPT, 'recovered')
    drill.exec_json(node, '/usr/local/bin/python3', INSIDE, 'reopen')
    drill.docker('stop', '--time', '10', node, timeout=15)
    snapshot = drill.container('snapshot', arguments)
    copied = json.loads(drill.attached(snapshot, 'snapshot.json'))
    recovered = drill.volume('restored')
    restore = drill.container('restore', ['--entrypoint', '/usr/local/bin/python3', *source,
        *mount(backup, '/backup'), *mount(recovered, '/var/cache/lsf'), drill.args.image, '-I',
        '/source/tools/container_runtime/storage.py', 'restore', '--source', '/backup/snapshot',
        '--output', '/var/cache/lsf/installation'])
    restored = json.loads(drill.attached(restore, 'restore.json'))
    # All coupled roots were restored together before any restored node is allowed to start.
    restored_mounts = ['--mount', f'type=volume,source={recovered},target=/etc/lsf,volume-subpath=installation/config,readonly',
        '--mount', f'type=volume,source={recovered},target=/var/lib/lsf,volume-subpath=installation/data',
        '--mount', f'type=volume,source={recovered},target=/var/cache/lsf,volume-subpath=installation/cache',
        *mount(volumes['work'], '/work', True)]
    replacement = drill.container('restored-node', [*restored_mounts, *source, drill.args.image])
    time.sleep(6)
    drill.docker('start', replacement)
    drill.ready(replacement)
    recovered_receipt = drill.exec_json(replacement, '/usr/local/bin/python3', SCRIPT, 'recovered')
    rollback = drill.exec_json(replacement, '/usr/local/bin/python3', SCRIPT, 'rollback')
    drill.exec_json(replacement, '/usr/local/bin/python3', INSIDE, 'reopen')
    drill.docker('stop', '--time', '10', replacement, timeout=15)
    for stopped in (node, replacement):
        if json.loads(drill.docker('inspect', '--format', '{{.State.ExitCode}}', stopped)[1]) != 0:
            raise RuntimeError('storage-node-shutdown-failed')
    result = {'passed': True, 'localFilesystem': primitives, 'update': update, 'updateRestart': after_update,
              'snapshot': copied, 'restore': restored, 'restoredReceipt': recovered_receipt, 'rollback': rollback,
              'liveBackupRejected': True, 'unrelatedSitePreserved': True, 'cloudQualified': False}
    (drill.output / 'storage.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
