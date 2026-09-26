"""Authored Rust watch stimuli shared by source and installed-package conductors."""
import json
from pathlib import Path

WORLD = """package examples:greeting@1.0.0;
interface api { value: func() -> u32; spin: async func() -> u32; }
world service { export api; }
"""
COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all});
    struct Capsule;
    static ENTERED: core::sync::atomic::AtomicU32 = core::sync::atomic::AtomicU32::new(0);
    impl exports::examples::greeting::api::Guest for Capsule {
        fn value() -> u32 {
            assert_eq!(ENTERED.fetch_add(1, core::sync::atomic::Ordering::Relaxed), 0);
            MARKER
        }
        async fn spin() -> u32 {
            // Yield through the supported component executor until the test
            // cancels this identity. A CPU-only loop can exhaust its finite
            // fuel before the deployment switch on a faster host. A bare
            // pending future has no registered wakeup and traps instead.
            loop { wit_bindgen::yield_async().await; }
        }
    }
    export!(Capsule);
}
"""
RECIPE = r'''import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).resolve().parents[1]))
from tools.build_process import run_bounded_result
mode=Path('qualification-mode.txt').read_text().strip()
if mode=='slow':
    child="import os,time;from pathlib import Path;Path('../build-cache/qualification-ready.txt').write_text(str(os.getpid()));time.sleep(30)"
    run_bounded_result([sys.executable,'-I','-B','-c',child],cwd=Path.cwd(),env=dict(os.environ),timeout_seconds=35,max_output_bytes=4096)
result=run_bounded_result([sys.executable,'-I','-B',*sys.argv[1:]],cwd=Path.cwd(),env=dict(os.environ),timeout_seconds=120,max_output_bytes=262144)
sys.stdout.buffer.write(result.stdout); sys.stderr.buffer.write(result.stderr)
if result.returncode==0 and mode=='malformed':
    Path('../output/component.wasm').write_bytes(b'deliberately malformed qualification output')
raise SystemExit(result.returncode)
'''


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False) + '\n').encode()


def edit(author: Path, marker: int, *, mode='normal', compiler_error=False, expected=None):
    if type(marker) is not int or mode not in {'normal', 'slow', 'malformed'}:
        raise ValueError('closed-watch-stimulus-required')
    (author / 'app/src/lib.rs').write_text(COMPONENT.replace('MARKER', str(marker))
        + ('\nthis is deliberately invalid Rust\n' if compiler_error else ''), encoding='utf-8', newline='\n')
    (author / 'app/qualification-mode.txt').write_text(mode + '\n', encoding='utf-8', newline='\n')
    (author / 'tests/value-expected.json').write_bytes(encode([marker if expected is None else expected]).rstrip(b'\n'))


def populate(destination: Path, descriptor: dict):
    if descriptor['language'] != 'rust' or descriptor['build']['argv'][:4] != ['python', '-I', '-B', '@tool:recipe']:
        raise ValueError('maintained-rust-watch-recipe-required')
    recipe = descriptor['build']
    recipe['argv'].insert(3, 'qualification_recipe.py')
    recipe['timeoutSeconds'] = 180
    with (destination / 'app/qualification_recipe.py').open('xb') as stream:
        stream.write(RECIPE.encode())
    (destination / 'app/wit/world.wit').write_text(WORLD, encoding='utf-8', newline='\n')
    compiled = json.loads((destination / 'app/capsule-project.json').read_bytes())
    compiled['limits'].update(cpuFuel=10000000000, wallTimeLimitMillis=120000)
    (destination / 'app/capsule-project.json').write_bytes(encode(compiled))
    with (destination / 'tests/value-input.json').open('xb') as stream:
        stream.write(b'[]')
    case = {'id': 'value', 'service': descriptor['service'], 'contract': 'examples:greeting/api@1.0.0',
        'function': 'value', 'input': 'tests/value-input.json', 'mediaType': 'application/vnd.latent.wit-values.v1+json',
        'timeoutMillis': 5000, 'required': True, 'requires': ['fresh-state'], 'fixtures': [],
        'execution': {'grants': []}, 'expect': {'category': 'success', 'payload': 'tests/value-expected.json'}}
    (destination / 'tests/scenarios.json').write_bytes(encode({'schemaVersion': 'latent.dev.scenarios.v1', 'scenarios': [case]}))
    (destination / 'latent.project.json').write_bytes(encode(descriptor))
    edit(destination, 101)
    return descriptor
