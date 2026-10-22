"""Immutable reviewed 3e417 v4 native cohort; no signed guest qualification."""
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.host_codec_funcrefs_native_products_reader import FrozenHostCodecFuncRefsProducts

SOURCE = '3e4178271b4b7fe75a69c8f0665dbe275b41d7c3'
RUN = 39711228748
JOB = 119602782320
ARTIFACT = {'id': 12397985069, 'size_in_bytes': 70376694,
    'digest': 'sha256:be0ec6bbdb91a7cc38ccc4856588bfa3d0bc45f8a7075b27060ad8f801493bbf'}
RECEIPTS = {
    'native-products.json': {'sha256': 'sha256:f39615a44f8f7873246e6053f7d058427c3f9e513baeb333564c4e66ef4b5502', 'bytes': 75420},
    'source-inputs.json': {'sha256': 'sha256:692bd8a4b2c7ba010f3bcb08f88bd7203f1115ae2beef293a8398741f7fdc402', 'bytes': 24573},
}
READER = FrozenHostCodecFuncRefsProducts(source=SOURCE, run=RUN, job=JOB, artifact=ARTIFACT,
    receipts=RECEIPTS, branch='feat/activation-funcrefs-memory-20261022')
prepare = READER.prepare
verify_prepared = READER.verify_prepared
native_products = READER.native_products

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    prepare(parser.parse_args().output)
