"""Reviewed source recipe used only by the real-node watch qualification driver."""
from pathlib import Path

from tools.dev_workflow import paths, project
from tools.dev_workflow.common import decode, encode, require

WORLD = """package examples:greeting@1.0.0;
interface api { value: func() -> u32; spin: func() -> u32; }
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
        fn spin() -> u32 {
            let mut value = std::hint::black_box(18446744073709551557u64);
            loop { value = std::hint::black_box(value.wrapping_mul(17) / std::hint::black_box(3)); }
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


def edit(author: Path, marker: int, *, mode="normal", compiler_error=False, expected=None):
    (author / "app/src/lib.rs").write_text(COMPONENT.replace("MARKER", str(marker))
        + ("\nthis is deliberately invalid Rust\n" if compiler_error else ""), encoding="utf-8", newline="\n")
    (author / "app/qualification-mode.txt").write_text(mode + "\n", encoding="utf-8", newline="\n")
    (author / "tests/value-expected.json").write_bytes(encode([marker if expected is None else expected]).rstrip(b"\n"))


def author(payload: Path, destination: Path) -> dict:
    entry = decode(paths.read(payload, "templates.json"))["templates"]["greeting"]
    template = payload / entry["path"]
    manifest = decode(paths.read(template, "template.json"))
    project.scaffold(template, destination, manifest, entry["identity"])
    descriptor = manifest["project"]
    require(descriptor["language"] == "rust", "rust-watch-probe-template-required")
    recipe = descriptor["build"]
    require(recipe["argv"][:4] == ["python", "-I", "-B", "@tool:recipe"], "maintained-rust-recipe-required")
    recipe["argv"].insert(3, "qualification_recipe.py")
    recipe["timeoutSeconds"] = 180
    paths.write_new(destination / "app/qualification_recipe.py", RECIPE.encode())
    (destination / "app/wit/world.wit").write_text(WORLD, encoding="utf-8", newline="\n")
    compiled = decode(paths.read(destination, "app/capsule-project.json"))
    compiled["limits"].update(cpuFuel=10000000000, wallTimeLimitMillis=120000)
    (destination / "app/capsule-project.json").write_bytes(encode(compiled))
    paths.write_new(destination / "tests/value-input.json", b"[]")
    case = {"id": "value", "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
        "function": "value", "input": "tests/value-input.json", "mediaType": "application/vnd.latent.wit-values.v1+json",
        "timeoutMillis": 5000, "required": True, "requires": ["fresh-state"], "fixtures": [],
        "execution": {"grants": []}, "expect": {"category": "success", "payload": "tests/value-expected.json"}}
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": [case]}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    edit(destination, 101)
    return descriptor
