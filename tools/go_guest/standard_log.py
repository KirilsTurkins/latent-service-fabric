"""Standard Go stdout/stderr through the explicitly declared typed log import."""
from __future__ import annotations

from pathlib import Path
import re

from tools.go_guest.runtime import replace_once
from tools.rust_capsule_project import digest

PROFILE = 'go-standard-logging-v1'
IMPORT = 'latent:log/log@0.1.0'
WRITE = '''func Write(fd int, b []byte) (int, error) {
	var nwritten size
	errno := fd_write(int32(fd), makeIOVec(b), 1, &nwritten)
	runtime.KeepAlive(b)
	return int(nwritten), errnoErr(errno)
}'''


def syscall_source(source: str) -> str:
    """The caller's ordinary syscall.Write retains its error/count contract."""
    return replace_once(source, WRITE, '''//go:linkname lsfStandardWrite
var lsfStandardWrite func(int, []byte) (int, error)

func Write(fd int, b []byte) (int, error) {
	if fd == 1 || fd == 2 {
		if lsfStandardWrite == nil { return 0, EBADF }
		return lsfStandardWrite(fd, b)
	}
	var nwritten size
	errno := fd_write(int32(fd), makeIOVec(b), 1, &nwritten)
	runtime.KeepAlive(b)
	return int(nwritten), errnoErr(errno)
}''')


def runtime_source(source: str) -> str:
    # Install the function before linked application initialization. A main
    # blank import alone does not order sibling dependency initializers before
    # an outside module whose init already writes to stdout.
    return replace_once(source, '\tdoInit(runtime_inittasks) // Must be before defer.',
        '\tlsfInstallStandardLog()\n\tdoInit(runtime_inittasks) // Must be before defer.') + (
        '\n//go:linkname lsfInstallStandardLog\nfunc lsfInstallStandardLog()\n')


def install(sdk: Path, module: Path, runtime_profile: str) -> tuple[bool, list[dict]]:
    """No declared import means no hook and no additional logging authority."""
    matches = []
    for path in sorted(module.glob('*/wit_bindings.go')):
        source = path.read_text(encoding='utf-8')
        if re.search(r'(?m)^//go:wasmimport ' + re.escape(IMPORT) + r' write$', source):
            matches.append((path, source))
    if not matches:
        return False, []
    if len(matches) != 1:
        raise ValueError('ambiguous-Go-standard-log-import')
    path, source = matches[0]
    package = re.search(r'(?m)^package ([A-Za-z][A-Za-z0-9_]*)$', source)
    if package is None or package[1] != path.parent.name:
        raise ValueError('unrecognized-Go-standard-log-package')
    # Generated owners, result lifting and guest allocations remain with the
    # actual pinned generator, rather than a handwritten canonical-ABI struct.
    for declaration in ('func Write(', 'type Field ', 'type LogError ',
                        'LevelInfo', 'LevelError', 'LogErrorBudgetExhausted', 'LogErrorInvalidField'):
        if declaration not in source:
            raise ValueError('generated-Go-standard-log-type-drift')
    entry = module / 'wit_exports.go'
    if not re.search(r'(?m)^package main$', entry.read_text(encoding='utf-8')):
        raise ValueError('generated-Go-standard-log-entry-drift')
    template = sdk / 'runtime/standard_log.go.in'
    raw = template.read_bytes()
    adapted = raw.replace(b'@raw@', path.parent.name.encode())
    targets = {
        module / 'lsf/standardlog/log.go': adapted,
        module / 'lsf_standard_log.go': b'package main\n\nimport _ "wit_component/lsf/standardlog"\n',
    }
    if any(target.exists() or target.is_symlink() for target in targets):
        raise ValueError('generated-Go-standard-log-output-collision')
    transformations = []
    for target, data in targets.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        transformations.append({'name': 'go-standard-log/' + target.relative_to(module).as_posix(),
            'upstreamDigest': digest(raw) if target.name == 'log.go' else digest(b''),
            'adaptedDigest': digest(data), 'profile': runtime_profile})
    return True, transformations
