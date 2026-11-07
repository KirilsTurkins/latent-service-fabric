"""Bind the final selected graph to the successful source-matched compiler job."""
from pathlib import Path
import os, subprocess, json, hashlib, zipfile
root = Path.cwd()
temp = Path(os.environ['RUNNER_TEMP'])
helpers = temp / 'pr1657-final-helpers'

s = (helpers / 'pr1657_refresh_catalogue.py').read_text()
replacements = {
    '67901817': '67919611',
    '8c8c44d5733e5bdb82e5b9b67eedd1737c09edbc16d104dc55e3cd83334b366f': 'ba5b77a22012f22f503839470858383c6847783b7b04abd3614bf680d8c92210',
    '== 203': '== 209', "'archiveMembers': 203": "'archiveMembers': 209, 'archivePrefix': 'rust-http-thread-public/rust-http-thread-combined/'",
    "archive.getinfo('rust-http-thread-combined/'": "archive.getinfo('rust-http-thread-public/rust-http-thread-combined/'",
    '27164664b222bc52c88371a2225d147b3f8c020e': '1d81c35ca6b206bafba113b6214de09bc6781bdb',
    'b45308aa4be494c749244d017d5cb43afb64c61f': '1e5d2f29ba8689a526049314a5e1322e5c271a67',
    'b8a028e8778198e27b343297e598542ad9b0c046': '0c2a0902d46da3bde7453259a88161257b59e042',
    'e26658d86f549fc9a29d88d703842acffaee04ed6c986f6d45882d972f1413ee': '25ecfa4024c125f3c8829216c8c5211097d9f27a8ae86e8385ecfb6526ebfcca',
    '1303953': '1306998',
    '93afb8712d2d3d624f470767f8944e32f29f6a50e5c59bba86cf2439f7946f28': '71e0d0bd5cd4be0578eff4ad0ee02dc0d40f3146bc5e373193f3cbc9b8d3fcef',
    '1652323': '1654366',
    '7e4952870f2ffe337978c0db1c9127e3d891130f7dd26659e928c6020ef829b6': 'ab7c8e29be5745ff29fa5788ab13f3cc2bdde87da5033e41e9f804dcb3d83032',
    '.github/workflows/pr1657-fresh-source.yml': '.github/workflows/pr1657-retirement-compiler.yml',
    'diag/pr1657-fresh-source-20261107': 'diag/pr1657-retirement-compiler-20261107',
    '42364782237': '42369110799', '128380436039': '128393351609', '13570829656': '13573560784',
    "'workflowConclusion': 'failure'": "'workflowConclusion': 'success'",
    "'source job used a nonexistent ci_contracts.py validate subcommand after all 39 controls passed; maintained validation passed separately'": 'None',
    'pr1657-fresh-compiler-27164664': 'pr1657-retirement-compiler-0c2a0902d46da3bde7453259a88161257b59e042',
}
for old, new in replacements.items():
    assert old in s, old
    s = s.replace(old, new)
exec(compile(s, 'reviewed-final-catalogue', 'exec'), {})
exec(compile((helpers / 'pr1657_refresh_package.py').read_text(), 'reviewed-package-controller', 'exec'), {})
s = (helpers / 'pr1657_refresh_controls.py').read_text()
s = s.replace("self.assertEqual(package.ORIGIN['workflowConclusion'], 'failure')", "self.assertEqual(package.ORIGIN['workflowConclusion'], 'success')")
s = s.replace("('compilerRunConclusion', 'success')", "('compilerRunConclusion', 'failure')")
exec(compile(s, 'reviewed-producer-controls', 'exec'), {})
p = root / 'tools/rust_combined_http_materials.py'
s = p.read_text().replace("PREFIX = 'rust-http-thread-combined/'", "PREFIX = ORIGIN['archivePrefix']")
s = s.replace('The selected compiler job passed. Its ancillary source-check job failed; the\nworkflow result is retained separately and is never relabelled as a pass.', 'The selected compiler job and workflow passed. Historical failed compiler and\nsigned observations retain their own identities and are not relabelled.')
p.write_text(s)
p = root / 'tools/rust_thread_http_combined_package.py'
s = p.read_text().replace('The successful compiler job is distinct from its failed ancillary source-check\njob and from the historical failed compiler event.', 'The successful compiler job and workflow are distinct from the historical\nfailed compiler and signed execution events.')
p.write_text(s)
p = root / 'crates/latent-component-threading/src/rust_catalogue/combined-corrected-v1/origin.json'
value = json.loads(p.read_bytes())
value['previousCorrectedObservation'] = {'sourceCommit': '27164664b222bc52c88371a2225d147b3f8c020e', 'compilerRun': 42364782237, 'compilerJobConclusion': 'success', 'compilerWorkflowConclusion': 'failure', 'signedRun': 42366341977, 'signedConclusion': 'failure', 'outboundRequests': 3, 'terminalState': 'deadline_exceeded', 'reclassified': False}
p.write_text(json.dumps(value, indent=2) + '\n')
archive = temp / 'sequential.zip'
assert archive.stat().st_size == 38931 and hashlib.sha256(archive.read_bytes()).hexdigest() == 'c7a66a3d4d9083b08a307bcb25424ec0cc96cb8cc823617b7c33c6d283595b05'
with zipfile.ZipFile(archive) as z:
    assert len(z.infolist()) == 5 and z.testzip() is None
    assert z.read('rust_http_pump_probe.rs') == (root / 'tools/toolchain-smoke/examples/rust_http_pump_probe.rs').read_bytes()
    (root / 'tools/toolchain-smoke/examples/rust_http_pump_control.rs').write_bytes(z.read('rust_http_pump_control.rs'))
print('Corrected compiler source, original limits, graph identities and successful sequential probe sources authenticated.')
