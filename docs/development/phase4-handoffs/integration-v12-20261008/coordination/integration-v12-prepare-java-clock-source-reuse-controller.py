from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
assert source.count(old)==1
new="""    prior = base / 'jobs' / 'integration-v12-current-startup-import-final-source-v5'
    previous = json.loads((prior / 'receipt.json').read_text())
    assert previous['head'] == 'dca5d7737ef2ae37cd0c3a92c5c6c0ad40d897e9'
    assert previous['passed'] and previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    assert len(previous['steps']) == 7
    for original in previous['steps']:
        raw = (prior / original['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == original['sha256'] and len(raw) == original['bytes']
    source = base / 'source-dca5d7737ef2ae37'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
"""
source=source.replace(old,new)
path=coord/'integration-v12-java-clock-source-reuse-controller-v6.py'
path.write_text(source,encoding='utf8')
print(json.dumps({'controllerSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
    'onlyOwnedReapedSourceCheckoutReused':True,'allPreviousSourceLogsAuthenticated':True,
    'nativeCheckoutReused':False,'newCandidate':'d6006fe34001b0129d9205d5e83398626920c24b'}))
