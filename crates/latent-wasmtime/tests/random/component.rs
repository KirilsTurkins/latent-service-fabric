//! Real canonical ABI guest, exporting only a marker/length or the requested u64.
use wasm_encoder::*;
#[path = "component/core.rs"]
mod core;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:random/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::random::RANDOM_CAPABILITY;

pub fn bytes() -> Vec<u8> {
    let mut component = Component::new();
    let specification = latent_core::PHASE3_HOST_ABI_CURRENT.interface(CAP).unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(specification.wit, CAP, None));
    types
        .function()
        .params([
            ("mode", PrimitiveValType::U32),
            ("length", PrimitiveValType::U32),
            ("count", PrimitiveValType::U32),
        ])
        .result(Some(PrimitiveValType::U64.into()));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(CAP, ComponentTypeRef::Instance(0));
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    for name in ["bytes", "u64-value"] {
        aliases.alias(Alias::InstanceExport {
            instance: 0,
            kind: ComponentExportKind::Func,
            name,
        });
    }
    component.section(&aliases);
    component.section(&ModuleSection(&core::memory()));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Memory,
        name: "memory",
    });
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "realloc",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    for index in 0..2 {
        canonical.lower(
            index,
            [CanonicalOption::Memory(0), CanonicalOption::Realloc(0)],
        );
    }
    component.section(&canonical);
    component.section(&ModuleSection(&core::caller()));
    let mut instances = InstanceSection::new();
    instances.export_items([
        ("bytes", ExportKind::Func, 1),
        ("u64-value", ExportKind::Func, 2),
    ]);
    instances.instantiate(
        1,
        [
            ("random", ModuleArg::Instance(1)),
            ("memory", ModuleArg::Instance(0)),
        ],
    );
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 2,
        kind: ExportKind::Func,
        name: "run",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(3, 1, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 2)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
    component.section(&exports);
    component.finish()
}
