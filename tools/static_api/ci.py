"""Qualify the freshly built SDK artifact; retain only public receipts in CI."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.static_api.qualify import run
from tools.build_process import run_bounded_result


def main(args):
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise RuntimeError('static-api-unprivileged-linux-required')
    for name in ('bin', 'signer', 'build', 'browser_tools'):
        setattr(args, name, getattr(args, name).resolve(strict=True))
    directory = Path(tempfile.mkdtemp(prefix='lsf-static-api-composition-'))
    receipt = None
    try:
        work = directory / 'work'
        observed = run_bounded_result(['node', str(ROOT / 'tools/static_api/prepare.mjs'), str(args.bin / 'latent'),
            str(args.signer), str(args.build), str(work)], cwd=ROOT, env=dict(os.environ),
            timeout_seconds=120, max_output_bytes=65536)
        if observed.returncode:
            raise RuntimeError('static-api-ci-input-preparation-failed')
        browser = run_bounded_result(['node', '-p', 'require("playwright-core").chromium.executablePath()'],
            cwd=args.browser_tools, env=dict(os.environ), timeout_seconds=10, max_output_bytes=8192)
        if browser.returncode or len(browser.stdout) > 4096 or browser.stderr:
            raise RuntimeError('static-api-browser-path-bound')
        args.chrome = Path(browser.stdout.decode('utf-8').strip()).resolve(strict=True)
        args.work = work
        receipt = run(args)
        receipt.update(publisherAuthenticated=False, inputAssociation='caller-supplied-build-and-runtime; CI retains their source build receipts')
    finally:
        args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        if (directory / 'work/composition-receipt.json').is_file():
            shutil.copyfile(directory / 'work/composition-receipt.json', args.output / 'composition-receipt.json')
        if receipt is not None:
            (args.output / 'composition-receipt.json').write_text(json.dumps(receipt) + '\n', encoding='utf-8')
        # This fresh private root owns all test keys, credentials and processes.
        # The qualifier has already reaped its node and peer on every path.
        if directory.parent != Path(tempfile.gettempdir()).resolve() or not directory.name.startswith('lsf-static-api-composition-'):
            raise RuntimeError('static-api-cleanup-ownership')
        shutil.rmtree(directory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bin', 'signer', 'build', 'browser-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    main(parser.parse_args())
