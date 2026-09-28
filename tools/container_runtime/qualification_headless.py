"""Invoke the finite CI worker through the actual local Docker daemon."""
import json


def run(drill, node, mount, source):
    node_id = drill.docker('inspect', '--format', '{{.Id}}', node)[1].decode().strip()
    image = drill.docker('inspect', '--format', '{{.Image}}', node)[1].decode().strip()
    journal = drill.volume('operator-journals')
    # This is the HOST operator, explicitly holding local daemon authority. It is
    # not part of the unprivileged node image or a mount given to applications.
    worker = drill.container('ci-worker', ['--cap-add', 'SETUID', '--cap-add', 'SETGID', *source, *mount(journal, '/journal'),
        '--mount', 'type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock',
        drill.args.operator_image, node_id, image], memory='256m', pids='32')
    try:
        result = json.loads(drill.attached(worker, 'headless-operator.json', timeout=210))
    finally:
        # These disposable qualification journals contain no credential bytes.
        # Retain interrupted-operation evidence before removing owned test resources.
        drill.docker('cp', worker + ':/journal', drill.output / 'headless-journals')
    if result.get('passed') is not True:
        raise RuntimeError('headless-operator-did-not-complete')
    return result
