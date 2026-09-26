"""Shared authored failure cases; standard library only, usable outside a checkout."""
from pathlib import Path
import json


WORLD = """package examples:greeting@1.0.0;
interface api {
    bump: func() -> u32;
    fail: func() -> result<u32, string>;
    trap: func() -> u32;
    spin: func() -> u32;
    grow: func() -> u32;
}
world service { export api; }
"""

COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all});
    struct Capsule;
    static COUNT: core::sync::atomic::AtomicU32 = core::sync::atomic::AtomicU32::new(0);
    impl exports::examples::greeting::api::Guest for Capsule {
        fn bump() -> u32 { COUNT.fetch_add(1, core::sync::atomic::Ordering::Relaxed) + 1 }
        fn fail() -> Result<u32, String> { Err("declared".to_owned()) }
        fn trap() -> u32 { core::arch::wasm32::unreachable() }
        fn spin() -> u32 {
            let mut value = 0u32;
            loop { value = std::hint::black_box(value.wrapping_add(1)); }
        }
        fn grow() -> u32 { core::arch::wasm32::memory_grow::<0>(1024) as u32 }
    }
    export!(Capsule);
}
"""


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)


def populate(destination: Path, descriptor: dict):
    app = destination / "app"
    (app / "src/lib.rs").write_text(COMPONENT, encoding="utf-8", newline="\n")
    (app / "wit/world.wit").write_text(WORLD, encoding="utf-8", newline="\n")
    recipe = json.loads((app / "capsule-project.json").read_bytes())
    recipe["limits"].update(cpuFuel=10000000000, wallTimeLimitMillis=5000)
    (app / "capsule-project.json").write_bytes(encode(recipe))
    write_new(destination / "tests/failure-input.json", b"[]")
    write_new(destination / "tests/fresh-result.json", b"[1]")
    write_new(destination / "tests/declared-result.json", b'[{"err":"declared"}]')
    cases = []
    def case(name, function="bump", code=None, **execution):
        row = {"id": name, "service": descriptor["service"], "contract": "examples:greeting/api@1.0.0",
            "function": function, "input": "tests/failure-input.json",
            "mediaType": "application/vnd.latent.wit-values.v1+json", "timeoutMillis": 1000,
            "nodeTimeoutMillis": 5000, "required": True, "requires": ["fresh-state"], "fixtures": [],
            "execution": {"grants": [], **execution},
            "expect": {"category": "success", "payload": "tests/fresh-result.json"}}
        if code:
            row["expect"] = {"category": "platform-failure", "platformCode": code}
        cases.append(row)
        return row
    case("cold-fresh")
    case("warm-fresh")
    case("declared", "fail")["expect"] = {"category": "declared-error", "payload": "tests/declared-result.json"}
    case("trap", "trap", "guest-trap")
    case("after-trap")
    case("fuel", "spin", "fuel-exhausted", fuel="10000")["expect"] = {
        "category": "platform-failure", "platformCodes": {"node": "resource-exhausted", "portable": "fuel-exhausted"}}
    case("after-fuel")
    case("memory", "grow", "memory-exhausted")["expect"] = {
        "category": "platform-failure", "platformCodes": {"node": "resource-exhausted", "portable": "memory-exhausted"}}
    case("after-memory")
    case("deadline", "spin", "deadline-exceeded").update(timeoutMillis=20, nodeTimeoutMillis=20)
    case("after-deadline")
    case("running-cancel", "spin", "cancelled", cancelWhenRunning=True).update(
        timeoutMillis=5000, nodeTimeoutMillis=5000, requires=["running-cancellation"])
    case("after-cancel")
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor, [row["id"] for row in cases if row["id"] != "running-cancel"]
