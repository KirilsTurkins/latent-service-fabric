"""Reviewed host parser preparation and captured selected-module checkpoints."""
import hashlib
import json
from pathlib import Path

from tools.build_observation import file_identity
from tools.rust_capsule_project import digest, read_file, write_json


LEGACY_YIELD_SHA256 = 'ea15d7acb007f314d876a434ceeb7c9e6b30180159959bb255e3be737e99f8b2'
FIFO_YIELD_SHA256 = '99fab873d692344f0bffd7e2d3543ca5e5c841f4d4f6ca556268694113b5d029'
FIFO_YIELD_TEST_SHA256 = '67f7147d0e5ee5112321c8396aabd05178ad6a4cd6709f3d2f3d2b43bd896e79'
STANDARD_ITERATOR = 'slices/iter.go'
STANDARD_ITERATOR_SHA256 = '986cce7d58c65e6f87987544908ec138ae664c4bf5c8868d2177a425f6fa2bbc'
STANDARD_ITERATOR_SITES = [(14, 57), (15, 40), (16, 24), (26, 62), (27, 40), (28, 37),
                           (37, 54), (38, 35), (39, 24), (50, 68), (51, 22), (59, 43),
                           (66, 50), (75, 66), (86, 72), (97, 64), (102, 39), (103, 35)]
STANDARD_MAP_ITERATOR = 'maps/iter.go'
STANDARD_MAP_ITERATOR_SHA256 = 'a803b5b1b09aa2dcedf90db32270f9cec310bc7cf8f141f87c2e6567db0c4208'
STANDARD_MAP_ITERATOR_SITES = [(12, 69), (13, 38), (14, 24), (25, 66), (26, 35), (27, 21),
                               (38, 68), (39, 35), (40, 24), (50, 77), (51, 25), (58, 65)]
STANDARD_STRING_ITERATOR = 'strings/iter.go'
STANDARD_STRING_ITERATOR_SHA256 = '067603fe06f2cec8ec607f9c9d469493901820f76af7f9e3e51136824fe8b04a'
STANDARD_BYTES_ITERATOR = 'bytes/iter.go'
STANDARD_BYTES_ITERATOR_SHA256 = '628f8dc51af2c70325050c0125340ec01c6a7da84c53f2f5ae3ec040c7e5fc6f'
STANDARD_TEXT_ITERATOR_SITES = [(18, 40), (19, 40), (20, 19), (36, 61), (37, 40),
                                (39, 20), (48, 8), (67, 48), (75, 53), (83, 44),
                                (84, 40), (86, 28), (116, 67), (117, 40), (119, 28)]
STANDARD_JSON_WIRE = 'encoding/json/internal/jsonwire/decode.go'
STANDARD_JSON_WIRE_SHA256 = '2ec579bfd801743cb8073f89d35c1f5540811e435b53793b2732cf57423e2eaa'
STANDARD_JSON_WIRE_SITES = [(28, 43), (29, 43), (30, 43), (33, 43), (35, 83), (43, 33),
                            (54, 34), (65, 33), (76, 63), (77, 47), (97, 45), (101, 69),
                            (117, 88), (123, 115), (137, 30), (139, 34), (142, 49),
                            (201, 39), (257, 60), (272, 32), (274, 34), (277, 53),
                            (390, 69), (391, 25), (413, 56), (426, 45), (433, 52),
                            (465, 50), (472, 125), (479, 64), (513, 63), (534, 63),
                            (556, 63), (568, 52), (572, 20), (593, 47), (596, 57)]
STANDARD_BASE64 = 'encoding/base64/base64.go'
STANDARD_BASE64_SHA256 = '15e67707bc3f0925f7f56bd4002106681c6b64ba5bf553b4d8cc0bb8eca71aa5'
STANDARD_BASE64_SITES = [(154, 21)]
STANDARD_BASE64_MODE = 'base64-encode-stride-v1'
STANDARD_BASE64_STRIDE = 256


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
    standard = {}
    modes = {}
    standard_iterators = {
        'slices': (STANDARD_ITERATOR, STANDARD_ITERATOR_SHA256, STANDARD_ITERATOR_SITES),
        'maps': (STANDARD_MAP_ITERATOR, STANDARD_MAP_ITERATOR_SHA256, STANDARD_MAP_ITERATOR_SITES),
        'strings': (STANDARD_STRING_ITERATOR, STANDARD_STRING_ITERATOR_SHA256, STANDARD_TEXT_ITERATOR_SITES),
        'bytes': (STANDARD_BYTES_ITERATOR, STANDARD_BYTES_ITERATOR_SHA256, STANDARD_TEXT_ITERATOR_SITES),
        'encoding/json/internal/jsonwire': (STANDARD_JSON_WIRE, STANDARD_JSON_WIRE_SHA256, STANDARD_JSON_WIRE_SITES),
        'encoding/base64': (STANDARD_BASE64, STANDARD_BASE64_SHA256, STANDARD_BASE64_SITES),
    }
    dispatcher = generated / 'vendor/go.bytecodealliance.org/pkg'
    for package in packages:
        iterator = standard_iterators.get(package.get('ImportPath'))
        if iterator:
            source_name, source_sha256, sites = iterator
            path = compiler.goroot / 'src' / source_name
            if (path in standard or not package.get('Standard') or Path(package['Dir']) != path.parent
                    or package.get('GoFiles', []).count(path.name) != 1
                    or hashlib.sha256(read_file(path)).hexdigest() != source_sha256):
                raise ValueError('go-checkpoint-standard-iterator-source-drift')
            selected.add(path)
            standard[path] = (source_name, source_sha256, sites)
            if source_name == STANDARD_BASE64:
                modes[path] = STANDARD_BASE64_MODE
            continue
        if package.get('Standard'):
            continue
        for name in package.get('GoFiles', []):
            path = Path(package['Dir']) / name
            if path in application_sources or path.is_relative_to(generated / 'vendor') and not path.is_relative_to(dispatcher):
                if not path.is_relative_to(generated) or path.is_symlink():
                    raise ValueError('go-checkpoint-source-outside-captured-module')
                selected.add(path)
    request = output / 'checkpoint-inputs.json'
    write_json(request, [{'path': str(path), 'diagnostic': str(path),
                          **({'mode': modes[path]} if path in modes else {})} for path in sorted(selected)])
    rows = json.loads(compiler.run('checkpoint-parser', 'go-checkpoints', request, output / 'checkpoints'))
    expected = {str(path) for path in selected}
    if (not isinstance(rows, list) or len(rows) != len(expected)
            or {row.get('path') for row in rows} != expected):
        raise ValueError('go-checkpoint-parser-returned-unselected-source')
    replacements, transformations = {}, []
    for row in rows:
        path = Path(row['path'])
        if path in standard:
            source_name, source_sha256, expected_sites = standard[path]
            sites = [{'line': line, 'column': column, 'suspendable': True}
                     for line, column in expected_sites]
            if source_name == STANDARD_BASE64:
                sites[0]['stride'] = STANDARD_BASE64_STRIDE
            if (row.get('sites') != sites
                    or any(type(site['line']) is not int or type(site['column']) is not int
                           or site['suspendable'] is not True for site in row['sites'])
                    or source_name == STANDARD_BASE64 and
                       type(row['sites'][0].get('stride')) is not int
                    or row.get('upstreamDigest') != 'sha256:' + source_sha256
                    or hashlib.sha256(read_file(path)).hexdigest() != source_sha256):
                raise ValueError('go-checkpoint-standard-iterator-output-drift')
        if not row['sites']:
            continue
        adapted = Path(row['adapted'])
        if adapted.parent != output / 'checkpoints' or adapted.is_symlink():
            raise ValueError('go-checkpoint-parser-output-outside-owned-directory')
        if digest(read_file(path)) != row['upstreamDigest'] or digest(read_file(adapted)) != row['adaptedDigest']:
            raise ValueError('go-checkpoint-parser-source-or-output-changed')
        replacements[str(path)] = str(adapted)
        source_name = ('standard/' + standard[path][0] if path in standard else path.relative_to(generated).as_posix())
        transformations.append({'name': 'go-compiler-checkpoints/' + source_name,
            'upstreamDigest': row['upstreamDigest'], 'adaptedDigest': row['adaptedDigest'], 'sites': row['sites']})
    return replacements, transformations
