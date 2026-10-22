"""Ordinary default ThreadPools in a normal captured Rust application.

This is source for a compiler diagnostic first. No source/native reference
control is credited as actual guest progress or runtime qualification.
"""
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import cargo_native_authoring as author, rust_application_dependencies as native
from tools import rust_dependency_authoring as review, rust_standard_logging_inputs as standard
from tools import rust_standard_thread_capture as port, rust_standard_thread_profile as profile
from tools.application_dependencies import LOCK
from tools.dev_workflow.common import require
from tools.rust_capsule_project import create, digest, inventory, read_file, snapshot, write_json

RECIPE = ('tools/rust_owned_thread_fixture.py', 'tools/rust_capsule_project.py',
          'tools/cargo_native_authoring.py', 'tools/rust_dependency_authoring.py',
          'tools/rust_application_dependencies.py', *port.RECIPE)
PUBLIC = 'examples:greeting/api@1.0.0#greet'
POST = 'cabi_post_' + PUBLIC
BODY = b'''    if name == "pools" {
        let first = futures_executor::ThreadPool::new().map_err(|e| e.to_string())?;
        let second = futures_executor::ThreadPool::new().map_err(|e| e.to_string())?;
        let (send, receive) = std::sync::mpsc::channel::<u32>();
        let (result_send, result_receive) = std::sync::mpsc::channel::<u32>();
        first.spawn_ok(async move {
            let value = receive.recv().unwrap();
            result_send.send(value + 1).unwrap();
        });
        second.spawn_ok(async move { send.send(41).unwrap(); });
        let answer = result_receive.recv().map_err(|e| e.to_string())?;
        drop(first);
        drop(second);
        return Ok(format!("ordinary-default-pools:{answer}"));
    }
'''


def prepare(destination: Path, cargo: Path):
    app = create(destination, 'greeting', name='ordinary-thread-inputs', runtime_profile=standard.THREAD)
    before = snapshot(app)
    marker = b'    let name = name.trim();'
    require(before['src/lib.rs'].count(marker) == 1, 'rust-thread-input-template-shape')
    (app / 'src/lib.rs').write_bytes(before['src/lib.rs'].replace(marker, BODY + marker, 1))
    author.author(app, 'add', identity=profile.EXECUTOR, version=profile.EXECUTOR_VERSION,
                  target='cfg(target_arch = "wasm32")', features=['thread-pool'], cargo=cargo)
    require(all(read_file(app / name) == value for name, value in before.items()
                if name not in {'src/lib.rs', 'Cargo.toml', 'Cargo.lock'}),
            'rust-thread-input-original-sdk-limits-and-world')
    candidate = app.parent / 'cargo-candidate.json'
    lock = native.resolve(app, candidate, cargo=cargo)
    selected = [row for row in lock['artifacts']
                if row['metadata'].get('package') == profile.EXECUTOR]
    require(len(selected) == 1
            and selected[0]['metadata'].get('version') == profile.EXECUTOR_VERSION
            and selected[0]['metadata'].get('vendorChecksum', {}).get('package')
                == profile.EXECUTOR_ARCHIVE_SHA256,
            'rust-thread-input-authentic-runtime-package')
    raw = read_file(candidate, 8 * 1024 * 1024)
    review.review(app, candidate, digest(raw))
    require(read_file(app / LOCK, 8 * 1024 * 1024) == raw
            and review.status(app)['status'] == 'verified', 'rust-thread-input-reviewed-capture')
    return app, {'sourceDigest': digest(inventory(snapshot(app))),
                 'runtimeArtifact': selected[0]['id'], 'candidateDigest': digest(raw),
                 'publicExport': PUBLIC, 'postReturnExport': POST,
                 'actualGuestExecuted': False, 'ordinaryThreadPoolQualified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application', type=Path, required=True)
    parser.add_argument('--cargo', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    _application, receipt = prepare(args.application, args.cargo)
    write_json(args.report, receipt)
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
