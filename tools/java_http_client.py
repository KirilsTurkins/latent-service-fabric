"""Explicit source-bound Java URLConnection profile; qualification is separate."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from tools.rust_capsule_project import canonical, digest, inventory, snapshot, read_file

PROFILE_ID = "lsf.java.httpurlconnection.streaming.v1"
PHASE_PROFILE_ID = "lsf.java.httpurlconnection.phase-timing.v1"
CONNECTION = "dev/latent/guest/client/Connection.java"
# The selected variant replaces this compiler-owned source, never application
# bytecode or a captured dependency. LF/CRLF are the only permitted variants.
PHASE_PREIMAGE = "4112c2d3a1590c96e5da4e17ec4080283516fcd17faae6b2a1c4c23b36e31782"
RECIPE = ("tools/java_http_client.py",)


def selection(value: object) -> dict:
    if (type(value) is not dict or set(value) != {"profile"}
            or type(value['profile']) is not str or value['profile'] not in {PROFILE_ID, PHASE_PROFILE_ID}):
        raise ValueError("unknown Java standard HTTP profile")
    return {"profile": value['profile']}


def phase_source(original: bytes) -> bytes:
    if type(original) is not bytes: raise ValueError('Java phase adapter preimage must be bytes')
    source = original.replace(b'\r\n', b'\n')
    if hashlib.sha256(source).hexdigest() != PHASE_PREIMAGE:
        raise ValueError('Java phase adapter preimage changed')
    text = source.decode('utf-8')
    def replace(before, after):
        nonlocal text
        if text.count(before) != 1: raise ValueError('Java phase adapter source shape changed')
        text = text.replace(before, after)
    replace('import java.net.ProtocolException;', 'import java.net.ProtocolException;\nimport java.net.SocketTimeoutException;')
    replace('    private Map<String, List<String>> responseHeaders;',
        '    private Map<String, List<String>> responseHeaders;\n    private String actualResponseMessage;')
    replace('    private void usable() throws IOException {', '''    private static Option<Long> timeout(int milliseconds) {
        return milliseconds == 0 ? Option.none() : Option.some((long) milliseconds);
    }

    private static IOException phaseError(LatentHttpPhaseTimingPhaseError value) {
        switch (value.tag()) {
            case 0: return error(value.httpValue());
            case 1: return new SocketTimeoutException("http-connect-timeout");
            case 2:
                var timeout = new SocketTimeoutException("http-read-timeout");
                if (value.readTimeoutValue()) timeout.initCause(new HttpFailure("uncertain"));
                return timeout;
            case 3: return new ProtocolException("HTTP phase timing is not installed");
            default: throw new IllegalStateException("unknown typed HTTP phase outcome");
        }
    }

    private static String reason(Option<byte[]> selected) throws IOException {
        if (!selected.isSome()) return null;
        byte[] bytes = selected.value();
        if (bytes.length > 512) throw new HttpFailure("invalid-state");
        char[] characters = new char[bytes.length];
        for (int index = 0; index < bytes.length; index++) characters[index] = (char)(bytes[index] & 255);
        return new String(characters);
    }

    private void usable() throws IOException {''')
    replace('''        if (getConnectTimeout() != 0 || getReadTimeout() != 0) {
            throw fail(new ProtocolException("separate connect/read timeout phases are not qualified"));
        }
''', '')
    if text.count('LatentHttpStreaming.') != 6:
        raise ValueError('Java phase adapter operation preimage changed')
    text = text.replace('LatentHttpStreaming.', 'LatentHttpPhaseTiming.')
    replace('length, media == null ? Option.none() : Option.some(media), Option.none(), Option.none()));',
        'length, media == null ? Option.none() : Option.some(media), Option.none(), Option.none()), timeout(getConnectTimeout()));')
    replace('if (opened.isError()) throw fail(error(opened.error()));',
        'if (opened.isError()) throw fail(phaseError(opened.error()));')
    replace('LatentHttpPhaseTiming.finish(owned);', 'LatentHttpPhaseTiming.finish(owned, timeout(getReadTimeout()));')
    replace('if (completed.isError()) throw fail(error(completed.error()));',
        'if (completed.isError()) throw fail(phaseError(completed.error()));')
    replace('        input = new ResponseInput(result.body());\n', '')
    replace('        var result = completed.value();', '''        var result = completed.value();
        input = new ResponseInput(result.body());
        try { actualResponseMessage = reason(result.reasonPhrase()); }
        catch (IOException invalid) { throw fail(invalid); }''')
    replace('''        // This typed provider exports status and headers, but no reason phrase.
        return null;''', '        return actualResponseMessage;')
    replace('LatentHttpPhaseTiming.read(body, (long) CHUNK_BYTES);',
        'LatentHttpPhaseTiming.read(body, (long) CHUNK_BYTES, timeout(getReadTimeout()));')
    replace('if (next.isError()) throw fail(error(next.error()));',
        'if (next.isError()) throw fail(phaseError(next.error()));')
    return text.encode('utf-8')


def stage_phase(sdk: Path, java_root: Path) -> dict:
    original = read_file(sdk / 'client' / CONNECTION)
    replacement = phase_source(original)
    target = java_root / CONNECTION
    if read_file(target) != original:
        raise ValueError('Java phase adapter source differs from captured SDK')
    target.write_bytes(replacement)
    return {'schemaVersion': 'latent.java.http-phase-source.v1', 'profile': PHASE_PROFILE_ID,
        'originalDigest': digest(original), 'replacementDigest': digest(replacement)}


def profile(sdk: Path, recipe_inputs: bytes, source_inputs: bytes, component: bytes, *, phase_timing: bool = False) -> bytes:
    if type(phase_timing) is not bool: raise ValueError('Java phase adapter requires explicit profile')
    sources = snapshot(sdk / "client")
    original = sources[CONNECTION] if phase_timing else None
    if phase_timing: sources[CONNECTION] = phase_source(original)
    inputs = inventory(sources)
    value = {"schemaVersion": "latent.java.http.profile.v1", "profile": PROFILE_ID,
        "compiler": "teavm-c-0.15.0", "runtimeAdapterDigest": digest(inputs),
        "recipeDigest": digest(recipe_inputs), "sourceDigest": digest(source_inputs),
        "componentDigest": digest(component), "inputs": json.loads(inputs),
        "boundary": "standard-url-default-handler-to-latent-http-streaming-0.3.0",
        "qualification": "pending", "schemes": ["http"],
        "responseMetadata": {"reasonPhrase": "not-supplied-by-typed-provider", "unavailableMessage": None},
        "limits": {"requestBodyBytes": 262144, "responseBodyBytes": 262144, "chunkBytes": 4096},
        "unsupported": ["https-standard-type", "separate-phase-timeouts", "automatic-redirects",
            "explicit-chunk-framing", "raw-status-line", "wire-reason-phrase", "indexed-response-headers",
            "proxy-transport", "socket-address-resolution"]}
    if phase_timing:
        value.update(profile=PHASE_PROFILE_ID, boundary='standard-url-default-handler-to-latent-http-phase-timing-0.4.0',
            sourceTransform={'originalDigest': digest(original), 'replacementDigest': digest(sources[CONNECTION])},
            responseMetadata={'reasonPhrase': 'actual-http1-latin1-if-present', 'unavailableMessage': None,
                'observedEmptyMessage': ''})
        value['unsupported'] = [item for item in value['unsupported']
            if item not in {'separate-phase-timeouts', 'wire-reason-phrase'}]
    return canonical(value)
