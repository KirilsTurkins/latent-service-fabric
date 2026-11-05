"""One private, fixed media-type observation on the existing HTTP peer."""
from tools.phase2_operator_process import require
from tools.standard_http.peer import Peer

# This value is the original public libfetch fixture's declared media type.
# The peer never copies a received header or credential into its observation.
EXPECTED = b'text/plain; charset=utf-8'


class MediaPeer(Peer):
    """Retain only whether one authenticated ordinary POST has the exact type."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._media_checked = False
        self._media_matches = False

    def _complete_request(self, stream, record):
        require(not self._media_checked and record.vector is not None
                and record.vector.identity == 'method-bytes'
                and record.parser.method == b'POST', 'c-media-one-ordinary-post')
        self._media_checked = True
        self._media_matches = record.parser.headers.get(b'content-type') == EXPECTED
        return super()._complete_request(stream, record)

    def media_observation(self):
        require(self._media_checked, 'c-media-request-not-observed')
        return {'expected': EXPECTED.decode('ascii'), 'exactMatch': self._media_matches,
                'arbitraryHeaderValueRetained': False}
