//! Tiny real no-argument component; one custom byte distinguishes releases.
use std::borrow::Cow;
use wasm_encoder::{
    Alias, CanonicalFunctionSection, CodeSection, Component, ComponentAliasSection,
    ComponentExportKind, ComponentExportSection, ComponentInstanceSection, ComponentTypeSection,
    ComponentValType, CustomSection, ExportKind, ExportSection, Function, FunctionSection,
    InstanceSection, Instruction, Module, ModuleArg, ModuleSection, TypeSection,
};

pub(super) fn artifact(marker: u8) -> latent_artifacts::CapsuleArtifact {
    let mut artifact =
        super::super::fixtures::artifact("tests", "echo", &format!("canary-{marker}"));
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], []);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("echo", ExportKind::Func, 0);
    module.section(&exports);
    let mut body = Function::new([]);
    body.instruction(&Instruction::Nop);
    body.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    let mut component = Component::new();
    component.section(&CustomSection {
        name: Cow::Borrowed("release"),
        data: Cow::Owned(vec![marker]),
    });
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(None);
    component.section(&types);
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "echo",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 0, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("echo", ComponentExportKind::Func, 0)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(
        "tests:echo/api@1.0.0",
        ComponentExportKind::Instance,
        0,
        None,
    );
    component.section(&exports);
    artifact.component_bytes = component.finish();
    artifact.descriptor.size_bytes = artifact.component_bytes.len() as u64;
    let digest = latent_artifacts::content_digest(&artifact.component_bytes);
    artifact.descriptor.release_digest = digest.clone();
    artifact.manifest.component_digest = digest;
    artifact
}
