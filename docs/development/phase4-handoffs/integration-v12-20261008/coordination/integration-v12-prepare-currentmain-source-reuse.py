from pathlib import Path
import hashlib
import json

coord=Path(__file__).resolve().parent
source=(coord/'portable-v2-reconstructed-native-controller-20261007-v93.py').read_text()
old="    source = base / ('source-' + head[:16])"
assert source.count(old)==1
new="""    prior = base / 'jobs' / 'portable-v2-pr800-dotnet-source-20261008-v213'
    original_receipt = (prior / 'receipt.json').read_bytes()
    assert hashlib.sha256(original_receipt).hexdigest() == '5884b57ca00a77644dd68fe016c2ca26713ddaa2a946f8e77d102ffb338f8f91'
    previous = json.loads(original_receipt)
    assert previous['head'] == 'a94e696f13a1d22a37c962d7b577ea7535a54f85'
    assert previous['passed'] and previous['sourceClean'] and previous['sourceHeadUnchanged'] and previous['originalProcessReaped']
    assert len(previous['steps']) == 7
    for original in previous['steps']:
        raw = (prior / original['log']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == original['sha256'] and len(raw) == original['bytes']
    source = base / 'source-6ab38845e5a266f3'
    assert source.resolve().parent == base.resolve() and not source.is_symlink()
    assert call(['git','rev-parse','HEAD'], source) == previous['head']
    assert not call(['git','status','--porcelain'], source)
"""
source=source.replace(old,new)
path=coord/'integration-v12-currentmain-source-reuse-controller-v7.py'
path.write_text(source,encoding='utf8')
print(json.dumps({'controllerSha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                  'explicitPortableSourceOwnershipReleased':True,'noNewClone':True,
                  'originalReceiptAndAllSevenLogsAuthenticated':True}))
