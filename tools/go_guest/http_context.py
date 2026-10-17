"""Finite context-aware variants of the authenticated generated HTTP calls.

Original generated entry points and marshalling remain intact. Only a terminal
RETURNED event permits result-buffer decoding; START_CANCELLED restores an own
argument which the callee never acquired. This is not a net/http transport.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from tools.go_guest.runtime import replace_once

IDENTITY = 'latent:http/streaming@0.3.0'
PREIMAGES = {
    'Open': '7f7248f0538934080d883cc78fa7d364cad41b2f372d9e8dfb1217fdbfd563b1',
    'Write': '6d162db06172c76f86ad6c6ebe09f463203a9dcf319858794738b402537b5a26',
    'Finish': '21fdd883d6771904e7c80f5f753fd637bd2a94c11006c9262919e77ddd01eb02',
    'Read': 'da646ad5a4f1fd376eed339a61f1f1708fe86cd0cbccf6aa5e0fd33621e06214',
    'ChunkBytes': '48fd701a04fb49da0bdbb4dcb2b5d09db08d92369446cea2d40239508e16fe70',
    'Trailers': '1cc651d084ac235c823e7de57e553e963527ce3008b58d42ed7edfa37ff5eaad',
}


def generated_source(text: str) -> str:
    additions = []
    if 'lsfHTTPContext' in text or any('func ' + name + 'Context(' in text for name in PREIMAGES):
        raise ValueError('go-http-context-already-derived')
    if not re.search(r'(?m)^//go:wasmimport ' + re.escape(IDENTITY) + r' ', text):
        raise ValueError('go-http-context-import-identity')
    for name, expected in PREIMAGES.items():
        matches = list(re.finditer(r'(?ms)^func ' + name + r'\([^\n]*\)[^\n]* \{\n.*?^\}', text))
        if len(matches) != 1 or hashlib.sha256(matches[0][0].encode()).hexdigest() != expected:
            raise ValueError('go-http-context-generated-source-drift:' + name)
        original = matches[0][0]
        signature = re.fullmatch(r'func ' + name + r'\((.*)\) witTypes.Result\[(.*), HttpError\] \{',
                                 original.splitlines()[0])
        if signature is None:
            raise ValueError('go-http-context-result-shape')
        error = 'return witTypes.Err[' + signature[2] + ', HttpError](MakeHttpErrorCancelled())'
        adapted = replace_once(original, original.splitlines()[0],
            f'func {name}Context(ctx lsfHTTPContext.Context, {signature[1]}) witTypes.Result[{signature[2]}, HttpError] {{\n'
            f'\tif ctx.Err() != nil {{ {error} }}')
        calls = list(re.finditer(r'(?m)^\twitAsync.SubtaskWait\(uint32\((wasm_import_[^\n]+)\)\)$', adapted))
        if len(calls) != 1:
            raise ValueError('go-http-context-call-shape')
        call = calls[0][1]
        prefix, restore = '', ''
        if name == 'Finish':
            call = replace_once(call, '(target).TakeHandle()', 'argumentHandle')
            prefix = '\targumentHandle := target.TakeHandle()\n'
            restore = '\t\tif status == witAsync.LSF_HTTP_START_CANCELLED { target.SetHandle(argumentHandle) }\n'
        elif '.TakeHandle()' in call:
            raise ValueError('go-http-context-unreviewed-own-argument')
        replacement = (prefix + '\tstatus := witAsync.SubtaskWaitContext(ctx, uint32(' + call + '))\n'
            '\tif status != 2 {\n' + restore + '\t\t' + error + '\n\t}')
        adapted = replace_once(adapted, calls[0][0], replacement)
        additions.append(adapted)
    text = replace_once(text, 'import (\n', 'import (\n\tlsfHTTPContext "context"\n')
    return text + '\n\n' + '\n\n'.join(additions) + '\n'


def async_source(text: str, sdk: Path) -> str:
    # activation.async_source authenticates the complete original dispatcher.
    # This addition runs after timer/initializer derivation and retains their
    # own completion prehandler and fresh scheduler quiescence checks.
    text = replace_once(text, 'import (\n', 'import (\n\tlsfHTTPContext "context"\n')
    text = replace_once(text, '\t\t\tcase STATUS_RETURNED:\n',
        '\t\t\tcase STATUS_RETURNED, LSF_HTTP_START_CANCELLED, LSF_HTTP_RETURN_CANCELLED:\n')
    if 'if lsfHandleTimerEvent(event1) { break }' in text:
        text = replace_once(text, 'if lsfHandleTimerEvent(event1) { break }',
            'if event2 == STATUS_RETURNED && lsfHandleTimerEvent(event1) { break }')
    text = replace_once(text, '\t\tstate.pending[subtask] = channel\n\t\t(<-channel)',
        '\t\tstate.pending[subtask] = channel\n\t\tif (<-channel) != STATUS_RETURNED { panic("unexpected ordinary subtask cancellation") }')
    return text + '\n' + (sdk / 'runtime/http_async.go.in').read_text()
