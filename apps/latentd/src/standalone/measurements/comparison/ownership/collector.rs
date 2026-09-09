use std::collections::BTreeMap;
use std::path::Path;
use std::time::Instant;

use latent_executor::ExecutionBackend;
use latent_wasmtime::{WasmtimeBackend, WasmtimeComponentEngineFactory};
use serde_json::{json, Value};

use super::{
    call, config, context, files,
    fixtures::{Artifact, ContextFile, Manifest},
    generation::Generated,
    observation,
    plan::{self, Mode, Plan},
    proof,
    request::{self, Control, Template},
    Result, Writer,
};

#[derive(Default)]
struct Work {
    preparations: u32,
    invocations: u32,
    proofs: u32,
    context_checks: u32,
}
impl Work {
    fn value(&self) -> Value {
        json!({"preparation_attempts":self.preparations.to_string(),
    "invoke_attempts":self.invocations.to_string(),"proof_attempts":self.proofs.to_string(),
    "context_validation_checks":self.context_checks.to_string()})
    }
}

pub(super) struct Completed {
    pub writer: Writer,
    pub footer: Value,
    pub generated: Option<Generated>,
    pub passed: bool,
}

pub(super) async fn run(
    plan: &Plan,
    identity: &Value,
    root: &Path,
    directory: &Path,
    input: &[u8],
    origin: Instant,
) -> Result<Completed> {
    let mut generated = if plan.mode == Mode::Fixtures {
        Some(super::generation::bootstrap(root, directory, input)?)
    } else {
        None
    };
    let manifest = if plan.mode == Mode::Fixtures {
        None
    } else {
        let manifest: Manifest = serde_json::from_slice(input)?;
        manifest.validate()?;
        Some(manifest)
    };
    let artifacts = generated.as_ref().map_or_else(
        || {
            manifest
                .as_ref()
                .expect("measured fixtures")
                .artifacts
                .clone()
        },
        |v| v.artifacts.clone(),
    );
    validate_identity(identity, &artifacts)?;
    let config = config::runtime();
    let factory = WasmtimeComponentEngineFactory::new(config).map_err(super::platform)?;
    let backend = factory.create_backend_instance();
    let observer = factory.invocation_input_observer();
    let compiler = factory.compiler_observer();
    let runtimes = factory.prepared_runtime_observer();
    let profile = factory.profile();
    let mut writer = Writer::named(
        directory,
        "ownership.json",
        512,
        &json!({
            "schema":"latent.optimization.ownership-arm.v1","plan":plan,"identity":identity,
            "fixture_manifest_sha256":latent_artifacts::content_digest(input).0,
            "process_id":std::process::id(),"runtime_workers":2,"observation_hold_millis":100,
            "engine_profile":{"id":profile.id,"wasmtime_version":profile.wasmtime_version,"target_triple":profile.target_triple,
                "cpu_feature_set":profile.cpu_feature_set,"pooling_allocator":profile.pooling_allocator,
                "copy_on_write_images":profile.copy_on_write_images,"async_support":profile.async_support,
                "fuel_enabled":profile.fuel_enabled,"epoch_interruption_enabled":profile.epoch_interruption_enabled,
                "configuration":profile.configuration},
            "configuration_debug":format!("{:?}",config::runtime()),"budget":observation::budget(&config::budget()),
            "boundaries":{"composition":"direct-wasmtime-factory","preparation":"explicit-before-invocation-population",
                "construction":"owned-request-and-boxed-backend-future","invoke":"poll-through-contained-report-and-future-drop",
                "backend_total_excludes":"outer-context-validation","reclamation":"two-actual-drop-spans-excluding-classification",
                "allocation_selection":"union-of-construction-and-poll-including-warmup","context_capacity":"logical-Rust-capacity-not-allocator-usable-size"},
            "initial_resources":observation::resources(backend.resource_snapshot()),"initial_cache":backend.cache_accounting_snapshot(),
            "initial_observer":observation::input(&observer,origin)?
        }),
    )?;
    let mut work = Work::default();
    let mut templates = BTreeMap::new();
    let mut checks = Vec::new();
    let result = async {
        let selected: Vec<&str> = match plan.mode {
            Mode::Fixtures => vec!["capabilities"],
            Mode::Normal => vec!["optimization", "capabilities", "generic"],
            Mode::Allocation => vec![plan::component(&plan.shapes[0])],
        };
        for id in selected {
            let row = artifacts
                .iter()
                .find(|v| v.id == id)
                .ok_or("ownership selected artifact missing")?;
            let template = prepare(
                &factory,
                &backend,
                row,
                root,
                &mut writer,
                &mut work,
                origin,
            )
            .await?;
            templates.insert(id.to_owned(), template);
        }
        if backend.resource_snapshot().stores_created != 0 {
            return Err("ownership preparation created Store".into());
        }
        if let Some(generated) = generated.as_mut() {
            let (contexts, probes) = context::generate(&backend, &templates["capabilities"])?;
            work.context_checks = u32::try_from(probes.len())?;
            checks = probes;
            for (value, charge) in contexts {
                let artifact = files::retain(
                    root,
                    &directory.join(format!("{}.json", value.shape)),
                    &serde_json::to_vec(&value)?,
                )?;
                generated.contexts.push(ContextFile {
                    shape: value.shape,
                    artifact,
                    charge,
                });
            }
        }
        super::ready(plan, identity, input, origin)?;
        tokio::time::sleep(std::time::Duration::from_millis(100)).await;
        if let Some(manifest) = manifest.as_ref() {
            normal(
                &backend,
                &templates,
                manifest,
                plan,
                root,
                &mut writer,
                &mut work,
                origin,
            )
            .await?;
            if plan.mode == Mode::Normal {
                observer
                    .enable(&[
                        request::identifier(work.invocations),
                        request::identifier(work.invocations + 1),
                    ])
                    .map_err(super::platform)?;
                for drop_pending in [false, true] {
                    let ordinal = work.invocations;
                    work.invocations += 1;
                    work.proofs += 1;
                    proof::run(
                        &backend,
                        &templates["generic"],
                        &observer,
                        ordinal,
                        drop_pending,
                        &mut writer,
                        origin,
                    )
                    .await?;
                }
            }
        }
        observation::idle(&backend)
    }
    .await;
    let before_shutdown = json!({"resources":observation::resources(backend.resource_snapshot()),
        "cache":backend.cache_accounting_snapshot(),"compiler":backend.compiler_snapshot(),
        "input":observation::input(&observer,origin)?});
    drop(templates);
    drop(backend);
    let shutdown_started = observation::elapsed(origin);
    let shutdown = factory.shutdown();
    let shutdown_finished = observation::elapsed(origin);
    let snapshot = observer.snapshot();
    let joined = compiler.snapshot();
    let zero = snapshot.live_invocations == 0
        && snapshot.live_raw_owners == 0
        && snapshot.live_raw_capacity_bytes == 0
        && !snapshot.overflowed
        && joined.workers_joined == 2
        && joined.workers_live == 0
        && !joined.failed
        && runtimes.snapshot().is_some_and(|v| v.live.runtimes == 0);
    let passed = result.is_ok() && shutdown.is_ok() && zero;
    let final_inputs = observation::input(&observer, origin)?;
    let footer = json!({"status":if passed {"passed"} else {"failed"},"reason":(!passed).then_some("ownership-collector-failed"),
        "elapsed_nanos":observation::elapsed(origin),"work":work.value(),"context_checks":checks,
        "before_factory_shutdown":before_shutdown,"factory_shutdown":{"succeeded":shutdown.is_ok(),
            "started_nanos":shutdown_started,"finished_nanos":shutdown_finished},
        "compiler_after_shutdown":joined,"prepared_runtimes_after_shutdown":runtimes.snapshot(),
        "raw_inputs_after_shutdown":final_inputs});
    Ok(Completed {
        writer,
        footer,
        generated,
        passed,
    })
}

async fn prepare(
    factory: &WasmtimeComponentEngineFactory,
    backend: &WasmtimeBackend,
    row: &Artifact,
    root: &Path,
    writer: &mut Writer,
    work: &mut Work,
    origin: Instant,
) -> Result<Template> {
    let artifact = row.load(root)?;
    let key = factory.preparation_key(artifact.descriptor.release_digest.clone());
    work.preparations += 1;
    let started = observation::elapsed(origin);
    let result = backend.prepare(&artifact, &key).await;
    let finished = observation::elapsed(origin);
    writer.sample(&json!({"kind":"prepare","fixture_id":row.id,"component":row.component,
        "capsule":row.capsule,"contracts":row.contracts,"started_nanos":started,"finished_nanos":finished,
        "status":if result.is_ok(){"passed"}else{"failed"},"cache":backend.cache_accounting_snapshot(),
        "resources":observation::resources(backend.resource_snapshot())}))?;
    let prepared = result.map_err(super::platform)?;
    let contract = match row.id.as_str() {
        "optimization" => "optimization:benchmark/workloads@0.1.0",
        "capabilities" => "tests:capabilities/api@0.1.0",
        "generic" => "tests:generic/values@0.1.0",
        _ => return Err("ownership fixture id".into()),
    };
    Ok(Template {
        fixture: row.id.clone(),
        tenant: artifact
            .manifest
            .metadata
            .tenant
            .as_ref()
            .ok_or("ownership fixture tenant")?
            .0
            .clone(),
        service: artifact.manifest.metadata.name.clone(),
        contract: contract.into(),
        imports: artifact
            .manifest
            .imports
            .iter()
            .map(|v| v.contract.0.clone())
            .collect(),
        prepared,
    })
}

async fn normal(
    backend: &WasmtimeBackend,
    templates: &BTreeMap<String, Template>,
    manifest: &Manifest,
    plan: &Plan,
    root: &Path,
    writer: &mut Writer,
    work: &mut Work,
    origin: Instant,
) -> Result<()> {
    for shape in &plan.shapes {
        let template = &templates[plan::component(shape)];
        let (context, payload) = if shape.starts_with("context-") {
            let (context, expected) = manifest.context(root, shape)?;
            let control = Control::new(request::identifier(0))?;
            let observed = backend
                .invocation_context_charge(&request::build(
                    template, &context, b"[]", &control, "snapshot",
                ))
                .map_err(super::platform)?;
            work.context_checks += 1;
            if context::charge(observed) != *expected
                || shape == "context-near-limit"
                    && !(512..=1024).contains(&observed.remaining_bytes)
            {
                return Err("ownership frozen context charge mismatch".into());
            }
            (context, b"[]".to_vec())
        } else {
            (context::Context::small(), manifest.payload(root, shape)?)
        };
        for iteration in 0..plan.count() {
            let ordinal = work.invocations;
            work.invocations += 1;
            let phase = if iteration < plan.warmup_per_shape {
                "warmup"
            } else {
                "measured"
            };
            call::run(
                backend,
                template,
                call::Case {
                    shape,
                    phase,
                    iteration,
                    ordinal,
                    context: &context,
                    payload: &payload,
                },
                writer,
                origin,
            )
            .await?;
        }
    }
    Ok(())
}

fn validate_identity(identity: &Value, artifacts: &[Artifact]) -> Result<()> {
    let fixtures = identity["fixtures"]
        .as_array()
        .ok_or("ownership fixture identities")?;
    if fixtures.len() != 3 {
        return Err("ownership identity fixture count".into());
    }
    for artifact in artifacts {
        let row = fixtures
            .iter()
            .find(|v| v["name"] == artifact.id)
            .ok_or("ownership identity fixture absent")?;
        if row["sha256"] != artifact.component.sha256 || row["bytes"] != artifact.component.bytes {
            return Err("ownership loaded fixture identity mismatch".into());
        }
    }
    Ok(())
}
