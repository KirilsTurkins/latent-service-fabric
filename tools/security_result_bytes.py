"""Keep the authenticated host bytes fork visible to upstream advisories."""
from pathlib import Path

from tools import result_owner_bytes as bounded
from tools.security_common import SecurityError, require

MANIFEST = bounded.MANIFEST


def origin(repo: Path, paths: list[str]) -> dict | None:
    selected = {path for path in paths if path.startswith(bounded.PROVIDER + '/')}
    if not selected:
        return None
    try:
        checked = bounded.verify(repo)
    except (ValueError, OSError, KeyError, TypeError, SecurityError) as error:
        raise SecurityError('unreviewed-result-bytes-source') from error
    require(selected == {bounded.PROVIDER + '/' + name for name in checked['files']},
            'partial-or-unreviewed-result-bytes-source')
    return checked


def inventory_record(repo: Path, entry: dict, paths: list[str]) -> tuple[dict, dict]:
    require(entry == {'path': MANIFEST, 'kind': 'bounded-bytes',
                      'absent_when_directory_missing': bounded.PROVIDER},
            'unreviewed-result-bytes-inventory')
    checked = origin(repo, paths)
    require(checked is not None, 'missing-result-bytes-source')
    return checked, {'path': MANIFEST, 'coverage': 'OSV-and-RustSec-authenticated-origin',
        'packages': 1, 'name': checked['name'], 'version': checked['version'],
        'upstreamArchiveSha256': checked['checksum'], 'recordSha256': checked['recordSha256'],
        'buildLock': 'Cargo.lock',
        'boundary': 'The real root lock remains scanned intact. The exact host-only source '
                    'also retains its upstream bytes advisory coordinate; no advisory exemption.'}
