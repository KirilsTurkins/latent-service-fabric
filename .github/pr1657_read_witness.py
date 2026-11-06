"""Read one exact signed-witness artifact; never execute or reclassify its payload."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = 'KirilsTurkins/latent-service-fabric'
SOURCE = '00d6ecd48187c292e2d7b9fdc401c8698d3df896'
RUN = 42287769427
LIMIT = 16 * 1024 * 1024
TOKEN = os.environ['GH_TOKEN']

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(suffix):
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + '/' + suffix,
        headers={'Authorization': 'Bearer ' + TOKEN, 'Accept': 'application/vnd.github+json'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        data = response.read(4 * 1024 * 1024 + 1)
    assert len(data) <= 4 * 1024 * 1024
    return json.loads(data)


def public(value, depth=0):
    if depth > 14:
        return '[depth-bound]'
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= 160 and re.fullmatch(r'[A-Za-z0-9_.:/ -]*', value):
            return value
        return {'textBytes': len(value.encode()), 'sha256': hashlib.sha256(value.encode()).hexdigest()}
    if isinstance(value, list):
        assert len(value) <= 2048
        return [public(item, depth + 1) for item in value]
    assert isinstance(value, dict)
    return {key: public(item, depth + 1) for key, item in value.items()
            if not any(word in key.lower() for word in
                ('credential', 'secret', 'authorization', 'headers', 'environment', 'argv', 'startup', 'signing', 'commands', 'materials', 'compilerprojection'))}


def main():
    deadline = time.monotonic() + 600
    while True:
        run = api(f'actions/runs/{RUN}')
        assert run['head_sha'] == SOURCE and run['event'] == 'push'
        assert run['path'] == '.github/workflows/rust-combined-signed-witness.yml'
        if run['status'] == 'completed':
            break
        assert time.monotonic() < deadline, 'original witness not completed during bounded observation'
        time.sleep(10)
    candidates = api(f'actions/runs/{RUN}/artifacts')['artifacts']
    selected, = [row for row in candidates if row['name'] == 'rust-combined-signed-' + SOURCE]
    assert selected['expired'] is False and 0 < selected['size_in_bytes'] <= LIMIT
    assert selected['workflow_run']['id'] == RUN and selected['workflow_run']['head_sha'] == SOURCE
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{selected['id']}/zip",
        headers={'Authorization': 'Bearer ' + TOKEN})
    try:
        urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        assert error.code == 302
        location = error.headers['Location']
    else:
        raise AssertionError('missing artifact redirect')
    parsed = urllib.parse.urlsplit(location)
    assert parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
    assert parsed.hostname.endswith(('.blob.core.windows.net', '.githubusercontent.com', '.github.com'))
    with urllib.request.urlopen(location, timeout=60) as response:
        data = response.read(LIMIT + 1)
    assert len(data) == selected['size_in_bytes']
    digest = 'sha256:' + hashlib.sha256(data).hexdigest()
    assert digest == selected['digest']
    summary = {'run': RUN, 'source': SOURCE, 'originalConclusion': run['conclusion'],
               'artifact': selected['id'], 'bytes': len(data), 'digest': digest, 'records': {}}
    wanted = {'result.json', 'FAILED.json', 'witness.json', 'rust-thread-http-sibling.json',
              'rust-thread-http-terminal.json', 'rust-thread-http-peer-refusal.json',
              'examples-peer-final.json', 'foreign-peer-final.json', 'rust-combined-native-denied.json'}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        assert 0 < len(members) <= 512
        assert len({row.filename.casefold() for row in members}) == len(members)
        assert sum(row.file_size for row in members) <= 128 * 1024 * 1024
        for row in members:
            path = PurePosixPath(row.filename)
            assert not path.is_absolute() and '..' not in path.parts and '\\' not in row.filename
            assert stat.S_IFMT(row.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR)
        assert archive.testzip() is None
        summary['members'] = len(members)
        summary['crcVerified'] = True
        summary['controlMembers'] = [row.filename for row in members if 'controls' in PurePosixPath(row.filename).parts]
        for row in members:
            path = PurePosixPath(row.filename)
            if path.name not in wanted or 'commands' in path.parts or 'signed' in path.parts:
                continue
            assert row.file_size <= 2 * 1024 * 1024
            value = json.loads(archive.read(row))
            if path.name in ('result.json', 'FAILED.json'):
                value = {key: value[key] for key in ('schemaVersion', 'status', 'sourceRevision', 'stage', 'errorCategory', 'nativeGrantRefusal', 'runtimeLimits', 'witness', 'cleanup') if key in value}
            summary['records'][row.filename] = public(value)
    encoded = json.dumps(summary, indent=2, sort_keys=True)
    assert len(encoded.encode()) <= 256 * 1024, 'bounded summary'
    destination = Path(os.environ['RUNNER_TEMP']) / 'pr1657-witness-inspection.json'
    destination.write_text(encoded + '\n', encoding='utf-8')
    print('WITNESS_INSPECTION_BEGIN\n' + encoded + '\nWITNESS_INSPECTION_END')


if __name__ == '__main__':
    main()
