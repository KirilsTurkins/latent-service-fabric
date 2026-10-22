"""Immutable reviewed cb8c v9 native cohort; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.host_codec_owned_reply_native_products_reader import FrozenHostCodecOwnedReplyProducts

SOURCE = 'cb8ceefc5f6343301871dbde1d8a853d3581cc30'
RUN = 39742557852
JOB = 119703099390
ARTIFACT = {'id': 12410348071, 'size_in_bytes': 70449703,
    'digest': 'sha256:a4bb2b98e8b338924b5462f338902ae65915625692969b60698fabcd8834a03a'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:994e2c150e98491b1d263a67f049822c9439690f42d072703e84f080e6842a27', 'bytes': 94912},
    'source-inputs.json': {'sha256': 'sha256:fa47517b986e14009f52be786fef0b3e3e288fd80596f3986de56f0afe1c7d93', 'bytes': 24574},
}
READER = FrozenHostCodecOwnedReplyProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/owned-context-replies-memory-20261022')
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
