#!/usr/bin/env python3
"""Correct only the missing exact Zig pin inverse in the frozen Rust test."""
import hashlib,json,os,pathlib,subprocess,sys
root=pathlib.Path(os.environ['RUNNER_TEMP'])/'ts-followup-parent'
out=pathlib.Path(os.environ['RUNNER_TEMP'])/'ts-followup-evidence';out.mkdir(exist_ok=True)
p=root/'tools/tests/test_rust_scratch_replay.py';raw=p.read_bytes()
assert hashlib.sha256(raw).hexdigest()=='d75b8f7048e19c255bb331e2fe8a94fc3de71709299f75cc456209558ec113d9'
record=json.loads((root/'.github/security/actions/xml-security-rebuilds.json').read_text())
selected=[row for row in record['actions'] if row['repository']=='KirilsTurkins/lsf-setup-zig']
assert len(selected)==1 and selected[0]['base']=='e064b42fa88ad0859d8b54838b44f672ffd5ea7a' and selected[0]['publishedCommit']=='adb5ed78414674f693e8fe00982f83df9badcdb3'
s=raw.decode();assert s.count('import json\n')==1;s=s.replace('import json\n','import json\nimport re\n')
helper='''def historical_zig_setup(value):
    """Invert only the source-reviewed XML rebuild for this frozen Rust guard."""
    if type(value) not in (str, bytes):
        raise AssertionError('historical-rust-exact-current-zig-required')
    prefix = 'KirilsTurkins/lsf-setup-zig@'
    current = prefix + 'adb5ed78414674f693e8fe00982f83df9badcdb3'
    previous = prefix + 'e064b42fa88ad0859d8b54838b44f672ffd5ea7a'
    terminal = r'(?=$|[\\s\\x22\\x27])'
    if type(value) is bytes:
        prefix, current, previous, terminal = (
            part.encode('ascii') for part in (prefix, current, previous, terminal))
    if value.count(prefix) != len(re.findall(re.escape(current) + terminal, value)):
        raise AssertionError('historical-rust-exact-current-zig-required')
    return value.replace(current, previous)


'''
needle='def historical_checkout(value):\n';assert s.count(needle)==1;s=s.replace(needle,helper+needle)
needle='    value = historical_security_actions(value)\n';assert s.count(needle)==1;s=s.replace(needle,needle+'    value = historical_zig_setup(value)\n')
method='''    def test_zig_history_accepts_only_the_reviewed_complete_revision(self):
        prefix = 'KirilsTurkins/lsf-setup-zig@'
        current = prefix + 'adb5ed78414674f693e8fe00982f83df9badcdb3'
        previous = prefix + 'e064b42fa88ad0859d8b54838b44f672ffd5ea7a'
        for encode in (str, str.encode):
            for suffix in ('', '\\n', '"', "'"):
                self.assertEqual(historical_zig_setup(encode(current + suffix)),
                                 encode(previous + suffix))
            self.assertEqual(historical_zig_setup(encode('no Zig action')), encode('no Zig action'))
            for value in (previous, prefix + '0' * 40, prefix + 'v2.2.1',
                          current + '0', current + '/other', current + '\\n' + previous):
                with self.subTest(value=value, encode=encode), self.assertRaisesRegex(
                        AssertionError, 'historical-rust-exact-current-zig-required'):
                    historical_zig_setup(encode(value))
        for value in (None, {}, 1):
            with self.subTest(value=value), self.assertRaises(AssertionError):
                historical_zig_setup(value)

'''
needle='class RustScratchReplay(unittest.TestCase):\n';assert s.count(needle)==1;s=s.replace(needle,needle+method)
p.write_text(s);assert hashlib.sha256(p.read_bytes()).hexdigest()=='89383fc769a546b46749cf43e7e6c9e71e7f43bae3aad75968a633ddbf97df53'
with (out/'rust-workflow-pins.log').open('wb') as f:
    result=subprocess.run([sys.executable,'-m','unittest','tools.tests.test_rust_scratch_replay','tools.tests.test_sdk_scratch_qualification','tools.tests.test_java_scratch_wiring','-v'],cwd=root,stdout=f,stderr=subprocess.STDOUT,timeout=180)
print('Rust and adjacent immutable workflow controls exit',result.returncode,flush=True)
if result.returncode:print((out/'rust-workflow-pins.log').read_text()[-16000:])
assert result.returncode==0
subprocess.run(['git','add',str(p)],cwd=root,check=True)
subprocess.run(['git','diff','--cached','--check'],cwd=root,check=True)
subprocess.run(['git','commit','-m','fix(ci): preserve Rust workflow history across the reviewed Zig rebuild'],cwd=root,check=True)
