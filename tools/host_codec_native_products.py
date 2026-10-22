"""Immutable 7b normal host-codec cohort; signed C qualification is separate."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.host_codec_native_products_reader import FrozenHostCodecProducts

SOURCE = '7b6365ee39dea9770591a931b96711965f8a1aaf'
RUN = 39685022895
JOB = 119516764302
ARTIFACT = {'id': 12386352515, 'size_in_bytes': 70254520,
    'digest': 'sha256:b7d9dc739e310e759494c83d8cebf07996b53d99f3f7be06db5145ae663ccaff'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:23cf17c9b55fb7bf5b3e26bee996b0c03e07c0349ded357f1b47a52cc3c418bc', 'bytes': 60551},
    'source-inputs.json': {'sha256': 'sha256:8db715c73cbfe525965cdb99269a32756d5583897c89f90d7d450b50ab78409a', 'bytes': 24572},
}
READER = FrozenHostCodecProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/host-codec-memory-736-20261021')
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
