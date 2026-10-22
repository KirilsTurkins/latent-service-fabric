"""Immutable reviewed f535 v7 native cohort; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.host_codec_linear_memory_native_products_reader import FrozenHostCodecLinearMemoryProducts

SOURCE = 'f5351a9331ed954c49ae83f2f4004e0f96d25d0e'
RUN = 39723924277
JOB = 119643418717
ARTIFACT = {'id': 12402318143, 'size_in_bytes': 70406286,
    'digest': 'sha256:832b109a4e41a2b02cbcc5e6c49114f3cd32aa959083b53c8f2caa6f5c3276cc'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:6a7f8d4d53244c51e985211ce9decdc38a25dd2eb50b1676a247743d8d43057d', 'bytes': 85615},
    'source-inputs.json': {'sha256': 'sha256:d92f6ecabd7db2d22042d3502592ba54c490b114fde6e5cb77d0812a568102ce', 'bytes': 24573},
}
READER = FrozenHostCodecLinearMemoryProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/linear-memory-notifications-20261022')
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
