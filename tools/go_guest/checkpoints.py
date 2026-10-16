"""Reviewed host parser preparation and captured selected-module checkpoints."""
import json
from pathlib import Path

from tools.build_observation import file_identity
from tools.rust_capsule_project import digest, read_file, write_json


def prepare(compiler):
    # Build only this authenticated SDK compiler source. No selected application
    # module source is imported or executed in this toolchain preparation step.
    root = compiler.root / 'checkpoint-parser'
    root.mkdir()
    source = root / 'main.go'
    source.write_bytes(read_file(compiler.sdk / 'runtime/checkpoint_transform.go.in'))
    controls = root / 'main_test.go'
    controls.write_bytes(read_file(compiler.sdk / 'runtime/checkpoint_transform_test.go.in'))
    binary = root / 'go-checkpoints'
    previous_root, previous_environment = compiler.commands.root, dict(compiler.commands.environment)
    compiler.commands.root = root
    compiler.commands.environment.update(GOOS='linux', GOARCH='amd64', CGO_ENABLED='0', GOFLAGS='-mod=readonly',
                                         GOPROXY='off', GOSUMDB='off')
    try:
        host = compiler.run('checkpoint-parser-host', 'go', 'env', 'GOHOSTOS', 'GOHOSTARCH').split()
        if host != ['linux', 'amd64']:
            raise ValueError('go-checkpoint-parser-requires-maintained-linux-x86_64-host')
        compiler.run('checkpoint-parser-controls', 'go', 'test', '-count=1', source, controls)
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
