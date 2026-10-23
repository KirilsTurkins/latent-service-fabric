"""Exact CLI diagnostic-type corrections before native qualification."""
import runpy
import subprocess

candidate = runpy.run_path('.github/audit-lifecycle-candidate.py')
candidate['prepare']()
replace = candidate['replace']
projection = 'apps/latent/src/audit_maintenance/projection.rs'
tests = 'apps/latent/src/audit_maintenance/tests.rs'
replace(projection, 'AuditPageStop::PageLimit => "page-limit",', 'AuditPageStop::RecordLimit => "record-limit",')
replace(tests, 'request_digest: digest,', 'request_digest: digest.clone(),')
replace(tests, 'preview_receipt_digest: Some(digest),', 'preview_receipt_digest: Some(digest.clone()),')
subprocess.run(['rustup', 'run', '1.97.1', 'rustfmt', '--edition', '2021', '--config', 'skip_children=true', projection, tests], check=True)
