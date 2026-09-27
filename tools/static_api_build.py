"""Compile the maintained API through the shipped developer controller and SDK.

This source probe is not authenticated released-artifact or cloud qualification.
This probe does not qualify the HTTP/browser composition.
"""
from __future__ import annotations

from pathlib import Path
import os
import shutil
import sys
import tempfile
import time
import zipfile

from tools.build_process import run_bounded_result
from tools.dev_workflow import build, paths, project, snapshot, state
from tools.dev_workflow.common import DevError, decode, digest, encode, require

ROOT = Path(__file__).resolve().parents[1]


def exercise(payload: Path, packager: Path, supplied: Path, output: Path) -> dict:
    require(sys.platform == 'linux' and os.geteuid() != 0 and not output.exists(),
            'unprivileged-linux-and-new-static-api-build-output-required')
    output.mkdir(mode=0o700)
    work = Path(tempfile.mkdtemp(prefix='lsf-static-api-')).resolve()
    began = time.monotonic()
    report = {'schemaVersion': 'latent.static-api.build.v1', 'passed': False,
              'publisherAuthenticated': False, 'cleanHost': False, 'browserQualified': False,
              'cleanup': 'unconfirmed'}
    try:
        index = decode(paths.read(payload, 'templates.json'))['templates']['greeting']
        template = payload / index['path']
        original = work / 'greeting'
        project.scaffold(template, original, decode(paths.read(template, 'template.json')), index['identity'])
        # The helper uses the same captured Node binary as the actual compiler.
        # Extract this one bounded entry; never execute an ambient npm install.
        with zipfile.ZipFile(payload / 'sdk/managed.zip') as archive:
            entry = archive.getinfo('node/bin/node')
            require(0 < entry.file_size <= 128 * 1024 * 1024, 'static-api-node-binary-bound')
            node = work / 'node'
            paths.write_new(node, archive.read(entry))
            node.chmod(0o700)
        environment = {'PATH': str(work), 'HOME': str(work), 'LANG': 'C', 'LC_ALL': 'C'}
        result = run_bounded_result([str(node), str(ROOT / 'examples/static-api/prepare-project.mjs'),
                              str(original), str(work / 'api')], cwd=ROOT,
                             env=environment, timeout_seconds=30, max_output_bytes=65536)
        paths.write_new(output / 'prepare.log', result.stdout + result.stderr)
        require(result.returncode == 0, 'static-api-source-preparation-failed')
        result = run_bounded_result([str(node), '--test', str(ROOT / 'examples/static-api/status.test.mjs')],
                             cwd=ROOT, env=environment, timeout_seconds=30, max_output_bytes=65536)
        paths.write_new(output / 'unit.log', result.stdout + result.stderr)
        require(result.returncode == 0, 'static-api-public-response-tests-failed')
        author = work / 'api'
        descriptor, _ = project.load(author)
        record, content = snapshot.observe(author, descriptor['inputRoots'], tuple(descriptor['exclude']))
        root = work / 'test-static-api'
        root.mkdir(mode=0o700)
        captured = root / 'source'
        snapshot.materialize(captured, record, content)
        paths.write_new(captured / 'snapshot.json', encode(record))
        trusted = project.trust_identity(descriptor)
        state.atomic(root, 'project.json', {'descriptor': descriptor, 'trust': trusted,
                     'source': str(captured), 'snapshot': record['identity']})
        compiled = build.execute(root, captured, descriptor, payload, trusted=trusted, cli=packager)
        report.update(build=compiled, template=index['identity'], source=record['identity'],
                      nodeBinary=digest(node.read_bytes()), outsideCheckout=True)
        source = root / 'builds' / compiled['attempt'] / 'source'
        shutil.copytree(source / 'output', output / 'build')
        from tools.dev_node_application_probe import run
        report['node'] = run(root, supplied, payload, descriptor, output / 'node')
        require(report['node']['passed'], 'static-api-signed-node-scenarios-failed')
        require(report['node']['cleanup'] == 'owned-node-and-client-processes-reaped',
                'static-api-owned-cleanup-required')
        report.update(passed=True, cleanup='owned-node-and-build-processes-reaped')
    except BaseException as error:
        report['failure'] = error.code if isinstance(error, DevError) else type(error).__name__
        raise
    finally:
        if report['passed']:
            require(work.parent == Path(tempfile.gettempdir()).resolve()
                    and work.name.startswith('lsf-static-api-'), 'static-api-cleanup-owner')
            try:
                shutil.rmtree(work)
            except OSError:
                report.update(passed=False, cleanup='filesystem-cleanup-incomplete')
        if not report['passed']:
            report['retainedPrivateWorkspace'] = str(work)
        report['seconds'] = round(time.monotonic() - began, 3)
        state.atomic(output, 'receipt.json', report)
    return report
