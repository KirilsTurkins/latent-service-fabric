"""Exact successful wait-for observer native producer; no guest qualification."""
from pathlib import Path
import sys
if __package__ in {None,''}:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.sdk_native_products_reader import FrozenNativeProducts

SOURCE='f9192fb5785ca7bed8b33dbb869b3d775b72ab4b'
RUN=39458247294
JOB=118750640204
ARTIFACT={'id': 12282362053, 'size_in_bytes': 66108086, 'digest': 'sha256:d3942fea19d78c27aac37811fc7f9be32cc26fc76b95a92f98498c3d44162945'}
RECEIPTS={'native-products.json': {'sha256': 'sha256:05254405868cb99025cd1f59a0ae13b406fb201371aa1c7c4a6938ee34a1f719', 'bytes': 21390}, 'source-inputs.json': {'sha256': 'sha256:aeba42c6b06725317f75726e8f60bdc4da1f6d6120c121fd5ee8039f2f28a8ca', 'bytes': 18937}}
STAGES=('rust-version', 'normal-host-build', 'closed-http-refusal-controls', 'neutral-resource-signing-controls', 'positive-timer-observer-controls', 'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls', 'independent-http-configuration-controls', 'independent-http-dispatch-controls', 'independent-http-secret-controls', 'phase-operational-metadata-controls', 'phase-operational-binding-controls')

READER=FrozenNativeProducts(source=SOURCE,run=RUN,job=JOB,artifact=ARTIFACT,receipts=RECEIPTS,
    branch='fix/runtime-wait-positive-observation-20261020',stages=STAGES)
prepare=READER.prepare
verify_prepared=READER.verify_prepared
native_products=READER.native_products

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    prepare(parser.parse_args().output)
