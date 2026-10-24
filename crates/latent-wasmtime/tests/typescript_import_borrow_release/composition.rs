//! Source-only composition. Original CAP is imported ONCE; no resource adoption.
//! RawSection/instantiate APIs are the pinned wasm-encoder0.261.0 maintained
//! source at wasm-tools/v1.261.0 (raw.rs, component/components.rs, instances.rs).
use wasm_encoder::*;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
use super::gate;

pub const CONTRACT: &str = "tests:typescript-import-borrow-probe/api@1.0.0";
pub const ACTIVATION: &str = "latent:runtime/activation@0.1.0";
pub const MONOTONIC: &str = "latent:clock/monotonic@0.1.0";
pub const WALL: &str = "latent:clock/wall@0.1.0";
pub const WORLD: &str =
    include_str!("../../../../sdk/typescript-guest/probes/borrow-release/outer.wit");

/// Wrap only the actual compiler-built component. Executed validation is
/// mandatory in the future owning harness; no source-stage pass is inferred.
pub fn bytes(guest: &[u8]) -> Vec<u8> {
    assert!(guest.starts_with(b"\0asm\x0d\0\x01\0"));
    assert!(guest.len() <= 32 * 1024 * 1024);
    let interfaces = [gate::CAP, ACTIVATION, MONOTONIC, WALL];
    let mut component = Component::new();
    let mut types = ComponentTypeSection::new();
    for name in interfaces {
        let spec = latent_core::PHASE3_HOST_ABI_V5.interface(name).unwrap();
        types.instance(&host::interface(spec.wit, spec.interface, None));
    }
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    for (index, name) in interfaces.into_iter().enumerate() {
        imports.import(
            name,
            ComponentTypeRef::Instance(u32::try_from(index).unwrap()),
        );
    } // original instances0..3; CAP has a single original type/resource authority.
    component.section(&imports);
    let gate = gate::bytes();
    component.section(&RawSection {
        id: ComponentSectionId::Component.into(),
        data: &gate,
    }); // component0
    component.section(&RawSection {
        id: ComponentSectionId::Component.into(),
        data: guest,
    }); // component1
    let mut instances = ComponentInstanceSection::new();
    instances.instantiate(0, [(gate::CAP, ComponentExportKind::Instance, 0)]); // instance4
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    for name in [gate::GATE_CONTRACT, gate::DIAGNOSTIC_CONTRACT] {
        aliases.alias(Alias::InstanceExport {
            instance: 4,
            kind: ComponentExportKind::Instance,
            name,
        });
    } // instance5=gate streams with EXACT original resources, instance6=diagnostic.
    component.section(&aliases);
    let mut instances = ComponentInstanceSection::new();
    instances.instantiate(
        1,
        [
            (gate::CAP, ComponentExportKind::Instance, 0),
            (ACTIVATION, ComponentExportKind::Instance, 1),
            (MONOTONIC, ComponentExportKind::Instance, 2),
            (WALL, ComponentExportKind::Instance, 3),
            (gate::GATE_CONTRACT, ComponentExportKind::Instance, 5),
            (gate::DIAGNOSTIC_CONTRACT, ComponentExportKind::Instance, 6),
        ],
    ); // instance7; its ordinary CAP permit reads share the original resource.
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::InstanceExport {
        instance: 7,
        kind: ComponentExportKind::Instance,
        name: CONTRACT,
    }); // instance8
    component.section(&aliases);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 8, None);
    component.section(&exports);
    let bytes = component.finish();
    assert!(bytes.len() <= 40 * 1024 * 1024);
    wasmparser::Validator::new_with_features(wasmparser::WasmFeatures::all())
        .validate_all(&bytes)
        .unwrap();
    bytes
}
