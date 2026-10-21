"""Closed formatting-only source comparison; frozen products remain historical."""
import hashlib
import json

from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, read_file

REVIEW = 'docs/testing/evidence/c-thread-native-rustfmt-2026-10-21.json'
REVIEW_DIGEST = '73982acc618c60f3ebe17c482285e4fbb0c4f97048cf19b70e82609fb99603c2'


def compatibility(compiled, current):
    if current == compiled:
        return {'compiledNativeSource': compiled, 'consumerNativeSource': current,
                'compiledSourceByteExact': True, 'reviewedFormatting': []}
    payload = read_file(ROOT / REVIEW, 32768)
    require(hashlib.sha256(payload).hexdigest() == REVIEW_DIGEST,
            'c-thread-native-format-review-identity')
    reviewed = json.loads(payload)
    require(compiled == reviewed['compiledNativeSource']
            and current == reviewed['formattedConsumerSource'],
            'c-thread-current-native-source-must-match-producer-or-exact-reviewed-formatting')
    # The two complete 3,324-file aggregate identities admit only this closed
    # formatter output. No suffix, caller-provided path or AST allowance exists.
    return {'compiledNativeSource': compiled, 'consumerNativeSource': current,
            'compiledSourceByteExact': False, 'reviewedFormatting': reviewed['files'],
            'formatter': reviewed['formatter'], 'reviewDigest': 'sha256:' + REVIEW_DIGEST,
            'otherNativeFilesByteExact': reviewed['otherNativeFilesByteExact']}
