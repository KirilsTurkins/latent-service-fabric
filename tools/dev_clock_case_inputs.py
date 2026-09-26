"""Shared authored clock cases; standard library only, usable outside a checkout."""
from pathlib import Path
import hashlib
import json


WORLD = """package examples:greeting@1.0.0;
interface api {
    record reading { monotonic: u64, wall: u64 }
    clocks: func() -> reading;
}
world service {
    import latent:clock/monotonic@0.1.0;
    import latent:clock/wall@0.1.0;
    export api;
}
"""

COMPONENT = """#[cfg(target_arch = "wasm32")]
mod component {
    wit_bindgen::generate!({path: "wit", world: "service", generate_all});
    struct Capsule;
    impl exports::examples::greeting::api::Guest for Capsule {
        fn clocks() -> exports::examples::greeting::api::Reading {
            exports::examples::greeting::api::Reading {
                monotonic: latent::clock::monotonic::now_nanos(),
                wall: latent::clock::wall::now_unix_millis(),
            }
        }
    }
    export!(Capsule);
}
"""


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True) + '\n').encode()


def digest(value):
    return 'sha256:' + hashlib.sha256(value).hexdigest()


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw)


def populate(destination: Path, descriptor: dict):
    app = destination / "app"
    (app / "src/lib.rs").write_text(COMPONENT, encoding="utf-8", newline="\n")
    (app / "wit/world.wit").write_text(WORLD, encoding="utf-8", newline="\n")
    clocks = app / "wit/deps/clock"
    clocks.mkdir(parents=True)
    write_new(clocks / "package.wit", (app / "vendor/lsf/wit/platform/clock/package.wit").read_bytes())
    cases = []
    grants = ["latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0"]
    for name, value in (("zero", "0"), ("maximum", "18446744073709551615")):
        fixture = encode({"clock": {"monotonicNanos": value, "wallUnixMillis": value}})
        write_new(destination / f"tests/clock-{name}.json", fixture)
        write_new(destination / f"tests/clock-{name}-expected.json",
                        json.dumps([{"monotonic": value, "wall": value}], separators=(",", ":")).encode())
        for behavior in ("cold", "warm", "denied", "fresh"):
            case = {"id": f"clock-{name}-{behavior}", "service": descriptor["service"],
                "contract": "examples:greeting/api@1.0.0", "function": "clocks", "input": "tests/clock-input.json",
                "mediaType": "application/vnd.latent.wit-values.v1+json", "timeoutMillis": 1000,
                "nodeTimeoutMillis": 5000, "required": True, "requires": ["clock"],
                "fixtures": [{"id": f"clock-{name}", "kind": "test-adapter", "identity": digest(fixture),
                              "configuration": f"tests/clock-{name}.json"}],
                "execution": {"grants": grants},
                "expect": {"category": "success", "payload": f"tests/clock-{name}-expected.json"}}
            if behavior == "denied":
                case["execution"] = {"grants": grants, "deniedCapabilities": grants}
                case["expect"] = {"category": "platform-failure", "platformCode": "guest-trap"}
            cases.append(case)
    write_new(destination / "tests/clock-input.json", b"[]")
    (destination / "tests/scenarios.json").write_bytes(encode({"schemaVersion": "latent.dev.scenarios.v1", "scenarios": cases}))
    (destination / "latent.project.json").write_bytes(encode(descriptor))
    return descriptor
