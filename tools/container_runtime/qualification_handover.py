"""Real overlapping containers, stop-before-start replacement and abandoned-owner recovery."""
import json
import time

from qualification import INSIDE


def run(drill, current, mounts, source):
    replacement = drill.container('replacement', [*mounts, *source, drill.args.image])
    # Separate network namespaces rule out a port collision masquerading as an owner fence.
    denied = json.loads(drill.attached(replacement, 'overlap-rejected.json', codes=(1,)))
    if denied.get('reason') != 'container-state-is-owned-stop-the-existing-node':
        raise RuntimeError('overlap-did-not-fail-at-shared-owner-fence')
    drill.ready(current)
    drill.exec_json(current, '/usr/local/bin/python3', INSIDE, 'reopen')
    current_identity = drill.docker('inspect', '--format', '{{.Image}}', current)[1].strip()
    replacement_identity = drill.docker('inspect', '--format', '{{.Image}}', replacement)[1].strip()
    if current_identity != replacement_identity:
        raise RuntimeError('runtime-rollback-pair-not-qualified')
    began = time.monotonic()
    drill.docker('stop', '--time', '10', current, timeout=15)
    if json.loads(drill.docker('inspect', '--format', '{{.State.ExitCode}}', current)[1]) != 0:
        raise RuntimeError('old-owner-not-cleanly-stopped')
    time.sleep(6)
    drill.docker('start', replacement)
    drill.ready(replacement)
    replaced = drill.exec_json(replacement, '/usr/local/bin/python3', INSIDE, 'reopen')
    cutover = round((time.monotonic() - began) * 1000)
    # Termination abandons the process, not the fence inode or any catalog state.
    # This is a real SIGKILL, distinct from power-loss or a mid-transaction fault.
    interrupted = time.monotonic()
    drill.docker('kill', '--signal', 'KILL', replacement)
    exit_code = int(drill.docker('wait', replacement, timeout=15)[1])
    if exit_code != 137:
        raise RuntimeError('forced-owner-termination-not-observed')
    time.sleep(6)
    # This explicit rollback returns to the SAME authenticated image/state format.
    # A different native release needs its own approved compatibility proof.
    drill.docker('start', current)
    drill.ready(current)
    recovered = drill.exec_json(current, '/usr/local/bin/python3', INSIDE, 'reopen')
    recovered_receipts = []
    for name in ('site', 'documentation'):
        result = drill.exec_json(current, '/opt/lsf/release/bin/latent', '--config', '/etc/lsf/client.json',
            '--output', 'json', 'web', 'operation', 'container-' + name)
        if result.get('outcomeKnown') is not True or result.get('category') != 'success':
            raise RuntimeError('handover-publication-receipt-not-recovered')
        recovered_receipts.append(name)
    outage = round((time.monotonic() - interrupted) * 1000)
    report = {'schemaVersion': 'latent.container-handover.v1', 'passed': True,
              'separateNamespaceOverlapRejected': True, 'oldOwnerStayedReady': True,
              'stopBeforeStart': True, 'replacement': replaced, 'forcedTerminationExitCode': exit_code,
              'rollback': recovered, 'publicationReceiptsRecovered': recovered_receipts,
              'rollbackEligibility': 'same-authenticated-image-and-coupled-state-format',
              'imageId': current_identity.decode(), 'cleanCutoverMillis': cutover,
              'forcedTerminationToVerifiedRecoveryMillis': outage,
              'lockFilesDeleted': False, 'cloudQualified': False, 'powerLossQualified': False}
    (drill.output / 'handover.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
