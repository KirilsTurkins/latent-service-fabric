"""Bounded controlled peers for the shared standard HTTP qualification profile.

These are test peers, not a guest transport, executor, grant or qualification
receipt. Language runners retain their real component/provider/ledger evidence.
"""

from .peer import Gate, Peer
from .protocol import FixtureError

__all__ = ["FixtureError", "Gate", "Peer"]
