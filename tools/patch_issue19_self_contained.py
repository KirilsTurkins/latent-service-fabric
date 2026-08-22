#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}: {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


builder = ROOT / "tools" / "build_echo_capsule.py"
replace_once(
    builder,
    'TARGET = "wasm32-wasip2"\n',
    'BINDINGS_TARGET = "wasm32-wasip2"\nCORE_TARGET = "wasm32-unknown-unknown"\n',
)
replace_once(
    builder,
    '''    configured_target = str(toolchain["rust"]["target"])
    if configured_target != TARGET:
        raise BuildError(
            f"tools/toolchain.toml selects {configured_target}; the echo fixture expects {TARGET}"
        )
''',
    '''    configured_bindings_target = str(toolchain["rust"]["target"])
    if configured_bindings_target != BINDINGS_TARGET:
        raise BuildError(
            "tools/toolchain.toml selects "
            f"{configured_bindings_target} for generated-binding checks; "
            f"the echo fixture expects {BINDINGS_TARGET}"
        )

    configured_core_target = str(toolchain["rust"]["component-target"])
    if configured_core_target != CORE_TARGET:
        raise BuildError(
            "tools/toolchain.toml selects "
            f"{configured_core_target} for component cores; "
            f"the echo fixture expects {CORE_TARGET}"
        )
''',
)
replace_once(builder, '            TARGET,\n', '            CORE_TARGET,\n')
replace_once(
    builder,
    '    return extract_cargo_artifact(completed.stdout).read_bytes()\n',
    '''    core_artifact = extract_cargo_artifact(completed.stdout)
    component_artifact = build_directory / "componentized" / ARTIFACT_NAME
    component_artifact.parent.mkdir(parents=True, exist_ok=True)
    wasm_tools = command_from_environment("WASM_TOOLS", "wasm-tools")
    run_checked(
        [
            *wasm_tools,
            "component",
            "new",
            str(core_artifact),
            "-o",
            str(component_artifact),
        ],
        environment=canonical_build_environment(),
    )
    return component_artifact.read_bytes()
''',
)
replace_once(builder, '            "target": TARGET,\n', '            "target": CORE_TARGET,\n')

toolchain = ROOT / "tools" / "toolchain.toml"
replace_once(
    toolchain,
    'target = "wasm32-wasip2"\n',
    'target = "wasm32-wasip2"\ncomponent-target = "wasm32-unknown-unknown"\n',
)

rust_toolchain = ROOT / "rust-toolchain.toml"
replace_once(
    rust_toolchain,
    'targets = ["wasm32-wasip2"]\n',
    'targets = ["wasm32-wasip2", "wasm32-unknown-unknown"]\n',
)

validate = ROOT / "tools" / "validate_contracts.sh"
validate.write_text(
    '''#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_ROOT="${CARGO_TARGET_DIR:-${ROOT}/target}"
if [[ "${TARGET_ROOT}" != /* ]]; then
    TARGET_ROOT="${ROOT}/${TARGET_ROOT}"
fi
OUTPUT="${TARGET_ROOT}/contracts"

cd "${ROOT}"
rm -rf "${OUTPUT}"
mkdir -p "${OUTPUT}/wit" "${OUTPUT}/proto" "${OUTPUT}/example-wit"

python3 tools/validate_repository.py
python3 -m unittest discover -s tools/tests

while IFS= read -r package; do
    name="$(basename "${package}")"
    if [[ "${name}" == "runtime" ]]; then
        continue
    fi
    wasm-tools component wit "${package}" --json > "${OUTPUT}/wit/platform-${name}.json"
done < <(find "${ROOT}/wit/platform" -mindepth 1 -maxdepth 1 -type d | sort)

python3 tools/stage_runtime_wit.py "${OUTPUT}/runtime-wit"
wasm-tools component wit "${OUTPUT}/runtime-wit" --json > "${OUTPUT}/wit/platform-runtime.json"

while IFS= read -r package; do
    relative="${package#"${ROOT}/"}"
    artifact="${relative//\//-}"
    staged="${OUTPUT}/example-wit/${artifact}"
    python3 tools/stage_runtime_wit.py "${staged}" --source "${package}"
    wasm-tools component wit "${staged}" --json > "${OUTPUT}/wit/${artifact}.json"
done < <(find "${ROOT}/examples" -type d -name wit | sort)

buf lint api/proto
buf build api/proto --as-file-descriptor-set -o "${OUTPUT}/proto/latent-api.bin"

cargo check -p latent-toolchain-smoke --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example echo-capsule --target wasm32-wasip2 --locked
cargo check -p latent-toolchain-smoke --example oversized-log-capsule --target wasm32-wasip2 --locked
python3 tools/build_echo_capsule.py --verify-reproducible
cargo build -p latent-toolchain-smoke --example oversized-log-capsule \
    --target wasm32-unknown-unknown --release --locked
OVERSIZED_LOG_CORE="${TARGET_ROOT}/wasm32-unknown-unknown/release/examples/oversized_log_capsule.wasm"
OVERSIZED_LOG_COMPONENT="${TARGET_ROOT}/capsules/oversized-log/oversized-log-capsule.wasm"
mkdir -p "$(dirname "${OVERSIZED_LOG_COMPONENT}")"
wasm-tools component new "${OVERSIZED_LOG_CORE}" -o "${OVERSIZED_LOG_COMPONENT}"
wasm-tools validate "${OVERSIZED_LOG_COMPONENT}"
LSF_ECHO_COMPONENT="${TARGET_ROOT}/capsules/echo/echo-capsule.wasm" \
LSF_ECHO_CAPSULE="${TARGET_ROOT}/capsules/echo/capsule.json" \
LSF_OVERSIZED_LOG_COMPONENT="${OVERSIZED_LOG_COMPONENT}" \
    cargo test -p latent-wasmtime --test echo_backend --locked -- --ignored --nocapture
''',
    encoding="utf-8",
)

readme = ROOT / "examples" / "echo-contract" / "README.md"
replace_once(
    readme,
    'The artifact is locally trusted because it is produced from the current checkout with the committed `Cargo.lock`, Rust 1.97.1, `wasm32-wasip2`, `wit-bindgen` 0.60.0, and `wasm-tools` 1.254.0.',
    'The artifact is locally trusted because it is produced from the current checkout with the committed `Cargo.lock`, Rust 1.97.1, a self-contained `wasm32-unknown-unknown` core compiled with `wit-bindgen` 0.60.0, and explicit componentization with `wasm-tools` 1.254.0.',
)
replace_once(
    readme,
    'A reproducibility check performs two isolated clean builds and requires byte-identical component bytes:',
    'The builder compiles a self-contained core module for `wasm32-unknown-unknown`, componentizes it with `wasm-tools component new`, and rejects any ambient authority in the extracted world. A reproducibility check performs two isolated clean builds and requires byte-identical component bytes:',
)

toolchain_doc = ROOT / "docs" / "development" / "toolchain.md"
replace_once(
    toolchain_doc,
    '| Rust guest target | `wasm32-wasip2` | Compile generated guest bindings and the echo Component Model fixture |',
    '| Rust binding-check target | `wasm32-wasip2` | Compile generated guest bindings against the preview-2 target |\n| Rust component-core target | `wasm32-unknown-unknown` | Build a self-contained core module before explicit Component Model wrapping |',
)
replace_once(
    toolchain_doc,
    'The Rust toolchain file installs `rustfmt`, Clippy, and `wasm32-wasip2`.',
    'The Rust toolchain file installs `rustfmt`, Clippy, `wasm32-wasip2`, and `wasm32-unknown-unknown`.',
)
replace_once(
    toolchain_doc,
    '`tools/validate_contracts.sh` also compiles the generated echo bindings for `wasm32-wasip2`, builds the release component twice, requires byte-identical output, validates the binary with `wasm-tools`, extracts its interface, rejects any import/export drift, and emits generated capsule metadata with the actual SHA-256 digest.',
    '`tools/validate_contracts.sh` compiles the generated echo bindings for `wasm32-wasip2`, builds the self-contained release core for `wasm32-unknown-unknown`, wraps it with `wasm-tools component new`, repeats that process in isolation, requires byte-identical component output, validates the binary, extracts its interface, rejects any import/export drift, and emits generated capsule metadata with the actual SHA-256 digest.',
)

phase_doc = ROOT / "docs" / "development" / "phase-0-wasmtime.md"
replace_once(
    phase_doc,
    'cargo build -p latent-toolchain-smoke --example oversized-log-capsule \\\n  --target wasm32-wasip2 --release --locked',
    'cargo build -p latent-toolchain-smoke --example oversized-log-capsule \\\n  --target wasm32-unknown-unknown --release --locked\nwasm-tools component new \\\n  target/wasm32-unknown-unknown/release/examples/oversized_log_capsule.wasm \\\n  -o target/capsules/oversized-log/oversized-log-capsule.wasm',
)
replace_once(
    phase_doc,
    'LSF_OVERSIZED_LOG_COMPONENT=target/wasm32-wasip2/release/examples/oversized-log-capsule.wasm',
    'LSF_OVERSIZED_LOG_COMPONENT=target/capsules/oversized-log/oversized-log-capsule.wasm',
)

tests = ROOT / "tools" / "tests" / "test_build_echo_capsule.py"
replace_once(
    tests,
    'class BuildEchoCapsuleTests(unittest.TestCase):\n',
    '''class BuildEchoCapsuleTests(unittest.TestCase):
    def test_component_build_uses_a_self_contained_core_target(self) -> None:
        self.assertEqual(build_echo_capsule.BINDINGS_TARGET, "wasm32-wasip2")
        self.assertEqual(build_echo_capsule.CORE_TARGET, "wasm32-unknown-unknown")
        self.assertNotEqual(
            build_echo_capsule.BINDINGS_TARGET,
            build_echo_capsule.CORE_TARGET,
        )

''',
)

print("patched the Issue #19 component pipeline for a self-contained core")
