"""Open the maintained static/API example using an existing built dev workspace."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.dev_workflow import build, state, tool_install
from tools.dev_workflow.common import require
from tools.dev_workflow.helper import installation, root_directory
from tools.build_process import run_bounded_result
from tools.static_api.qualify import run


def main(args):
    require(args.disposable_test_keys and sys.platform == 'linux' and os.geteuid() != 0,
            'explicit-disposable-example-on-unprivileged-linux-required')
    require(re.fullmatch(r'test-[a-z0-9][a-z0-9-]{0,47}', args.workspace) is not None,
            'select-a-disposable-test-workspace')
    workspace = root_directory() / args.workspace
    saved = state.load(workspace, 'project.json')
    require(saved['descriptor']['language'] == 'typescript' and saved['descriptor']['service'] == 'examples/status-api',
            'build-the-maintained-status-api-project-first')
    source, _receipt = build.accepted(workspace, saved)
    tools = Path(tool_install.selected_root(workspace, saved['descriptor']))
    _layout, runtime = installation(workspace)
    root = Path(tempfile.mkdtemp(prefix='lsf-static-api-demo-'))
    try:
        work = root / 'composition'
        observed = run_bounded_result(['node', str(ROOT / 'tools/static_api/prepare.mjs'), str(runtime / 'bin/latent'),
            str(tools / 'sdk/bin/capsule-test-signer'), str(source / 'output'), str(work)],
            cwd=ROOT, env={'PATH': os.environ['PATH'], 'HOME': str(root), 'LANG': 'C.UTF-8'},
            timeout_seconds=120, max_output_bytes=65536)
        require(observed.returncode == 0, 'static-api-example-input-preparation-failed')
        args.work, args.bin = work, runtime / 'bin'
        args.browser_tools = args.chrome = None
        args.serve_seconds = args.seconds
        run(args)
    finally:
        require(root.parent == Path(tempfile.gettempdir()).resolve() and root.name.startswith('lsf-static-api-demo-'),
                'static-api-demo-cleanup-owner')
        shutil.rmtree(root)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--disposable-test-keys', action='store_true', required=True)
    parser.add_argument('--seconds', type=int, choices=range(1, 601), metavar='1..600', default=600)
    main(parser.parse_args())
