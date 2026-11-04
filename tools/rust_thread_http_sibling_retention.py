"""Admit a finite public diagnostic artifact without retaining build caches."""
from pathlib import Path
import os
import stat
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow.common import require
from tools.rust_capsule_project import checked_path, digest, fresh, read_file, write_json

MAX_FILES = 1024
MAX_ENTRIES = 4096
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
ROOTS = ('rust-http-thread-owned', 'rust-http-thread-http',
         'rust-http-thread-contracts', 'rust-http-thread-combined')


def allowed(name):
    parts = name.split('/')
    if len(parts) < 2 or parts[0] not in ROOTS:
        return False
    root, rest = parts[0], parts[1:]
    leaf = rest[-1]
    if root == 'rust-http-thread-owned':
        return (len(rest) == 1 and leaf.endswith('.json')
                or rest == ['tool', 'rust-context']
                or rest[0] == 'owned-sysroot'
                or len(rest) >= 3 and rest[:2] == ['tool-build', 'logs'] and leaf.endswith('.txt'))
    if root == 'rust-http-thread-http':
        return (len(rest) == 1 and leaf.endswith(('.json', '.wasm'))
                or rest == ['component-composer', 'wac']
                or len(rest) >= 2 and rest[0] == 'logs' and leaf.endswith('.txt'))
    if root == 'rust-http-thread-contracts':
        return (len(rest) == 1 and (leaf.endswith(('.json', '.jsonl')) or leaf == 'capsule_contracts')
                or len(rest) >= 2 and rest[0] == 'logs' and leaf.endswith('.txt'))
    return (len(rest) == 1 and leaf.endswith(('.json', '.wasm', '.rlib', '.tar.gz'))
            or len(rest) >= 2 and rest[0] in ('derived', 'http-thread-contracts', 'logs'))


def collect(root, output):
    root = checked_path(Path(root))
    require(root.is_dir(), 'rust-http-thread-retention-root')
    output = fresh(Path(output))
    rows, entries, total = [], 0, 0
    try:
        for name in ROOTS:
            directory = root / name
            if not directory.exists():
                continue
            require(not directory.is_symlink() and directory.is_dir(), 'rust-http-thread-retention-directory')
            pending = [directory]
            while pending:
                parent = pending.pop()
                for path in sorted(parent.iterdir()):
                    entries += 1
                    require(entries <= MAX_ENTRIES and not path.is_symlink(),
                            'rust-http-thread-retention-entry-bound')
                    mode = path.lstat().st_mode
                    if stat.S_ISDIR(mode):
                        # The contracts Cargo target is always excluded as cache.
                        if path.relative_to(root).as_posix() != 'rust-http-thread-contracts/target':
                            pending.append(path)
                        continue
                    require(stat.S_ISREG(mode), 'rust-http-thread-retention-regular-file')
                    relative = path.relative_to(root).as_posix()
                    if not allowed(relative):
                        continue
                    checked_path(path)
                    size = path.stat().st_size
                    total += size
                    require(size <= MAX_FILE and total <= MAX_TOTAL and len(rows) < MAX_FILES,
                            'rust-http-thread-retention-payload-bound')
                    rows.append((relative, path, size))
        identities = []
        for name, path, size in sorted(rows):
            data = read_file(path, MAX_FILE)
            require(len(data) == size, 'rust-http-thread-retention-source-mutated')
            destination = output / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(data)
            require(read_file(destination, MAX_FILE) == data, 'rust-http-thread-retention-copy-mutated')
            identities.append({'path': name, 'bytes': size, 'sha256': digest(data)})
        result = {'schemaVersion': 'latent.rust.http-thread.public-artifact.v1',
                  'status': 'retained', 'files': identities, 'bytes': total,
                  'buildCachesIncluded': False, 'credentialInputsSelected': False,
                  'hostOrGuestQualified': False}
        write_json(output / 'retention.json', result)
        return result
    except Exception as error:
        write_json(output / 'retention-FAILED.json', {'status': 'refused',
            'errorType': type(error).__name__, 'reason': str(error),
            'hostOrGuestQualified': False})
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    collect(args.root, args.output)
