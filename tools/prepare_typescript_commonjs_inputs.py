"""Reuse the shared authenticated OWN compiler tuple; never rebuild products."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, write_json
from tools.typescript_guest import borrow_signed_inputs as inputs


def prepare(output):
    inputs.prepare(output)
    output = output.resolve()
    expires, commands = time.monotonic()+120, []
    def git(label, *arguments):
        require(len(commands) < 258 and time.monotonic() < expires, 'commonjs-compiler-input-verification-bound')
        result = run_bounded_result(list(arguments), ROOT, build_environment(output),
            min(20, max(0.001, expires-time.monotonic())), 8*1024**2)
        require(result.returncode == 0 and time.monotonic() < expires, 'commonjs-compiler-input-git-verification')
        commands.append({'label': label, 'returncode': result.returncode,
            'stdout': {'bytes':len(result.stdout),'sha256':digest(result.stdout)},
            'stderr': {'bytes':len(result.stderr),'sha256':digest(result.stderr)}})
        return result.stdout
    checked = inputs.verify(output/'products', git)
    require(time.monotonic() < expires, 'commonjs-compiler-input-final-verification-deadline')
    record = {'schemaVersion':'latent.typescript.commonjs-compiler-inputs.v1',
        'acquisition':file_identity(output/'ACQUIRED.json',4*1024**2), 'checked':checked,
        'selector':file_identity(ROOT/'tools/typescript_guest/borrow_signed_inputs.py'),
        'commands':commands, 'commonjsQualification':'not-run'}
    write_json(output/'NORMAL-CHECKED.json',record)
    require(time.monotonic() < expires, 'commonjs-compiler-input-receipt-deadline')
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.output)))
