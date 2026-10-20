"""Run only compiler-refusal cases with authenticated historical public tools."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_typescript_scratch_refusals import CASES, qualify
from tools.replay_typescript_standard_entropy import historical
from tools.rust_capsule_project import write_json


def run(acquired, tools, output):
    products, _, original = historical(acquired)
    result = qualify(output, tools, products['examples/capsule_contracts'], products['examples/package'])
    require(result['status'] == 'passed' and {row['case'] for row in result['cases']} == set(CASES)
            and len(result['cases']) == len(CASES)
            and all(row['observation']['status'] == 'refused'
                    and row['observation']['runtimeFilesystemExecutionClaimed'] is False for row in result['cases']),
            'scratch-typescript-complete-refusal-packet-required')
    require(historical(acquired)[2] == original, 'scratch-typescript-historical-products-changed')
    record = {'schemaVersion': 'latent.typescript.scratch-refusal-inputs.v1', 'status': 'passed',
        'historicalProducts': original, 'currentQualification': file_identity(output/'qualification.json'),
        'usedNativeProducts': ['examples/capsule_contracts', 'examples/package'],
        'newNativeBuild': False, 'nodeInvoked': False, 'historicalNormalReceiptRewritten': False,
        'runtimeFilesystemExecutionClaimed': False, 'fullTicketQualification': False}
    write_json(output/'historical-inputs.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('acquired', 'tools', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    run(args.acquired, args.tools, args.output)
