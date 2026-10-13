"""An explicit SDK-owned HTTP addition preserves all application contract types."""
from tools.typescript_guest.runtime_profile import (
    FETCH_PROFILE, find_world, public_graph, scoped_selected_world, world_id,
)

HTTP_INTERFACE = "latent:http/streaming@0.3.0"
SDK_RUNTIME_FILES = (
    "http-headers.mjs", "http-body.mjs", "http-objects.mjs", "http-fetch.mjs",
)


def source_paths() -> tuple[str, ...]:
    from tools.typescript_guest.import_profile import source_paths as import_source_paths
    return tuple(dict.fromkeys(import_source_paths() + (
        'tools/typescript_guest/fetch_profile.py', 'tools/typescript_guest/fetch_bindings.mjs',
        'tools/typescript_guest/operation_capture.mjs', 'tools/typescript_guest/fetch_startup.mjs',
        'sdk/typescript-guest/activation/fetch-globals.d.ts', 'wit/platform/http-v3/package.wit',
    ) + tuple('sdk/typescript-guest/runtime/' + name for name in SDK_RUNTIME_FILES)))


def binding_world(canonical: bytes, graph: dict, world: str, http_wit: bytes) -> dict[str, bytes]:
    find_world(graph, world)
    before = public_graph(graph, world)
    if not canonical or not http_wit:
        raise ValueError("fetch-original-and-SDK-HTTP-source-required")
    selected = scoped_selected_world(world)
    package = selected.split("/", 1)[0] + "@1.0.0"
    add = "" if HTTP_INTERFACE in before["imports"] else f"    import {HTTP_INTERFACE};\n"
    document = (f"package {package};\n\nworld selected {{\n"
                f"    include {world};\n" + add + "}\n").encode()
    files = {"world.wit": document, "deps/application/package.wit": canonical}
    if HTTP_INTERFACE not in before['imports']:
        files['deps/sdk-fetch-http/package.wit'] = http_wit
    return files


def check_binding_world(original: dict, derived: dict, http: dict, world: str,
                        selected: str) -> dict:
    before = public_graph(original, world)
    after = public_graph(derived, selected)
    matches = [item for item in http["worlds"] if item["name"] == "sdk-http"]
    if len(matches) != 1:
        raise ValueError("fetch-exact-SDK-HTTP-world-required")
    supplied = public_graph(http, world_id(http, matches[0]))["imports"]
    if set(supplied) != {HTTP_INTERFACE}:
        raise ValueError("fetch-exact-SDK-HTTP-interface-required")
    expected = dict(before["imports"])
    if HTTP_INTERFACE in expected and expected[HTTP_INTERFACE] != supplied[HTTP_INTERFACE]:
        raise ValueError("fetch-shadowed-SDK-HTTP-interface")
    expected.update(supplied)
    if after != {"imports": expected, "exports": before["exports"]}:
        raise ValueError("fetch-binding-world-changed-application-contract")
    return {"profile": FETCH_PROFILE, "SDKImport": HTTP_INTERFACE,
            "originalPublicContractPreserved": True, "authority": "none",
            "qualification": "unknown", "apiSupport": "not-evaluated"}


def runtime_world(files: dict[str, bytes], original: dict, world: str,
                  http_wit: bytes) -> dict[str, bytes]:
    """Add SDK HTTP to the original activation/clock derivation, no second ABI."""
    result = dict(files)
    if HTTP_INTERFACE not in public_graph(original, world)['imports']:
        root = result['world.wit']
        if root.count(b'}\n') != 1:
            raise ValueError('fetch-runtime-world-source-shape')
        result['world.wit'] = root.replace(b'}\n', f'    import {HTTP_INTERFACE};\n}}\n'.encode())
        result['deps/sdk-fetch-http/package.wit'] = http_wit
    return result
