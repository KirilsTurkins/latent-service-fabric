"""Verify and invert only the reviewed tooling gate for historical workflow tests."""
import copy
import json
from pathlib import Path

PREFIX = "${{ needs.tooling-selection.outputs.reason != 'isolated-tooling:documentation-validator-tests' && ("
SUFFIX = ") }}"


def project_dotnet_reset_witness(test, tree):
    """Invert only the independently checked default-false .NET reset witness."""
    import ast
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'run']
    test.assertEqual(len(functions), 1)
    run = functions[0]
    argument, default = run.args.kwonlyargs.pop(), run.args.kw_defaults.pop()
    test.assertEqual(argument.arg, 'dotnet_task_reset_witness')
    test.assertIsInstance(default, ast.Constant)
    test.assertIs(default.value, False)
    guard = run.body.pop(0)
    expected = ast.parse("require(type(dotnet_task_reset_witness) is bool and "
        "(not dotnet_task_reset_witness or dotnet_task_runtime is True), "
        "'authoring-dotnet-reset-witness-selection')").body[0]
    test.assertEqual(ast.dump(guard, include_attributes=False), ast.dump(expected, include_attributes=False))
    calls = [node for node in ast.walk(run) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == 'probe_managed_tasks']
    test.assertEqual(len(calls), 1)
    matches = [item for item in calls[0].keywords if item.arg == 'reset_notification']
    test.assertEqual(len(matches), 1)
    test.assertIsInstance(matches[0].value, ast.Name)
    test.assertEqual(matches[0].value.id, 'dotnet_task_reset_witness')
    calls[0].keywords.remove(matches[0])
    test.assertFalse(any(isinstance(node, ast.Name) and node.id == 'dotnet_task_reset_witness'
                         for node in ast.walk(run)))
    return tree


def unwrap_tooling_gate(test, job):
    test.assertEqual(job.pop('needs'), 'tooling-selection')
    expression = job['if']
    test.assertTrue(expression.startswith(PREFIX) and expression.endswith(SUFFIX), expression)
    job['if'] = "${{ " + expression[len(PREFIX):-len(SUFFIX)] + " }}"


def restore_java_pre_tooling_view(test, workflow):
    # Authenticate and invert the development-push route before comparing a
    # historical pull-request-only workflow; do not relax its path filters.
    events = workflow['on'] if 'on' in workflow else workflow[True]
    test.assertEqual(events.pop('push'), events['pull_request'])
    test.assertEqual(events['pull_request']['branches'], ['development'])
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
