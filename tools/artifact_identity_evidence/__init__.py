"""Offline verification of bounded artifact identity comparisons."""

def validate_suite(path):
    from .suite import validate_suite as replay
    return replay(path)
