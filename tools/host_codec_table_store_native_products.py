"""Immutable de0 v2 native cohort; retained C observations remain unqualified."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.host_codec_table_store_native_products_reader import FrozenHostCodecTableStoreProducts

SOURCE = 'de0aed36f0b135d6d88fb536484e60aee978f218'
RUN = 39702795582
JOB = 119575748362
ARTIFACT = {'id': 12393673565, 'size_in_bytes': 70328915,
    'digest': 'sha256:db0bf86b985fc53a1c146383af58b4fc5074b7c1f4c3dda019fb89c4e3edd964'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:5a0160810ddcc520771bcc2feede1f9e2e82e1ec88260192aef20f4b9356abe3', 'bytes': 68567},
    'source-inputs.json': {'sha256': 'sha256:29151dda7d155cd1cc0db1de9820b179f2a94f248c24791b6f0ab0f91079c6af', 'bytes': 24573},
}
READER = FrozenHostCodecTableStoreProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/typescript-table-memory-20261022')
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
