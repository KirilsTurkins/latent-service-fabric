"""Reviewed host parser preparation and captured selected-module checkpoints."""
import hashlib
import json
from pathlib import Path

from tools.build_observation import file_identity
from tools.rust_capsule_project import digest, read_file, write_json


LEGACY_YIELD_SHA256 = 'ea15d7acb007f314d876a434ceeb7c9e6b30180159959bb255e3be737e99f8b2'
FIFO_YIELD_SHA256 = '99fab873d692344f0bffd7e2d3543ca5e5c841f4d4f6ca556268694113b5d029'
FIFO_YIELD_TEST_SHA256 = '67f7147d0e5ee5112321c8396aabd05178ad6a4cd6709f3d2f3d2b43bd896e79'


def checkpoint_yield_template(sdk):
    """Select only an authenticated captured dispatcher template."""
    raw = read_file(sdk / 'runtime/checkpoint_async.go.in')
    identity = hashlib.sha256(raw).hexdigest()
    if identity == LEGACY_YIELD_SHA256:
        return 'legacy'
    if identity == FIFO_YIELD_SHA256:
        return 'fifo'
    raise ValueError('go-checkpoint-dispatcher-template-drift')


def checkpoint_queue_control_source(sdk):
    """Source-project the maintained queue into a private host-only fault control."""
    from tools.go_guest.runtime import replace_once
    text = read_file(sdk / 'runtime/checkpoint_async.go.in').decode('utf-8')
    text = replace_once(text, '//go:linkname lsfActivationYield runtime.lsfActivationYield\n', '')
    text = replace_once(text,
        '    waiter := &lsfYieldWait{channel: channel}\n    lsfPublishYield(waiter)\n',
        '    waiter := &lsfYieldWait{channel: channel}\n    checkpointQueueBeforePublish(channel)\n'
        '    lsfPublishYield(waiter)\n    checkpointQueueAfterPublish(channel)\n')
    return ('package main\n\ntype unit struct{}\n'
            'type taskState struct { yielding *lsfYieldWait; yieldTail *lsfYieldWait }\n'
            'var state *taskState\n\n' + text +
            '\nfunc Yield() {\n    channel := make(chan unit)\n    lsfQueueYield(channel)\n    (<-channel)\n}\n')


def prepare(compiler):
    # Build only this authenticated SDK compiler source. No selected application
    # module source is imported or executed in this toolchain preparation step.
    root = compiler.root / 'checkpoint-parser'
    root.mkdir()
    source = root / 'main.go'
    source.write_bytes(read_file(compiler.sdk / 'runtime/checkpoint_transform.go.in'))
    controls = root / 'main_test.go'
    controls.write_bytes(read_file(compiler.sdk / 'runtime/checkpoint_transform_test.go.in'))
    queue_inputs = []
    if checkpoint_yield_template(compiler.sdk) == 'fifo':
        queue_test = read_file(compiler.sdk / 'runtime/checkpoint_queue_test.go.in')
        if hashlib.sha256(queue_test).hexdigest() != FIFO_YIELD_TEST_SHA256:
            raise ValueError('go-checkpoint-dispatcher-control-drift')
        queue_source = root / 'checkpoint_queue.go'
        queue_source.write_text(checkpoint_queue_control_source(compiler.sdk), encoding='utf-8')
        queue_controls = root / 'checkpoint_queue_test.go'
        queue_controls.write_bytes(queue_test)
        queue_inputs = [queue_source, queue_controls]
    binary = root / 'go-checkpoints'
    previous_root, previous_environment = compiler.commands.root, dict(compiler.commands.environment)
    compiler.commands.root = root
    compiler.commands.environment.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOFLAGS='-mod=readonly',
                                         GOPROXY='off', GOSUMDB='off')
    try:
        host = compiler.run('checkpoint-parser-host', 'go', 'env', 'GOHOSTOS', 'GOHOSTARCH').split()
        if host != ['linux', 'amd64']:
            raise ValueError('go-checkpoint-parser-requires-maintained-linux-x86_64-host')
        compiler.run('checkpoint-parser-controls', 'go', 'test', '-count=1', source, controls, *queue_inputs)
        compiler.run('checkpoint-parser-build', 'go', 'build', '-o', binary, source)
    finally:
        compiler.commands.root = previous_root
        compiler.commands.environment.clear()
        compiler.commands.environment.update(previous_environment)
    compiler.paths['go-checkpoints'] = binary
    compiler.materials['go-checkpoints'] = file_identity(binary, 'go-checkpoints')


def transform(compiler, generated, packages, application_sources, output):
    selected = set()
    dispatcher = generated / 'vendor/go.bytecodealliance.org/pkg'
    for package in packages:
        if package.get('Standard'):
            continue
        for name in package.get('GoFiles', []):
            path = Path(package['Dir']) / name
            if path in application_sources or path.is_relative_to(generated / 'vendor') and not path.is_relative_to(dispatcher):
                if not path.is_relative_to(generated) or path.is_symlink():
                    raise ValueError('go-checkpoint-source-outside-captured-module')
                selected.add(path)
    request = output / 'checkpoint-inputs.json'
    write_json(request, [{'path': str(path), 'diagnostic': str(path)} for path in sorted(selected)])
    rows = json.loads(compiler.run('checkpoint-parser', 'go-checkpoints', request, output / 'checkpoints'))
    expected = {str(path) for path in selected}
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or {row.get('path') for row in rows} != expected):
        raise ValueError('go-checkpoint-parser-returned-unselected-source')
    replacements, transformations = {}, []
    for row in rows:
        if not row['sites']:
            continue
        path, adapted = Path(row['path']), Path(row['adapted'])
        if adapted.parent != output / 'checkpoints' or adapted.is_symlink():
            raise ValueError('go-checkpoint-parser-output-outside-owned-directory')
        if digest(read_file(path)) != row['upstreamDigest'] or digest(read_file(adapted)) != row['adaptedDigest']:
            raise ValueError('go-checkpoint-parser-source-or-output-changed')
        replacements[str(path)] = str(adapted)
        transformations.append({'name': 'go-compiler-checkpoints/' + path.relative_to(generated).as_posix(),
            'upstreamDigest': row['upstreamDigest'], 'adaptedDigest': row['adaptedDigest'], 'sites': row['sites']})
    return replacements, transformations
