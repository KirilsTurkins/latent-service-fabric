"""Exact canonical async-call variants for the declared streams interface.

Only terminal completion permits decoding the pinned result area. An
acknowledged cancellation after entry is kept uncertain for operations which
can consume bytes or a connection; it is never relabelled as no effect.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

from tools.go_guest.runtime import replace_once

IDENTITY = 'latent:network/streams@0.1.0'
PREIMAGES = {
    'Connect': '33762dda2aa61bd50f5fb2ed3134ec829232d92412fa3ac59aef3966a367ffa9',
    'Read': '820dff7524049f3767737c3e4b7d99f92e347cc2dacf98b93eb697ddfe808de6',
    'Write': '262d1fc4309d2827c4d994e0228e8b12cd579d142d7805f8dd3b6ffa8e6e0a63',
    'Ready': '0ded6ffa903d499750954cfe6059062699bac2514fac521406350864c5ae5e91',
    'ChunkBytes': '31069ffd4656cd132f73cb9bec61257a6e17e5a83a7a48b9e7ad4065fcb3d6b2',
    'Shutdown': '4735a66953463a9b3f0d3251428eeac435904060b9dbae7613a9208bcf2f1964',
    'Close': '7d6e0e93d7ff244ed48b33daf3a03b19252117e42f8fd85006d832413131aaa2',
}
MAY_APPLY = {'Connect', 'Read', 'Write', 'Shutdown', 'Close'}


def selected(module: Path, runtime_profile: str) -> bool:
    """Recognition does not install a provider or grant a destination."""
    imported = []
    for path in sorted(module.glob('*/wit_bindings.go')):
        text = path.read_text()
        identities = re.findall(r'(?m)^//go:wasmimport (latent:network/[^ ]+) ', text)
        if not identities:
            continue
        if set(identities) != {IDENTITY}:
            raise ValueError('go-network-contract-not-installed')
        imported.append(path)
    if not imported:
        return False
    if runtime_profile != 'go-component-activation-v5':
        raise ValueError('go-network-requires-managed-v5')
    if len(imported) != 1 or imported[0].parent.name != 'latent_network_streams':
        raise ValueError('go-network-generated-package-identity')
    return True


def generated_source(text: str) -> str:
    if 'lsfNetworkContext' in text or any('func ' + name + 'Context(' in text for name in PREIMAGES):
        raise ValueError('go-network-context-already-derived')
    if not re.search(r'(?m)^//go:wasmimport ' + re.escape(IDENTITY) + r' ', text):
        raise ValueError('go-network-context-import-identity')
    additions = []
    for name, expected in PREIMAGES.items():
        matches = list(re.finditer(r'(?ms)^func ' + name + r'\([^\n]*\)[^\n]* \{\n.*?^\}', text))
        if len(matches) != 1 or hashlib.sha256(matches[0][0].encode()).hexdigest() != expected:
            raise ValueError('go-network-context-generated-source-drift:' + name)
        original = matches[0][0]
        signature = re.fullmatch(r'func ' + name + r'\((.*)\) witTypes.Result\[(.*), StreamError\] \{',
                                 original.splitlines()[0])
        if signature is None:
            raise ValueError('go-network-context-result-shape')
        cancelled = 'return witTypes.Err[' + signature[2] + ', StreamError](StreamError{Code: ErrorCodeCancelled})'
        deadline = 'return witTypes.Err[' + signature[2] + ', StreamError](StreamError{Code: ErrorCodeTimeout})'
        local_failure = ('if ctx.Err() == lsfNetworkContext.DeadlineExceeded { ' + deadline + ' }\n' +
                         '\t\t' + cancelled)
        adapted = replace_once(original, original.splitlines()[0],
            f'func {name}Context(ctx lsfNetworkContext.Context, {signature[1]}) witTypes.Result[{signature[2]}, StreamError] {{\n'
            f'\tif ctx.Err() != nil {{ {local_failure} }}')
        calls = list(re.finditer(r'(?m)^\twitAsync.SubtaskWait\(uint32\((wasm_import_[^\n]+)\)\)$', adapted))
        if len(calls) != 1:
            raise ValueError('go-network-context-call-shape')
        call, prefix, restore = calls[0][1], '', ''
        if name == 'Close':
            call = replace_once(call, '(target).TakeHandle()', 'argumentHandle')
            prefix = '\targumentHandle := target.TakeHandle()\n'
            restore = '\t\tif status == witAsync.LSF_HTTP_START_CANCELLED { target.SetHandle(argumentHandle) }\n'
        elif '.TakeHandle()' in call:
            raise ValueError('go-network-context-unreviewed-own-argument')
        failure = '\t\t' + local_failure + '\n'
        if name in MAY_APPLY:
            failure = ('\t\tif status != witAsync.LSF_HTTP_START_CANCELLED {\n'
                '\t\t\treturn witTypes.Err[' + signature[2] + ', StreamError]('
                'StreamError{Code: ErrorCodeUncertain, MayHaveApplied: true})\n\t\t}\n') + failure
        replacement = (prefix + '\tstatus := witAsync.SubtaskWaitContext(ctx, uint32(' + call + '))\n'
            '\tif status != 2 {\n' + restore + failure + '\t}')
        adapted = replace_once(adapted, calls[0][0], replacement)
        additions.append(adapted)
    text = replace_once(text, 'import (\n', 'import (\n\tlsfNetworkContext "context"\n')
    return text + '\n\n' + '\n\n'.join(additions) + '\n'
