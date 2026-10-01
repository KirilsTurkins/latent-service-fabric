"""Controlled authored variants for the shared transaction guest qualification.

These are ordinary editable projects produced by the maintained six creators.
They neither change the captured SDK nor install a profile or capability grant.
The forbidden-HTTP component must be rejected by transaction preparation/admission;
successfully compiling its actual import is a prerequisite, not execution evidence.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.rust_capsule_project import read_file, snapshot
from tools.transaction_guest_project import TEMPLATE

LANGUAGES = ("rust", "c", "typescript", "go", "java", "dotnet")
VARIANTS = ("forbidden-http",)
URL = "http://127.0.0.1:1/forbidden-transaction-effect"
HTTP = "latent:http/client@0.2.0"
SOURCES = {
    "rust": "src/lib.rs", "c": "src/main.c", "typescript": "src/main.ts",
    "go": "src/main.go", "java": "src/dev/latent/app/Capsule.java", "dotnet": "src/Main.cs",
}


def replace_once(source: str, before: str, after: str) -> str:
    if source.count(before) != 1:
        raise ValueError("controlled transaction variant source drift")
    return source.replace(before, after)


def forbidden_http(source: str, language: str) -> str:
    """Add a reachable real SDK call, preserving declared business results."""
    if language == "rust":
        source = replace_once(source, '"latent:intents/staging@0.1.0": latent_guest::bindings::intents,',
            '"latent:intents/staging@0.1.0": latent_guest::bindings::intents,\n'
            '        "latent:http/client@0.2.0": latent_guest::bindings::http,')
        return replace_once(source, '        let mut command = Command::acquire()',
            '        latent_guest::http::send(latent_guest::http::Request {\n'
            '            method: latent_guest::http::Method::Get,\n'
            f'            url: "{URL}".into(), headers: vec![], body: None,\n'
            '            body_media_type: None, idempotency_key: None, timeout_millis: Some(1000),\n'
            '        }).await.expect("forbidden immediate HTTP must be denied");\n'
            '        let mut command = Command::acquire()')
    if language == "typescript":
        source = replace_once(source, "import type * as Contract",
            "import { send } from '../vendor/lsf/sdk/typescript-guest/capabilities/http.js';\nimport type * as Contract")
        return replace_once(source, '  update(request) {\n',
            '  update(request) {\n'
            f"    host(send({{ method: 'get', url: '{URL}', headers: [], timeoutMillis: 1000n }}));\n")
    if language == "go":
        source = replace_once(source, '    "encoding/binary"',
            '    "encoding/binary"\n    http "wit_component/lsf/http"')
        return replace_once(source, 'func Update(request UpdateRequest) wit.Result[Aggregate, BusinessError] {\n',
            'func Update(request UpdateRequest) wit.Result[Aggregate, BusinessError] {\n'
            f'    http.Send(http.Request{{Method: http.MethodGet, Url: "{URL}", Headers: []http.Header{{}},\n'
            '        Body: wit.None[[]uint8](), BodyMediaType: wit.None[string](),\n'
            '        IdempotencyKey: wit.None[string](), TimeoutMillis: wit.Some[uint64](1000)}).Ok()\n')
    if language == "java":
        return replace_once(source, '    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {\n',
            '    update(Bindings.ExamplesTransactionalAggregateApiUpdateRequest request) {\n'
            '        Bindings.LatentHttpClient.send(new Bindings.LatentHttpClientRequest(\n'
            f'            Bindings.LatentHttpClientMethod.Get, "{URL}", List.of(),\n'
            '            Option.none(), Option.none(), Option.none(), Option.none())).value();\n')
    if language == "dotnet":
        source = replace_once(source, 'using Raw = ',
            'using HttpRaw = ServiceWorld.wit.Imports.latent.http.IClientImports;\nusing Raw = ')
        return replace_once(source, '    public static Result<IApiExports.Aggregate, IApiExports.BusinessError> Update(IApiExports.UpdateRequest request) {\n',
            '    public static Result<IApiExports.Aggregate, IApiExports.BusinessError> Update(IApiExports.UpdateRequest request) {\n'
            '        _ = Http.Send(new HttpRaw.Request(HttpRaw.Method.GET,\n'
            f'            "{URL}", new System.Collections.Generic.List<HttpRaw.Header>(),\n'
            '            null, null, null, 1000)).AsOk;\n')
    if language != "c":
        raise ValueError("unknown transaction guest language")
    source = replace_once(source, '#include "lsf/intents.h"',
        '#include "lsf/intents.h"\n#include "lsf/http.h"')
    source = replace_once(source, 'enum phase { READ_OLD,', 'enum phase { FORBIDDEN_HTTP, READ_OLD,')
    source = replace_once(source, '    lsf_state_call_t call;',
        '    lsf_state_call_t call;\n'
        '    latent_http_client_request_t http_request;\n'
        '    latent_http_client_result_response_http_error_t http_result;\n'
        '    bool http_returned;')
    source = replace_once(source, '    lsf_state_get_result_close(&frame->read);\n    lsf_state_entry_result_close',
        '    if (frame->http_returned && !frame->http_result.is_err)\n'
        '        lsf_http_response_close(&frame->http_result.val.ok);\n'
        '    lsf_state_get_result_close(&frame->read);\n    lsf_state_entry_result_close')
    source = replace_once(source, '        else lsf_state_call_retire(&frame->call);',
        '        else if (frame->phase != FORBIDDEN_HTTP) lsf_state_call_retire(&frame->call);\n'
        '        if (frame->phase == FORBIDDEN_HTTP)\n'
        '            frame->http_returned = state == LSF_ASYNC_RETURNED || state == LSF_ASYNC_CANCELLED_RETURNED;')
    source = replace_once(source, '        switch (frame->phase) {\n',
        '        switch (frame->phase) {\n'
        '        case FORBIDDEN_HTTP:\n'
        '            lsf_require(!frame->http_result.is_err); /* Never turn a host denial into business success. */\n'
        '            lsf_http_response_close(&frame->http_result.val.ok);\n'
        '            frame->http_returned = false;\n'
        '            frame->phase = READ_OLD;\n'
        '            status = lsf_state_get(&frame->call, &frame->command, key(), &frame->read);\n'
        '            break;\n')
    return replace_once(source,
        '    struct frame *frame = start(UPDATE); frame->delta = request->delta; frame->reject = request->reject;\n'
        '    frame->phase = READ_OLD;\n'
        '    return pump(frame, lsf_async_submit(&frame->async, lsf_state_get(&frame->call, &frame->command, key(), &frame->read)));',
        '    struct frame *frame = start(UPDATE); frame->delta = request->delta; frame->reject = request->reject;\n'
        '    frame->phase = FORBIDDEN_HTTP;\n'
        '    frame->http_request = (latent_http_client_request_t){\n'
        f'        .method = LATENT_HTTP_CLIENT_METHOD_GET, .url = LSF_LITERAL("{URL}"),\n'
        '        .timeout_millis = {true, 1000},\n'
        '    }; /* Literal URL is borrowed; all call arguments stay in the frame until retirement. */\n'
        '    return pump(frame, lsf_async_submit(&frame->async,\n'
        '        latent_http_client_send(&frame->http_request, &frame->http_result)));')


def create(directory: Path, language: str, variant: str, name: str | None = None) -> Path:
    if language not in LANGUAGES or variant not in VARIANTS:
        raise ValueError("unknown controlled transaction guest variant")
    if language == "rust":
        from tools.rust_capsule_project import create as author
    elif language == "c":
        from tools.c_capsule_project import create as author
    elif language == "typescript":
        from tools.typescript_guest.project import create as author
    elif language == "go":
        from tools.go_capsule_project import create as author
    elif language == "java":
        from tools.java_capsule_project import create as author
    else:
        from tools.dotnet_guest.project import create as author
    project = author(directory, TEMPLATE, name or "transaction-" + language + "-" + variant)
    files = snapshot(project)
    world = files["wit/world.wit"].decode()
    if HTTP in world:
        raise ValueError("controlled transaction world unexpectedly permits HTTP")
    world = replace_once(world, "world service {", "world service {\n    import " + HTTP + ";")
    code = forbidden_http(files[SOURCES[language]].decode(), language)
    # Read from the captured SDK, not mutable installed tools or ambient WIT.
    dependency = read_file(project / "vendor/lsf/wit/platform/http-v2/package.wit")
    (project / SOURCES[language]).write_bytes(code.encode())
    (project / "wit/world.wit").write_bytes(world.encode())
    target = project / "wit/deps/forbidden-http/package.wit"
    target.parent.mkdir(parents=True, exist_ok=False)
    with target.open("xb") as output:
        output.write(dependency)
    return project


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", required=True, choices=LANGUAGES)
    parser.add_argument("--variant", required=True, choices=VARIANTS)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--name")
    arguments = parser.parse_args()
    print(create(arguments.project, arguments.language, arguments.variant, arguments.name))


if __name__ == "__main__":
    main()
