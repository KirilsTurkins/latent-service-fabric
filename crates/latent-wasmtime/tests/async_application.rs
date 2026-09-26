//! Application async function kind must not require unrelated provider authority.
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;
#[path = "async_application/web.rs"]
mod web;
use latent_executor::ExecutionBackend;
use latent_wasmtime::WasmtimeComponentEngineFactory;
use wasm_encoder::*;

const CONTRACT: &str = "tests:web-async/api@1.0.0";

fn component() -> Vec<u8> {
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I32]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("answer", ExportKind::Func, 0);
    module.section(&exports);
    let mut body = Function::new([]);
    body.instruction(&Instruction::I32Const(42));
    body.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&body);
    module.section(&code);
    let mut component = Component::new();
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "answer",
    });
    component.section(&aliases);
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .async_(true)
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U32.into()));
    component.section(&types);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 0, []);
    component.section(&canonical);
    let mut instances = ComponentInstanceSection::new();
    instances.export_items([("answer", ComponentExportKind::Func, 0)]);
    component.section(&instances);
    let mut exports = ComponentExportSection::new();
    exports.export(CONTRACT, ComponentExportKind::Instance, 0, None);
    component.section(&exports);
    component.finish()
}

#[tokio::test]
async fn import_free_async_application_prepares_executes_and_reuses_without_a_provider() {
    let factory = WasmtimeComponentEngineFactory::new(support::config()).unwrap();
    let backend = factory.create_backend_instance();
    let artifact = support::artifact_bytes(component(), &[CONTRACT]);
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap();
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    for id in ["first-web", "second-web"] {
        let cancellation = support::Cancellation::new(id);
        let request = support::request(
            prepared.clone(),
            &cancellation.id,
            CONTRACT,
            "answer",
            b"[]",
            support::budget(),
        );
        assert_eq!(
            support::returned(
                support::run(&backend, request, &cancellation)
                    .await
                    .unwrap()
            ),
            serde_json::json!([42])
        );
        support::idle(&backend);
    }
}
