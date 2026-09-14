use super::{fixture::*, package_fixture};
use crate::{
    bindings::{BindingLimits, ConfiguredBindingProvider},
    DeploymentStore,
};
use latent_artifacts::package::artifact_blob_digest;
use latent_capabilities::broker::CapabilityPlanSource;
use latent_core::{DeploymentId, ServiceId, TenantId};
use latent_manifest::BindingMode;
use latent_routing::RouteResolver;
use serde_json::json;
mod fence;

pub(super) fn package() -> latent_packaging::PackageBundle {
    use wasm_encoder::*;
    let mut module = Module::new();
    let mut types = TypeSection::new();
    types.ty().function([], [ValType::I64]);
    module.section(&types);
    let mut functions = FunctionSection::new();
    functions.function(0);
    module.section(&functions);
    let mut exports = ExportSection::new();
    exports.export("clock", ExportKind::Func, 0);
    module.section(&exports);
    let mut function = Function::new([]);
    function.instruction(&Instruction::I64Const(1));
    function.instruction(&Instruction::End);
    let mut code = CodeSection::new();
    code.function(&function);
    module.section(&code);
    let mut component = Component::new();
    component.section(&ModuleSection(&module));
    let mut instances = InstanceSection::new();
    instances.instantiate(0, [] as [(&str, ModuleArg); 0]);
    component.section(&instances);
    let mut types = ComponentTypeSection::new();
    types
        .function()
        .params([] as [(&str, ComponentValType); 0])
        .result(Some(PrimitiveValType::U64.into()));
    component.section(&types);
    let mut aliases = ComponentAliasSection::new();
    aliases.alias(Alias::CoreInstanceExport {
        instance: 0,
        kind: ExportKind::Func,
        name: "clock",
    });
    component.section(&aliases);
    let mut canonical = CanonicalFunctionSection::new();
    canonical.lift(0, 0, []);
    component.section(&canonical);
    let mut instance = ComponentInstanceSection::new();
    instance.export_items([("now-nanos", ComponentExportKind::Func, 0)]);
    component.section(&instance);
    let mut exports = ComponentExportSection::new();
    exports.export(
        package_fixture::component::CLOCK,
        ComponentExportKind::Instance,
        0,
        None,
    );
    component.section(&exports);
    let bytes = component.finish();
    let service =
        b"package tests:packaging@1.0.0; world service { export latent:clock/monotonic@0.1.0; }";
    let mut interface = json!({"id":package_fixture::component::CLOCK,"functions":[{"id":"now-nanos","name":"now-nanos","asynchronous":false,"parameters":[],"results":[{"name":"result","value_type":"U64","documentation":null}],"documentation":null,"attributes":{}}],"documentation":null});
    interface["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&interface).unwrap()).as_str());
    let mut contract = json!({"id":package_fixture::component::CLOCK,"package_name":"latent:clock","semantic_version":"0.1.0","interfaces":[interface],"dependencies":[]});
    contract["digest"] =
        json!(artifact_blob_digest(&serde_json::to_vec(&contract).unwrap()).as_str());
    let contracts =
        serde_json::to_vec(&json!({"format_version":1,"contracts":[contract]})).unwrap();
    let mut input = package_fixture::capsule(Default::default());
    for layer in &mut input.layers {
        match layer.path.as_str() {
            "component.wasm" => layer.bytes.clone_from(&bytes),
            "wit/service.wit" => layer.bytes = service.to_vec(),
            "contracts.json" => layer.bytes.clone_from(&contracts),
            _ => (),
        }
    }
    package_fixture::mutate_json(&mut input, "capsule.json", |m| {
        m["metadata"]["name"] = json!("clock-host");
        m["metadata"].as_object_mut().unwrap().remove("tenant");
        m["component"]["digest"] = json!(artifact_blob_digest(&bytes).as_str());
        m["imports"] = json!([]);
        m["exports"] = json!([package_fixture::component::CLOCK]);
    });
    package_fixture::mutate_json(&mut input, "wit-lock.json", |lock| {
        lock["contractsDigest"] = json!(artifact_blob_digest(&contracts).as_str());
        lock["packages"][1]["digest"] = json!(artifact_blob_digest(service).as_str());
    });
    {
        use latent_manifest::{ManifestCodec, ManifestValidator};
        let m = latent_manifest::JsonManifestCodec::default()
            .decode_capsule(
                &input
                    .layers
                    .iter()
                    .find(|l| l.path == "capsule.json")
                    .unwrap()
                    .bytes,
            )
            .unwrap();
        latent_manifest::Phase1ManifestValidator
            .validate_capsule(&m)
            .unwrap();
    }
    latent_packaging::build_package(input, Default::default()).unwrap()
}
pub(super) fn install(f: &Fixture) {
    let mut d = definition();
    d.manifest.mode = BindingMode::IsolatedLocal;
    d.manifest.provider.service = ServiceId("clock-host".into());
    d.allowed_modes = vec![BindingMode::IsolatedLocal];
    let current = f.store.read_publication();
    let prepared = run(f.store.prepare_binding_update(
        current.routes.generation,
        current.transaction,
        vec![d],
        f.broker.clone(),
        vec![ConfiguredBindingProvider {
            tenant: TenantId("tests".into()),
            service: ServiceId("clock-host".into()),
            reference: f.provider.reference(),
            local_deployment: Some(DeploymentId("clock-provider".into())),
        }],
        BindingLimits::default(),
    ))
    .unwrap();
    f.store.commit_binding_update(prepared).unwrap();
}
#[test]
fn local_provider_revision_change_denies_old_plan_and_retains_desired_history() {
    let f = Fixture::with_local();
    install(&f);
    let pinned = f.store.pin().unwrap();
    let consumer = pinned.resolve(&target(), None).unwrap();
    let plan = f.store.plan(&consumer).unwrap();
    let record = f
        .store
        .read_catalog()
        .record_by_id(&DeploymentId("clock-provider".into()))
        .unwrap()
        .clone();
    let mut replacement = (*record.deployment).clone();
    replacement.resources.cpu_fuel += 1;
    run(f.store.apply(replacement)).unwrap();
    assert!(plan.check_eligible().is_err());
    assert!(f.store.plan(&consumer).is_err());
    assert_eq!(f.store.binding_definitions().unwrap().len(), 1);
    let next = f.store.pin().unwrap().resolve(&target(), None).unwrap();
    assert!(f.store.plan(&next).is_ok());
}
#[test]
fn local_publication_revocation_is_independent_of_consumer_admission() {
    use latent_artifacts::*;
    let f = Fixture::with_local();
    install(&f);
    // The injected publisher authority rejects recursive fence acquisition.
    assert!(fence::admit(&f).is_ok());
    let consumer = f.store.pin().unwrap().resolve(&target(), None).unwrap();
    let plan = f.store.plan(&consumer).unwrap();
    let record = f
        .store
        .read_catalog()
        .record_by_id(&DeploymentId("clock-provider".into()))
        .unwrap()
        .clone();
    let publication = record
        .publication_reference(f.releases.as_ref())
        .unwrap()
        .unwrap();
    f.releases
        .change_publication_lifecycle(
            ReleaseMutationContext {
                scope: LifecycleScope::Tenant(TenantId("tests".into())),
                actor: ReleaseActor {
                    subject: "operator".into(),
                    kind: ReleaseActorKind::Host,
                },
                operation: Some(ReleaseOperationPrecondition {
                    operation_id: "revoke-provider".into(),
                    expected_generation: 1,
                }),
            },
            &PublicationSelector::Publication(publication),
            ReleaseLifecycleAction::Revoke,
            ReleaseLifecycleReason::OperatorRevocation,
            &mut |_| Ok(()),
        )
        .unwrap();
    assert!(plan.check_eligible().is_err());
    assert!(fence::admit(&f).is_err());
    assert!(f.store.resolve(&target(), None).is_ok());
    assert_eq!(f.store.binding_definitions().unwrap().len(), 1);
}
