"""Finite stopped-backup/expansion drill on the actual signed static node."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import time

from tools.phase2_operator_process import read_json, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_web_scenario import http_response, tree_inventory
from tools.run_security_profile_workflow import replace_config


def restore_drill(client, args, directory, config, node, hosts, publications, apply, capacity):
    before = capacity(client, args)
    records = {name: client.call('web', 'get', '--publication', publication)['data']['record']
               for name, publication in publications.items()}
    selected = {method: client.call('trigger', 'get', 'csr-a-' + method)['data']['trigger']
                for method in ('get', 'head')}
    stop(client, node)
    original_shutdown = stopped_record(node)
    require(original_shutdown['record']['clean'], 'maintenance-source-not-cleanly-stopped')
    inventory = tree_inventory(directory, client, maximum_bytes=256 * 1024 * 1024)
    restored = directory.parent / 'restored-installation'
    hardlinks, copied_bytes, copied_files = {}, 0, 0

    def copy(source, target):
        nonlocal copied_bytes, copied_files
        client.cancellation.check()
        require(time.monotonic() < client.deadline, 'maintenance-copy-deadline')
        source, target = Path(source), Path(target)
        info = source.lstat()
        copied_files += 1
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and copied_files <= 1024,
                'maintenance-regular-owned-file-required')
        identity = (info.st_dev, info.st_ino)
        if identity in hardlinks:
            os.link(hardlinks[identity], target)
        else:
            copied_bytes += info.st_size
            require(copied_bytes <= 256 * 1024 * 1024, 'maintenance-copy-byte-bound')
            shutil.copy2(source, target, follow_symlinks=False)
            hardlinks[identity] = target
        require(stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(info.st_mode), 'maintenance-mode-changed')
        return str(target)

    # The original remains stopped and intact. No individual catalog files are
    # removed, merged, or copied while a node can mutate this installation.
    shutil.copytree(directory, restored, copy_function=copy, symlinks=False)
    require(tree_inventory(restored, client) == inventory
            and tree_inventory(directory, client) == inventory, 'maintenance-copy-content-mismatch')
    for relative in inventory:
        source, target = directory / relative, restored / relative
        require(source.stat().st_nlink == target.stat().st_nlink, 'maintenance-hardlinks-not-preserved')
        with target.open('rb') as stream:
            os.fsync(stream.fileno())
    for parent, children, _files in os.walk(restored, topdown=False):
        for name in [parent, *(str(Path(parent) / child) for child in children)]:
            descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    restored_config = restored / config.name
    value = read_json(restored_config)
    old_limit = value['catalogs']['releaseEntries']
    value['catalogs']['releaseEntries'] = old_limit * 2
    replace_config(restored_config, value)
    floor = read_json(restored / 'data/supply-chain/floor.json')['restartNotBefore']
    require(isinstance(floor, int) and floor > 0 and floor - int(time.time()) <= 6, 'maintenance-clock-floor-bound')
    while int(time.time()) < floor:
        client.cancellation.check()
        require(time.monotonic() < client.deadline, 'maintenance-restart-deadline')
        time.sleep(0.05)
    replacement = connect(client, args.node, restored, restored_config, 'tests', 2)
    try:
        for name, publication in publications.items():
            require(client.call('web', 'get', '--publication', publication)['data']['record'] == records[name],
                    'maintenance-publication-history-changed')
        for method in ('get', 'head'):
            require(client.call('trigger', 'get', 'csr-a-' + method)['data']['trigger'] == selected[method],
                    'maintenance-current-route-changed')
        after = capacity(client, args)
        require(before['accounting'] == after['accounting'], 'maintenance-content-accounting-changed')
        for name in ('csr-a', 'csr-b', 'csr-a'):
            for method in ('GET', 'HEAD'):
                apply(client, 'csr-a-' + method.lower(), publications[name], hosts['csr'], method=method)
            http_response(client, replacement, hosts['csr'], '/orders/42', headers={'Accept': 'text/html'})
        require(b'Static guide' in http_response(client, replacement, hosts['csr'], '/docs/guide/')[0],
                'maintenance-unrelated-publication-changed')
        return replacement, {'passed': True, 'stoppedSourceUnchanged': True, 'restoredExactHistory': True,
            'hardlinksAndProtectedModesPreserved': True, 'explicitRollback': True,
            'unrelatedPublicationPreserved': True, 'originalPublicationLimit': old_limit,
            'expandedPublicationLimit': old_limit * 2, 'uniqueCopiedBytes': copied_bytes,
            'copiedFiles': copied_files, 'originalShutdown': original_shutdown}
    except BaseException:
        client.node = None
        replacement.close()
        raise
