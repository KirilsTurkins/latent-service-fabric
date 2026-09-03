from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"expected one compatibility marker in {path}: {old!r}; found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


observability = Path("apps/latentd/src/phase0_observability.rs")
text = observability.read_text(encoding="utf-8")
for name in (
    "Phase0CacheInventorySource",
    "Phase0LivePressureSource",
    "Phase0ActivationTopologySource",
):
    marker = f"#[derive(Debug)]\nstruct {name}"
    replacement = f"struct {name}"
    if marker not in text:
        raise SystemExit(f"missing compatibility marker: {marker}")
    text = text.replace(marker, replacement, 1)
expected = "self.pool.observations(CellClass::Standard)"
if text.count(expected) != 2:
    raise SystemExit(
        f"expected two concrete pool snapshot calls, found {text.count(expected)}"
    )
text = text.replace(expected, "self.pool.observations()")
observability.write_text(text, encoding="utf-8")

replace_once(
    Path("crates/latent-telemetry/src/observer.rs"),
    "for (resource, was_exhausted) in exhausted",
    "for (resource, _) in exhausted",
)

local = Path("crates/latent-telemetry/src/local.rs")
text = local.read_text(encoding="utf-8")
marker = "use crate::{LogSeverity, TelemetrySink as _};"
if marker in text:
    local.write_text(
        text.replace(marker, "use crate::LogSeverity;", 1),
        encoding="utf-8",
    )

rpc_build = Path("crates/latent-rpc/build.rs")
replace_once(
    rpc_build,
    ".compile_protos(&proto_files, &[proto_root.clone()])?;",
    ".compile_protos(&proto_files, std::slice::from_ref(&proto_root))?;",
)
replace_once(
    rpc_build,
    '        if !entry.ends_with(".proto") || Path::new(entry).is_absolute() || entry.contains("..") {\n',
    '        let path = Path::new(entry);\n'
    '        let is_proto = path\n'
    '            .extension()\n'
    '            .is_some_and(|extension| extension.eq_ignore_ascii_case("proto"));\n'
    '        if !is_proto || path.is_absolute() || entry.contains("..") {\n',
)

scheduler = Path("crates/latent-scheduler/src/fixed_pool/mod.rs")
replace_once(
    scheduler,
    "    pub(super) inner: Arc<PoolInner>,",
    "    inner: Arc<PoolInner>,",
)
replace_once(
    scheduler,
    "    pub(super) fn managed(\n",
    "    fn managed(\n",
)

replace_once(
    Path("crates/latent-wasmtime/src/bindings.rs"),
    "pub mod runtime {\n    pub use latent_component_bindings::host::runtime::*;\n}",
    "pub mod runtime {\n    #[allow(unused_imports)]\n    pub use latent_component_bindings::host::runtime::*;\n}",
)

replace_once(
    Path("crates/latent-wasmtime/src/containment.rs"),
    "    pub(crate) fn kind(&self) -> Option<GuestInterruptionKind> {\n",
    "    #[cfg_attr(not(test), allow(dead_code))]\n"
    "    pub(crate) fn kind(&self) -> Option<GuestInterruptionKind> {\n",
)

replace_once(
    Path("crates/latent-contracts/src/lib.rs"),
    "    fn publish<'a>(\n"
    "        &'a self,\n"
    "        contract: ContractDescriptor,\n"
    "    ) -> BoxFuture<'a, Result<(), PlatformError>>;\n",
    "    fn publish(\n"
    "        &self,\n"
    "        contract: ContractDescriptor,\n"
    "    ) -> BoxFuture<'_, Result<(), PlatformError>>;\n",
)

replace_once(
    Path("tools/validate_pr53_observability.sh"),
    "cargo clippy --workspace --all-targets --all-features --locked -- -D warnings",
    "cargo clippy --workspace --all-targets --all-features --locked --keep-going",
)
