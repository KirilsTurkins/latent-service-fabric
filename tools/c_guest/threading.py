"""Explicit compiler-owned synchronous cooperative C context profile."""
from pathlib import Path
import re

from tools.c_guest import standard_facilities
from tools.c_guest.bindings import digest
from tools.rust_capsule_project import read_file

PROFILE = 'c-context144-sync-cooperative-v1'
DEFAULT = 'single-threaded'
IMPORTS = ('latent:runtime/activation@0.1.0', 'latent:runtime-native/threads@0.1.0')
RECIPE = ('tools/c_guest/threading.py',)
EXPORTS = ('__stack_pointer', '__tls_base', '__data_end', '__heap_base', '__stack_low',
           '__wasm_call_ctors', '__indirect_function_table', '__lsf_c_thread_body',
           '__lsf_c_root_initialize', '__lsf_c_root_finish')
LIBC = {
    'lib/libc/include/wasm-wasi-musl/errno.h': '844d1aa7a14734acde284e3109db63e29511540f6c9ccfefe46e455fd5b3ab40',
    'lib/libc/include/wasm-wasi-musl/__errno.h': 'b9ce417c2b172bf982d8ef0236adfe442f54e7d0d344e75104cbcede88a9d7e2',
    'lib/libc/wasi/libc-bottom-half/cloudlibc/src/libc/errno/errno.c': 'eeecab4885f9dba3df77a2c81c1960f1f84779a2b16f0b2aceb1d83af1d47aa3',
    'lib/libc/wasi/libc-bottom-half/sources/__errno_location.c': 'fb6d59a8ca5b99dc0799db259a7b35e7403818469f6cbf6a6ec1178fec98f702',
}


def selected(project):
    profile = project.get('threadingProfile', DEFAULT)
    if type(profile) is not str or profile not in (DEFAULT, PROFILE):
        raise ValueError('unsupported-c-threading-profile')
    return profile == PROFILE


def libc_inputs(zig):
    paths = {name: zig.parent / name for name in LIBC}
    if any(digest(read_file(path, 8192)) != 'sha256:' + LIBC[name] for name, path in paths.items()):
        raise ValueError('c-threading-original-libc-errno-preimage')
    return paths


def stage(source: Path, world: str, destination: Path, platform: Path) -> Path:
    return standard_facilities.stage_imports(source, world, destination, platform, IMPORTS)


def public_export(graph):
    """Read the real generated graph; the first profile accepts one sync string API."""
    def require(value):
        if not value:
            raise ValueError('c-threading-finite-public-contract-required')
    require(type(graph) is dict and set(graph) == {'worlds', 'interfaces', 'types', 'packages'})
    require(type(graph['worlds']) is list and len(graph['worlds']) == 1)
    exports = graph['worlds'][0]['exports']
    require(type(exports) is dict and len(exports) == 1)
    key, value = next(iter(exports.items()))
    index = value.get('interface', {}).get('id')
    require(type(index) is int and 0 <= index < len(graph['interfaces']))
    require(key == 'interface-' + str(index))
    interface = graph['interfaces'][index]
    require(interface['types'] == {} and len(interface['functions']) == 1)
    name, function = next(iter(interface['functions'].items()))
    result = function['result']
    require(function['kind'] == 'freestanding' and function['name'] == name
            and len(function['params']) == 1 and function['params'][0]['type'] == 'string'
            and type(result) is int and 0 <= result < len(graph['types'])
            and graph['types'][result]['kind'] == {'result': {'ok': 'string', 'err': 'string'}})
    package = graph['packages'][interface['package']]['name']
    require(type(package) is str and re.fullmatch(r'[a-z][a-z0-9-]*:[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+', package)
            and re.fullmatch(r'[a-z][a-z0-9-]*', interface['name']) and re.fullmatch(r'[a-z][a-z0-9-]*', name))
    return package.replace('@', '/' + interface['name'] + '@') + '#' + name
