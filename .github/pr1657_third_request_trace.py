"""Retain bounded numeric host observations around the third-request stall."""
from pathlib import Path, PurePosixPath
import os, hashlib, zipfile, tarfile, subprocess, io, json
root = Path.cwd()
out = Path(os.environ['RUNNER_TEMP']) / 'pr1657-third-trace'
out.mkdir()
archive = Path(os.environ['RUNNER_TEMP']) / 'candidate.zip'
assert archive.stat().st_size == 5109054
assert hashlib.sha256(archive.read_bytes()).hexdigest() == '7a6ee9b3f5f69d81ff7135ac09dfe15174988dcd9b8244b72117accec33e9608'
with zipfile.ZipFile(archive) as z:
    assert len(z.infolist()) == 149 and z.testzip() is None
    expected = {}
    for line in z.read('pr1657-candidate/source-tree.txt').decode().splitlines():
        meta, name = line.split('\t', 1)
        mode, kind, sha = meta.split()
        expected[name] = (mode, kind, sha)
    selected = []
    with tarfile.open(fileobj=io.BytesIO(z.read('pr1657-candidate/source.tar.gz')), mode='r:gz') as t:
        for member in t:
            if member.isdir():
                continue
            name = member.name
            p = PurePosixPath(name)
            assert member.isfile() and not p.is_absolute() and '..' not in p.parts
            assert name not in selected and member.size <= 2 * 1024 * 1024
            payload = t.extractfile(member).read()
            assert expected[name] == ('100644', 'blob', hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest())
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            selected.append(name)
    assert len(selected) == 24
    subprocess.run(['git', 'add', '--', *selected], check=True)
    assert subprocess.check_output(['git', 'write-tree']).decode().strip() == '4088bad162df1058fb6cb51d989490a3e4bdf98c'

def once(s, old, new):
    assert s.count(old) == 1, old
    return s.replace(old, new)

changes = []
def update(name, function):
    p = root / name
    before = p.read_text()
    after = function(before)
    assert before != after
    p.write_text(after)
    changes.append({'path': name, 'before': hashlib.sha256(before.encode()).hexdigest(), 'after': hashlib.sha256(after.encode()).hexdigest()})

helper = '''
fn trace_http(stage: usize, id: usize, value: usize) {
    use std::sync::{OnceLock, atomic::{AtomicUsize, Ordering}};
    static START: OnceLock<std::time::Instant> = OnceLock::new();
    static COUNT: AtomicUsize = AtomicUsize::new(0);
    let ordinal = COUNT.fetch_add(1, Ordering::Relaxed);
    if ordinal < 512 {
        let micros = START.get_or_init(std::time::Instant::now).elapsed().as_micros();
        eprintln!("LSF-HTTP3:{ordinal}:{micros}:{stage}:{id}:{value}");
    }
}
'''
update('crates/latent-wasmtime/src/host/streaming_http.rs', lambda s: once(s, 'mod body;', helper + '\nmod body;'))

def upload(text):
    for name, number, key in [('open', 10, '0'), ('write', 20, 'target.rep() as usize'), ('finish', 30, 'target.rep() as usize'), ('abort_upload', 40, 'target.rep() as usize')]:
        start = text.index('pub(super) fn ' + name + '(')
        end = text.find('\npub(super) fn ', start + 1)
        if end < 0: end = len(text)
        s = text[start:end]
        s = once(s, 'Box::pin(async move {', 'Box::pin(async move {' + f'\n            let diagnostic_id = {key};\n            super::trace_http({number}, diagnostic_id, 0);')
        if name == 'open':
            s = once(s, 'let result = (&mut pending.value).await;', 'let result = (&mut pending.value).await;\n                    super::trace_http(11, diagnostic_id, usize::from(result.is_ok()));')
        if name == 'finish':
            s = once(s, 'Ok(Value::Upload(upload)) => upload.finish().await,', '''Ok(Value::Upload(upload)) => {
                    let result = upload.finish().await;
                    super::trace_http(31, diagnostic_id, usize::from(result.is_ok()));
                    result
                },''')
        s = once(s, 'Ok((result.map_err(convert_error),))', f'super::trace_http({number + 2}, diagnostic_id, usize::from(result.is_ok()));\n                Ok((result.map_err(convert_error),))')
        text = text[:start] + s + text[end:]
    return text
update('crates/latent-wasmtime/src/host/streaming_http/upload.rs', upload)

def body(text):
    for name, number, key in [('read', 50, 'source.rep() as usize'), ('chunk_bytes', 60, 'value.rep() as usize'), ('trailers', 70, 'source.rep() as usize'), ('abort_body', 80, 'target.rep() as usize')]:
        start = text.index('pub(super) fn ' + name + '(')
        end = text.find('\npub(super) fn ', start + 1)
        if end < 0: end = len(text)
        s = text[start:end]
        s = once(s, 'Box::pin(async move {', 'Box::pin(async move {' + f'\n            let diagnostic_id = {key};\n            super::trace_http({number}, diagnostic_id, 0);')
        if name == 'read':
            s = once(s, 'let result = value.read(maximum as usize).await;', '''let result = value.read(maximum as usize).await;
                        super::trace_http(51, diagnostic_id, match &result { Ok(Some(_)) => 1, Ok(None) => 2, Err(_) => 3 });''')
        needle = 'synchronize(&mut store)?;'
        pos = s.rindex(needle) + len(needle)
        s = s[:pos] + f'\n                super::trace_http({number + 2}, diagnostic_id, usize::from(result.is_ok()));' + s[pos:]
        text = text[:start] + s + text[end:]
    return text
update('crates/latent-wasmtime/src/host/streaming_http/body.rs', body)

def observations(s):
    return once(s, '    finally:\n        process.close()', '''    finally:
        try:
            import re
            node.drain()
            markers = [line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                       if re.fullmatch(rb'LSF-HTTP3:[0-9]{1,3}:[0-9]{1,12}:[0-9]{1,2}:[0-9]{1,10}:[0-9]', line)]
            write_json(output / 'third-request-trace.json', {'diagnosticOnly': True, 'markers': markers[:512]})
        except (OSError, ValueError, TypeError, WorkflowError):
            pass
        process.close()''')
update('tools/rust_thread_http_sibling_node.py', observations)
(out / 'observed-source.json').write_text(json.dumps(changes, indent=2) + '\n')
subprocess.run(['git', 'add', '--', *[row['path'] for row in changes]], check=True)
subprocess.run(['git', 'commit', '-m', 'diag: numeric observation of the corrected third HTTP request'], check=True)
(out / 'trace.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary', '--cached']))
print('Exact proof-tested graph restored. Only bounded host-stage logging added; original budget and peer gates retained.')
