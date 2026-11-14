#!/usr/bin/env python3
"""Repair the independently reproduced Java cache-pin historical inverse."""
import hashlib, os, pathlib, subprocess, sys
root=pathlib.Path(os.environ['RUNNER_TEMP'])/'ts-followup-parent'
out=pathlib.Path(os.environ['RUNNER_TEMP'])/'ts-followup-evidence'
p=root/'tools/tests/test_java_scratch_wiring.py'
raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()=='44b7df29e339dd3052e2a1e7795413c965a4ec3cd4191052d8477a5c409b08de'
s=raw.decode();before="matches[0]['uses'] != prefix + 'ec176dce9471270c8a9be1289040c0a8fd6aa708'";assert s.count(before)==1
s=s.replace(before,"matches[0]['uses'] != prefix + '2571c499f8aa6b4db4b4b5632bea291d6be58dc8'")
before="for suffix in ('2ff27e45011b8bcf31ef566ae84c1c923c8aea69', '0' * 40):";assert s.count(before)==1
s=s.replace(before,"for suffix in ('ec176dce9471270c8a9be1289040c0a8fd6aa708',\n                           '2ff27e45011b8bcf31ef566ae84c1c923c8aea69', '0' * 40):")
p.write_text(s)
p=root/'docs/development/workflow-action-pins.md';s=p.read_text();before='ec176dce9471270c8a9be1289040c0a8fd6aa708';assert s.count(before)==1
p.write_text(s.replace(before,'2571c499f8aa6b4db4b4b5632bea291d6be58dc8'))
with (out/'java-wiring.log').open('wb') as f:
    result=subprocess.run([sys.executable,'-m','unittest','tools.tests.test_java_scratch_wiring','tools.tests.test_java_resource_conformance','tools.tests.test_sdk_scratch_qualification','-v'],cwd=root,stdout=f,stderr=subprocess.STDOUT,timeout=180)
print('Java workflow and resource controls exit',result.returncode)
if result.returncode:print((out/'java-wiring.log').read_text()[-16000:])
assert result.returncode==0
