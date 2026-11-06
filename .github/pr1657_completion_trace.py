"""Closed numeric stage trace, separate from production and qualification claims."""
from pathlib import Path
import hashlib
import json
import os
import subprocess

ROOT = Path.cwd()
OUT = Path(os.environ['RUNNER_TEMP']) / 'pr1657-completion-trace'
OUT.mkdir()
changed = []


def update(name, transform):
    path = ROOT / name
    before = path.read_text(encoding='utf-8')
    after = transform(before)
    assert after != before, name
    path.write_text(after, encoding='utf-8')
    changed.append({'path': name, 'before': hashlib.sha256(before.encode()).hexdigest(),
                    'after': hashlib.sha256(after.encode()).hexdigest()})


def once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


helper = '''
// Disposable diagnostic only: fixed numeric stages, no headers, data or errors.
fn diagnostic_stage(stage: usize, value: usize) {
    use std::sync::atomic::{AtomicUsize, Ordering};
    static EVENTS: AtomicUsize = AtomicUsize::new(0);
    let ordinal = EVENTS.fetch_add(1, Ordering::Relaxed);
    if ordinal < 256 {
        eprintln!("LSF-COMBINED-STAGE:{ordinal}:{stage}:{value}");
    }
}
'''


def root(text):
    text = once(text, 'mod body;', helper + '\nmod body;')
    return once(text, 'fn convert_error(error: Error) -> wit::HttpError {', '''fn convert_error(error: Error) -> wit::HttpError {
    let code = match &error {
        Error::InvalidState => 1,
        Error::UnexpectedEof => 2,
        Error::UnsupportedEncoding => 3,
        Error::Http(HttpError::InvalidUrl) => 4,
        Error::Http(HttpError::InvalidRequest) => 5,
        Error::Http(HttpError::PermissionDenied) => 6,
        Error::Http(HttpError::RequestTooLarge) => 7,
        Error::Http(HttpError::ResponseTooLarge) => 8,
        Error::Http(HttpError::DeadlineExceeded) => 9,
        Error::Http(HttpError::Cancelled) => 10,
        Error::Http(HttpError::BudgetExhausted) => 11,
        Error::Http(HttpError::DnsFailed) => 12,
        Error::Http(HttpError::TlsFailed) => 13,
        Error::Http(HttpError::ConnectionFailed) => 14,
        Error::Http(HttpError::Unavailable) => 15,
        Error::Http(HttpError::Uncertain) => 16,
    };
    diagnostic_stage(99, code);''')


update('crates/latent-wasmtime/src/host/streaming_http.rs', root)


def upload(text):
    # Edit independently delimited functions; repeats elsewhere cannot match.
    for name, number in [('open', 10), ('write', 20), ('finish', 30), ('abort_upload', 40)]:
        start = text.index('pub(super) fn ' + name + '(')
        end = text.find('\npub(super) fn ', start + 1)
        end = len(text) if end < 0 else end
        part = text[start:end]
        needle = 'Box::pin(async move {'
        part = once(part, needle, needle + f'\n            super::diagnostic_stage({number}, 0);')
        if name == 'open':
            part = once(part, 'let result = (&mut pending.value).await;',
                f'let result = (&mut pending.value).await;\n                    super::diagnostic_stage({number + 1}, usize::from(result.is_ok()));')
        if name == 'write':
            part = once(part, 'let result = upload.write(bytes).await;',
                f'let result = upload.write(bytes).await;\n                        super::diagnostic_stage({number + 1}, usize::from(result.is_ok()));')
        if name == 'finish':
            part = once(part, 'Ok(Value::Upload(upload)) => upload.finish().await,', '''Ok(Value::Upload(upload)) => {
                    let result = upload.finish().await;
                    super::diagnostic_stage(31, usize::from(result.is_ok()));
                    result
                },''')
        part = once(part, 'Ok((result.map_err(convert_error),))',
            f'super::diagnostic_stage({number + 2}, usize::from(result.is_ok()));\n                Ok((result.map_err(convert_error),))')
        text = text[:start] + part + text[end:]
    return text


update('crates/latent-wasmtime/src/host/streaming_http/upload.rs', upload)


def body(text):
    for name, number in [('read', 50), ('chunk_bytes', 60), ('trailers', 70), ('abort_body', 80)]:
        start = text.index('pub(super) fn ' + name + '(')
        end = text.find('\npub(super) fn ', start + 1)
        end = len(text) if end < 0 else end
        part = text[start:end]
        needle = 'Box::pin(async move {'
        part = once(part, needle, needle + f'\n            super::diagnostic_stage({number}, 0);')
        if name == 'read':
            part = once(part, 'let result = value.read(maximum as usize).await;', '''let result = value.read(maximum as usize).await;
                        super::diagnostic_stage(51, match &result {
                            Ok(Some(_)) => 1, Ok(None) => 2, Err(_) => 3,
                        });''')
        needle = 'synchronize(&mut store)?;'
        # Last synchronization precedes returning the completed host import.
        assert needle in part
        pos = part.rindex(needle) + len(needle)
        part = part[:pos] + f'\n                super::diagnostic_stage({number + 2}, usize::from(result.is_ok()));' + part[pos:]
        text = text[:start] + part + text[end:]
    return text


update('crates/latent-wasmtime/src/host/streaming_http/body.rs', body)


def workers(text):
    for number, name in [(1, 'native-worker-original-native-limit'),
                         (2, 'native-worker-original-memory-limit'),
                         (3, 'native-worker-original-metadata-limit')]:
        needle = f'.map_err(|_| wasmtime::Error::msg("{name}"))?'
        replacement = f'''.map_err(|_| {{
                eprintln!("LSF-COMBINED-STACK:{number}:{{}}:{{}}", self.runtime.snapshot().owners[6], self.active.load(Ordering::Acquire));
                wasmtime::Error::msg("{name}")
            }})?'''
        text = once(text, needle, replacement)
    return text


update('crates/latent-wasmtime/src/native_stacks/workers.rs', workers)


def observation(text):
    return once(text, '    finally:\n        process.close()', '''    finally:
        try:
            import re
            node.drain()
            markers = [line.decode('ascii') for line in bytes(node.buffers[1]).splitlines()
                       if re.fullmatch(rb'LSF-COMBINED-(?:STAGE:[0-9]{1,3}:[0-9]{1,2}:[0-9]{1,10}|STACK:[0-9]:[0-9]{1,4}:[0-9]{1,4})', line)]
            write_json(output / 'completion-stage-trace.json',
                       {'markers': markers[:264], 'diagnosticOnly': True,
                        'notQualificationEvidence': True})
        except (OSError, ValueError, TypeError, WorkflowError):
            pass
        process.close()''')


update('tools/rust_thread_http_sibling_node.py', observation)
(OUT / 'source-identities.json').write_text(json.dumps(changed, indent=2) + '\n')
(OUT / 'diagnostic.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary']))
print('Only fixed host stage observations added; budgets, grants and peer gates unchanged.')
