//! Canonical ABI guest forwards a metric, optionally substitutes a nonfinite
//! number (JSON cannot supply one), and repeats until a typed rejection.
use wasm_encoder::*;
#[path = "component/core.rs"]
mod core;
#[path = "../../../latent-packaging/tests/fixtures/host.rs"]
mod host;
pub const CONTRACT: &str = "tests:metrics/api@1.0.0";
pub const CAP: &str = latent_capabilities::broker::metrics::METRICS_CAPABILITY;
pub fn bytes() -> Vec<u8> {
    let mut component = Component::new();
    let specification = latent_core::PHASE3_HOST_ABI_CURRENT.interface(CAP).unwrap();
    let mut types = ComponentTypeSection::new();
    types.instance(&host::interface(specification.wit, CAP, None));
    component.section(&types);
    let mut imports = ComponentImportSection::new();
    imports.import(CAP, ComponentTypeRef::Instance(0));
    component.section(&imports);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::InstanceExport {
        instance: 0,
        kind: ComponentExportKind::Type,
        name: "metric",
    });
    aliases.alias(Alias::InstanceExport {
        instance: 0,
        kind: ComponentExportKind::Func,
        name: "emit-metric",
    });
    component.section(&aliases);
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .params([
            ("metric", ComponentValType::Type(1)),
            ("count", PrimitiveValType::U32.into()),
            ("mode", PrimitiveValType::U32.into()),
        ])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
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
    canonical.lower(0, [CanonicalOption::Memory(0), CanonicalOption::Realloc(0)]);
    component.section(&canonical);
    component.section(&ModuleSection(&core::caller()));
    let mut instances = InstanceSection::new();
    instances.export_items([("emit-metric", ExportKind::Func, 1)]);
    instances.instantiate(
        1,
        [
            ("metrics", ModuleArg::Instance(1)),
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
    canonical.lift(
        2,
        2,
        [CanonicalOption::Memory(0), CanonicalOption::Realloc(0)],
    );
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("run", ComponentExportKind::Func, 1)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 1, None);
    component.section(&exports);
    component.finish()
}
