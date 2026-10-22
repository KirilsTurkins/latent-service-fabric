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
# Precompiled libc owns raw TCB key slots. The selected source PAL has its own
# generation-checked keys in the charged context. Compile every selected source
# and its ordinary declarations into that private namespace, without aliases or
# changes to the original libc archive. Static archives remain unsupported.
TLS_SYMBOLS = ('pthread_key_create', 'pthread_key_delete', 'pthread_getspecific',
               'pthread_setspecific', 'tss_create', 'tss_delete', 'tss_get', 'tss_set')
# The selected source synchronization implementation must likewise remain
# distinct from strong pthread/C11 symbols in the unchanged precompiled libc.
SYNC_SYMBOLS = ('pthread_mutex_init', 'pthread_mutex_lock', 'pthread_mutex_trylock',
    'pthread_mutex_unlock', 'pthread_mutex_destroy', 'pthread_mutex_timedlock',
    '__pthread_mutex_lock', '__pthread_mutex_trylock', '__pthread_mutex_unlock',
    'pthread_cond_init', 'pthread_cond_destroy', 'pthread_cond_wait',
    'pthread_cond_signal', 'pthread_cond_broadcast', 'pthread_cond_timedwait',
    'mtx_init', 'mtx_lock', 'mtx_trylock', 'mtx_unlock', 'mtx_destroy', 'mtx_timedlock',
    'cnd_init', 'cnd_destroy', 'cnd_wait', 'cnd_signal', 'cnd_broadcast', 'cnd_timedwait')
LIBC = {
    'lib/libc/include/wasm-wasi-musl/pthread.h': '21b1fd90de05919d0718109f16fa1408a0750dcf65f63cc661c506f07e8e1ca1',
    'lib/libc/include/generic-musl/threads.h': '402b75ff71dd5051ebf8744fe7e09a9e43740b9798e6c02701929c852972a2fc',
    'lib/libc/musl/src/thread/pthread_setspecific.c': 'e588f3345a6c8d636fae1b0832827474c74c171fa3dd7861b2a3e5cbe87b5520',
    'lib/libc/musl/src/thread/pthread_getspecific.c': '5b0e9479040a4a891d021daf202dfab5def79233ec948558eaa3c36fd0203cf7',
    'lib/libc/musl/src/thread/tss_set.c': '2dbc898eadabcd478ce8028a0b450e47f02f454d5d66de220805dbd45adcce23',
    'lib/libc/wasi/libc-top-half/musl/src/thread/pthread_key_create.c':
        '96b57e03ae683118bcb004b08b6d42db8990d4abf3731781ec3bfd65d0b0b4ba',
    'lib/libc/include/wasm-wasi-musl/errno.h': '844d1aa7a14734acde284e3109db63e29511540f6c9ccfefe46e455fd5b3ab40',
    'lib/libc/include/wasm-wasi-musl/__errno.h': 'b9ce417c2b172bf982d8ef0236adfe442f54e7d0d344e75104cbcede88a9d7e2',
    'lib/libc/wasi/libc-bottom-half/cloudlibc/src/libc/errno/errno.c': 'eeecab4885f9dba3df77a2c81c1960f1f84779a2b16f0b2aceb1d83af1d47aa3',
    'lib/libc/wasi/libc-bottom-half/sources/__errno_location.c': 'fb6d59a8ca5b99dc0799db259a7b35e7403818469f6cbf6a6ec1178fec98f702',
}


def linked_defines(defines):
    symbols = (*TLS_SYMBOLS, *SYNC_SYMBOLS)
    reserved = {'LSF_C_LINKED_LIBC', *symbols,
                *('__lsf_c_' + name for name in symbols)}
    if any(value.split('=', 1)[0] in reserved for value in defines):
        raise ValueError('c-threading-compiler-owned-tls-symbol')
    return (*defines, 'LSF_C_LINKED_LIBC=1',
            *(name + '=__lsf_c_' + name for name in symbols))


def selected(project):
    profile = project.get('threadingProfile', DEFAULT)
    if type(profile) is not str or profile not in (DEFAULT, PROFILE):
        raise ValueError('unsupported-c-threading-profile')
    return profile == PROFILE


def libc_inputs(zig):
    paths = {name: zig.parent / name for name in LIBC}
    if any(digest(read_file(path, 32768)) != 'sha256:' + LIBC[name] for name, path in paths.items()):
        raise ValueError('c-threading-original-libc-tls-preimage')
    return paths


def libc_material_name(path):
    if path not in LIBC:
        raise ValueError('c-threading-original-libc-material-path')
    return 'c-threading-libc-' + str(sorted(LIBC).index(path))


def stage(source: Path, world: str, destination: Path, platform: Path) -> Path:
    return standard_facilities.stage_imports(source, world, destination, platform, IMPORTS)


def public_export(graph):
    """Read the real generated graph; the selected public async effect uses a synchronous Core ABI."""
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
    require(function['kind'] == 'async-freestanding' and function['name'] == name
            and len(function['params']) == 1 and function['params'][0]['type'] == 'string'
            and type(result) is int and 0 <= result < len(graph['types'])
            and graph['types'][result]['kind'] == {'result': {'ok': 'string', 'err': 'string'}})
    package = graph['packages'][interface['package']]['name']
    require(type(package) is str and re.fullmatch(r'[a-z][a-z0-9-]*:[a-z][a-z0-9-]*@[0-9]+\.[0-9]+\.[0-9]+', package)
            and re.fullmatch(r'[a-z][a-z0-9-]*', interface['name']) and re.fullmatch(r'[a-z][a-z0-9-]*', name))
    return package.replace('@', '/' + interface['name'] + '@') + '#' + name
