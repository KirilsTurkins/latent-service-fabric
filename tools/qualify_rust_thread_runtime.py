"""One finite signed original ThreadPool programme using two immutable origins."""
from pathlib import Path
import argparse
import json
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import inventory
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json
from tools import rust_thread_native_products as native_source
from tools.rust_thread_runtime_package import prepare
from tools.rust_thread_runtime_node import run


def qualify(prepared: Path, compiler_materials: Path, output: Path) -> dict:
    output = fresh(output)
    record = {'schemaVersion': 'latent.rust.thread-runtime.programme.v1', 'status': 'incomplete',
              'full743Qualified': False, 'checkpointQualified': False}
    stage, primary = 'exact-native-source-and-product-recheck', False
    try:
        native = native_source.verify_prepared(prepared)
        write_json(output / 'native-origin.json', native)
        products = native_source.native_products(prepared)
        commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                            deadline_seconds=600, command_seconds=60)
        stage = 'original-compiler-pair-and-explicit-policy-package'
        projection = prepare(compiler_materials, products, output / 'package', commands)
        write_json(output / 'compiler-projection.json', projection)
        stage = 'five-normal-signed-default-threadpool-calls'
        result = run(output / 'package', products, output / 'node')
        record.update(status='passed', package=projection, signedProgramme=result,
                      nativeCompiledSource=native['compiledSource'], commands=commands.records,
                      actualDefaultThreadPoolProgress=True)
        stage = 'bounded-public-evidence-retention'
        final = json.dumps(record, indent=2, ensure_ascii=False).encode() + b'\n'
        require(len(final) < 128 * 1024 * 1024, 'rust-thread-final-receipt-byte-bound')
        # Reserve the exact bytes and one directory entry for this receipt BEFORE
        # publishing passed. A retention refusal reaches FAILED, never qualified.
        inventory(output, maximum_files=255, maximum_bytes=128 * 1024 * 1024 - len(final))
        with (output / 'qualified.json').open('xb') as destination:
            destination.write(final)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', stage=stage, qualification=False)
        raise
    finally:
        if primary:
            try:
                write_json(output / 'FAILED.json', record)
            except BaseException:
                pass
        # Both passing and failed payloads must obey the same declared retention
        # budget. Refusal leaves actual bytes in place for the always-upload step.
        try:
            inventory(output, maximum_files=256, maximum_bytes=128 * 1024 * 1024)
        except BaseException:
            if not primary:
                raise
            try:
                write_json(output / 'retention-refused.json', {
                    'status': 'refused', 'withinRetentionBudgetClaimed': False,
                    'originalFailurePreserved': True})
            except BaseException:
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--compiler-materials', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.prepared, args.compiler_materials, args.output)
    print(json.dumps({'status': result['status'], 'full743Qualified': False}))
