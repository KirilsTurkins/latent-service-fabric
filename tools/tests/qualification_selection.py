"""Verify and invert only the reviewed tooling gate for historical workflow tests."""
import copy
import json
from pathlib import Path

PREFIX = "${{ needs.tooling-selection.outputs.reason != 'isolated-tooling:documentation-validator-tests' && ("
SUFFIX = ") }}"


def unwrap_tooling_gate(test, job):
    test.assertEqual(job.pop('needs'), 'tooling-selection')
    expression = job['if']
    test.assertTrue(expression.startswith(PREFIX) and expression.endswith(SUFFIX), expression)
    job['if'] = "${{ " + expression[len(PREFIX):-len(SUFFIX)] + " }}"


def restore_java_pre_tooling_view(test, workflow):
    jobs = workflow['jobs']
    for name in ('compiler-component', 'dependency-ingestion', 'http-public-spi', 'public-fiber-assembly'):
        unwrap_tooling_gate(test, jobs[name])
    selector = jobs.pop('tooling-selection')
    test.assertEqual(selector['outputs']['reason'], '${{ steps.select.outputs.reason }}')
    result = jobs.pop('selection-result')
    test.assertEqual(result['needs'], 'tooling-selection')
    test.assertEqual(result['if'], 'always()')
    # An independently added Java queue qualification remains fully pinned by
    # its current workflow contract; it is outside these older comparisons.
    if 'queue-heap-control' in jobs:
        from tools.ci_lane_inventory import workflow_model
        root = Path(__file__).resolve().parents[2]
        current = workflow_model((root / '.github/workflows/java-guest-feasibility.yml').read_text(encoding='utf-8'))
        actual = copy.deepcopy(current['jobs']['queue-heap-control'])
        for step in actual.get('steps', []):
            if 'uses' in step:
                test.assertIn('@', step['uses'])
                step['uses'] = step['uses'].rsplit('@', 1)[0]
        contract = json.loads((root / 'tools/ci/contracts/workflows/java-guest-feasibility.yml/jobs/queue-heap-control.json').read_text(encoding='utf-8'))
        test.assertEqual(actual, contract['definition'])
        jobs.pop('queue-heap-control')
