"""Build the current contracts helper once for the Rust HTTP/thread diagnostic."""
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import compile_rust_thread_http_sibling as combined
from tools.build_observation import build_environment, file_identity
from tools.dev_workflow.common import require
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, checked_path, fresh, write_json


def run(output: Path, rust_bin: Path, expected_head: str):
    require(sys.platform == 'linux', 'rust-http-thread-contracts-linux-owner')
    output = fresh(output)
    commands = None
    record = {'schemaVersion': 'latent.rust.http-thread.contract-tool.v1',
              'status': 'in-progress', 'head': expected_head, 'stage': 'source',
              'actualGuestExecuted': False, 'hostQualified': False}
    try:
        cargo = checked_path(rust_bin / 'cargo')
        rustc = checked_path(rust_bin / 'rustc')
        identities = {name: file_identity(path, name) for name, path in (('cargo', cargo), ('rustc', rustc))}
        # This also checks HEAD and all recipe preimages before any build.
        source = combined.bind_recipe_to_git(expected_head, {
            'Cargo.toml': (ROOT / 'Cargo.toml').read_bytes(),
            'Cargo.lock': (ROOT / 'Cargo.lock').read_bytes(),
            'crates/latent-packaging/Cargo.toml': (ROOT / 'crates/latent-packaging/Cargo.toml').read_bytes(),
            'crates/latent-packaging/examples/capsule_contracts.rs':
                (ROOT / 'crates/latent-packaging/examples/capsule_contracts.rs').read_bytes(),
            'tools/rust_thread_http_sibling_contracts.py':
                (ROOT / 'tools/rust_thread_http_sibling_contracts.py').read_bytes()})
        target = output / 'target'
        environment = build_environment(output)
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0',
            CARGO_PROFILE_DEV_DEBUG='0', RUSTUP_AUTO_INSTALL='0', RUSTUP_TOOLCHAIN='1.97.1', RUSTC=str(rustc))
        commands = Commands(ROOT, output, environment, deadline_seconds=600, command_seconds=300)
        record['stage'] = 'current-contracts-build'
        raw = commands.run('current-contracts-build', cargo, 'build', '--locked', '--package',
                           'latent-packaging', '--example', 'capsule_contracts', '--message-format=json')
        (output / 'cargo-messages.jsonl').write_bytes(raw)
        selected = []
        for row in combined.cargo_records(raw):
            if row.get('reason') != 'compiler-artifact' or row.get('target', {}).get('name') != 'capsule_contracts':
                continue
            require(Path(row['manifest_path']).resolve() == (ROOT / 'crates/latent-packaging/Cargo.toml').resolve()
                    and Path(row['target']['src_path']).resolve() ==
                        (ROOT / 'crates/latent-packaging/examples/capsule_contracts.rs').resolve()
                    and row['target']['kind'] == ['example'] and row['profile']['test'] is False
                    and row.get('fresh') is False and type(row.get('executable')) is str,
                    'rust-http-thread-current-contracts-artifact')
            executable = checked_path(Path(row['executable']))
            require(executable.parent == (target / 'debug/examples').resolve(),
                    'rust-http-thread-contracts-target')
            selected.append(executable)
        require(len(selected) == 1, 'rust-http-thread-one-current-contracts-tool')
        identity = file_identity(selected[0], 'contracts-tool', 64 * 1024 * 1024)
        copied = output / 'capsule_contracts'
        shutil.copyfile(selected[0], copied); copied.chmod(0o755)
        require(file_identity(copied, 'contracts-tool', 64 * 1024 * 1024) == identity
                and combined.bind_recipe_to_git(expected_head, {
                    row['path']: (ROOT / row['path']).read_bytes() for row in source['files']}) == source
                and {name: file_identity(path, name) for name, path in (('cargo', cargo), ('rustc', rustc))}
                    == identities, 'rust-http-thread-current-contracts-input-mutated')
        record.update(status='passed-current-contracts-tool', stage='complete', source=source,
                      tools=identities, tool=identity, commands=commands.records)
        write_json(output / 'report.json', record)
        return record
    except Exception as error:
        record.update(status='failed', errorType=type(error).__name__, reason=str(error),
                      commands=[] if commands is None else commands.records)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rust-bin', type=Path, required=True)
    parser.add_argument('--expected-head', required=True)
    args = parser.parse_args()
    run(args.output, args.rust_bin, args.expected_head)
