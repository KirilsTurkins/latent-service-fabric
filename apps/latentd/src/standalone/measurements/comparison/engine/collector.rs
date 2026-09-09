use super::super::super::{fixtures::Fixture, platform, runtime};
use super::{
    files, fixture, functional, observation,
    plan::Plan,
    publication, resources,
    sequence::{self, State},
    Clock, Node, Result, Writer,
};
use latent_artifacts::content_digest;
use latent_core::{DeadlineDiagnosticObserver, DeadlineWaitObserver};
use serde_json::{json, Value};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

struct Runtimes {
    invocation: tokio::runtime::Runtime,
    control: tokio::runtime::Runtime,
    client: tokio::runtime::Runtime,
}
struct Counts {
    node: crate::standalone::RuntimeThreads,
    client: Arc<AtomicUsize>,
}

struct Inputs {
    plan: Plan,
    plan_bytes: Vec<u8>,
    identity: Value,
    identity_bytes: Vec<u8>,
    fixture_bytes: Vec<u8>,
    root: PathBuf,
    directory: PathBuf,
}
impl Inputs {
    fn load() -> Result<Self> {
        let plan_path = files::required("LSF_PHASE1_COMPARISON_PLAN")?;
        let identity_path = files::required("LSF_PHASE1_COMPARISON_IDENTITY")?;
        let fixture_path = files::required("LSF_ENGINE_FIXTURES")?;
        let plan_bytes = files::read(&plan_path, 64 * 1024)?;
        let identity_bytes = files::read(&identity_path, 1024 * 1024)?;
        let fixture_bytes = files::read(&fixture_path, 1024 * 1024)?;
        let plan: Plan = serde_json::from_slice(&plan_bytes)?;
        plan.validate()?;
        let identity: Value = serde_json::from_slice(&identity_bytes)?;
        let root = fixture_path
            .parent()
            .ok_or("engine fixture root")?
            .canonicalize()?;
        let directory = files::required("LSF_PHASE1_COMPARISON_OUTPUT")?.canonicalize()?;
        if !directory.starts_with(&root) {
            return Err("engine output root".into());
        }
        Ok(Self {
            plan,
            plan_bytes,
            identity,
            identity_bytes,
            fixture_bytes,
            root,
            directory,
        })
    }

    fn emit_completion(&self, passed: bool) -> Result<()> {
        let raw = files::read(&self.directory.join("engine.json"), 32 * 1024 * 1024)?;
        files::emit(
            &json!({"schema":"latent.optimization.engine-complete.v1","event":"measurement-complete","process_id":std::process::id(),"plan_sha256":content_digest(&self.plan_bytes).0,"identity_sha256":content_digest(&self.identity_bytes).0,"raw":{"path":self.directory.join("engine.json").strip_prefix(&self.root)?.to_str().ok_or("engine raw path")?.replace('\\',"/"),"bytes":raw.len().to_string(),"sha256":content_digest(&raw).0},"outcome":if passed{"passed"}else{"failed"}}),
        )
    }
}
impl Counts {
    fn new() -> Self {
        Self {
            node: crate::standalone::RuntimeThreads::default(),
            client: Arc::new(AtomicUsize::new(0)),
        }
    }
    fn runtimes(&self) -> Runtimes {
        Runtimes {
            invocation: runtime(2, &self.node.invocation),
            control: runtime(4, &self.node.control),
            client: runtime(2, &self.client),
        }
    }
    fn snapshot(&self) -> Value {
        json!({"invocation":self.node.invocation.load(Ordering::Acquire),"control":self.node.control.load(Ordering::Acquire),"client":self.client.load(Ordering::Acquire)})
    }
}

pub(super) fn execute() -> Result<()> {
    let clock = Clock::new()?;
    let input = Inputs::load()?;
    let plan = &input.plan;
    let fixtures = fixture::load(&input.root, &input.fixture_bytes, &input.identity)?;
    let before = resources::capture("before-node", clock)?;
    let data = tempfile::Builder::new()
        .prefix("engine-comparison-owned-")
        .tempdir_in(files::required("LSF_PHASE1_COMPARISON_DATA_ROOT")?)?;
    let observing = diagnostic_clock(clock)?;
    let counts = Counts::new();
    let runtimes = counts.runtimes();
    let mut node = runtimes.invocation.block_on(Node::start_with_clock(
        plan.commands(),
        plan.configuration(data.path()),
        clone_fixture(&fixtures[0]),
        runtimes.control.handle().clone(),
        crate::standalone::RuntimeThreads {
            invocation: counts.node.invocation.clone(),
            control: counts.node.control.clone(),
        },
        clock.origin,
        observing.clone(),
    ))?;
    let preparation = node.owner.backend.preparation_observer();
    preparation.enable();
    let compiler = node
        .owner
        .factory
        .as_ref()
        .ok_or("engine factory missing")?
        .compiler_observer();
    let ledger = node.owner.backend.prepared_runtime_observer();
    let setup = runtimes.client.block_on(async {
        node.reconnect().await?;
        publication::publish(&mut node, fixtures, &input.directory, clock).await
    });
    let header = json!({"schema":"latent.optimization.engine-arm.v1","plan":plan,"identity":input.identity,
        "plan_sha256":content_digest(&input.plan_bytes).0,"identity_sha256":content_digest(&input.identity_bytes).0,"fixture_manifest_sha256":content_digest(&input.fixture_bytes).0,
        "configuration":node.config,"engine_profile":observation::profile(&node,plan)?,"effective_options":options(&node),"startup":node.startup,"clock":clock.record(),
        "before_node_memory":before,"fixtures":setup.as_ref().ok().map(|v|&v.fixtures),"configured_runtimes":{"invocation":2,"control":4,"client":2},
        "population":{"invokes":plan.offers().to_string(),"commands":plan.commands().to_string(),"functional_invokes":"24","functional_commands":"53","functional_guest_logs":"10"},
        "bounds":{"arm_seconds":"300","functional_seconds":"30","memory_checkpoints":"64","diagnostic_identities":"24","diagnostic_records":"1024"}});
    let mut writer = Writer::named(&input.directory, "engine.json", 2048, &header)?;
    let mut state = State::new(Vec::new());
    let result = match setup {
        Ok(setup) => {
            state.targets = setup.targets;
            for row in setup.commands {
                writer.sample(&row)?;
            }
            runtimes.client.block_on(async {
                tokio::time::timeout(
                    Duration::from_mins(5),
                    run(&mut node, &mut writer, &mut state, plan, &observing, clock),
                )
                .await
                .map_err(|_| {
                    Box::<dyn std::error::Error + Send + Sync>::from("engine arm watchdog")
                })?
            })
        }
        Err(error) => Err(error),
    };
    runtimes.client.block_on(state.abort_and_join())?;
    let drained = runtimes
        .client
        .block_on(super::super::cold::observation::drain(&preparation, clock));
    let before_shutdown = observation::checkpoint(&node, clock, "before-shutdown");
    let work = node.work;
    let shutdown = runtimes.invocation.block_on(Box::pin(node.shutdown()));
    let cleanup = data.close();
    drop(runtimes);
    let threads = counts.snapshot();
    let mut runtime_final = serde_json::to_value(ledger.snapshot())?;
    observation::decimals(&mut runtime_final);
    let mut compiler_final = serde_json::to_value(compiler.snapshot())?;
    observation::decimals(&mut compiler_final);
    let diagnostic = super::super::budget::observation::diagnostic(&observing.diagnostic, clock)?;
    let clean = shutdown.as_ref().is_ok_and(clean_shutdown)
        && cleanup.is_ok()
        && drained.is_ok()
        && threads == json!({"invocation":0,"control":0,"client":0});
    let passed = result.is_ok()
        && state.passed
        && clean
        && work.commands == plan.commands()
        && work.invoke_attempts == plan.offers()
        && !work.budget_exhausted
        && !observing.diagnostic.snapshot().overflowed
        && observing.diagnostic.snapshot().identities.len() == 24;
    let final_memory = resources::capture("after-shutdown", clock)?;
    writer.finish(&json!({"status":if passed{"passed"}else{"failed"},"reason":(!passed).then_some("engine-comparison-failed"),"work":work,"before_shutdown":before_shutdown.ok(),"shutdown":shutdown.ok(),"data_cleanup":{"removed":cleanup.is_ok()},"runtime_threads_after_join":threads,
        "final_preparation":super::super::cold::observation::snapshot(&preparation,clock)?,"final_compiler":compiler_final,"final_runtime_accounting":runtime_final,"final_diagnostic":diagnostic,"final_waits":super::super::budget::observation::waits(&observing.waits),"after_shutdown_memory":final_memory,"revision_pins":state.revisions,"functional_guest_logs":state.functional_logs.to_string(),"elapsed_nanos":clock.elapsed().to_string()}))?;
    input.emit_completion(passed)?;
    result?;
    if !passed {
        return Err("engine collector did not qualify".into());
    }
    Ok(())
}

fn diagnostic_clock(clock: Clock) -> Result<Arc<observation::ObservingClock>> {
    Ok(Arc::new(observation::ObservingClock {
        diagnostic: DeadlineDiagnosticObserver::with_limits(clock.origin, 24, 1024)
            .map_err(platform)?,
        waits: DeadlineWaitObserver::new(),
        enabled: AtomicBool::new(false),
    }))
}

fn clean_shutdown(value: &crate::standalone::ShutdownReport) -> bool {
    value.clean
        && value.telemetry_flushed
        && value.epoch_helper_joined
        && value.quarantined_cells == 0
        && value.cleanup.driver_joined
        && !value.cleanup.driver_alive
        && !value.cleanup.accepting
        && value.cleanup.reserved == 0
        && value.cleanup.queued == 0
        && value.cleanup.running == 0
        && !value.cleanup.failed
}

async fn run(
    node: &mut Node,
    writer: &mut Writer,
    state: &mut State,
    plan: &Plan,
    observing: &observation::ObservingClock,
    clock: Clock,
) -> Result<()> {
    writer.sample(&observation::checkpoint(node, clock, "empty")?)?;
    for (phase, target, warmup, measured, width) in plan.phases() {
        let template = sequence::ordinary(&state.targets[target], phase, 0, warmup, clock)?;
        population(
            node,
            writer,
            state,
            observing,
            clock,
            PhaseBatch {
                template: &template,
                first: 0,
                count: warmup,
                width,
            },
        )
        .await?;
        writer.sample(&observation::checkpoint(
            node,
            clock,
            &format!("{phase}-after-warmup"),
        )?)?;
        population(
            node,
            writer,
            state,
            observing,
            clock,
            PhaseBatch {
                template: &template,
                first: warmup,
                count: measured,
                width,
            },
        )
        .await?;
        writer.sample(&observation::checkpoint(
            node,
            clock,
            &format!("{phase}-after-measured"),
        )?)?;
    }
    observing.enabled.store(true, Ordering::Release);
    let result = tokio::time::timeout(
        Duration::from_secs(30),
        functional::run(state, node, clock, &observing.diagnostic, writer),
    )
    .await
    .map_err(|_| "engine functional watchdog")?;
    observing.enabled.store(false, Ordering::Release);
    result?;
    writer.sample(&observation::checkpoint(
        node,
        clock,
        "functional-after-drain",
    )?)?;
    Ok(())
}

#[derive(Clone, Copy)]
struct PhaseBatch<'a> {
    template: &'a super::call::Offer,
    first: u32,
    count: u32,
    width: u32,
}

async fn population(
    node: &mut Node,
    writer: &mut Writer,
    state: &mut State,
    observing: &observation::ObservingClock,
    clock: Clock,
    phase: PhaseBatch<'_>,
) -> Result<()> {
    let PhaseBatch {
        template,
        first,
        count,
        width,
    } = phase;
    let started = clock.elapsed();
    for base in (first..first + count).step_by(usize::try_from(width)?) {
        let mut batch = Vec::with_capacity(usize::try_from(width)?);
        for index in base..(base + width).min(first + count) {
            let mut offer = template.clone();
            offer.index = index;
            offer.id = format!("engine-{}-{index:04}", offer.phase);
            offer.phase_kind = if first == 0 { "warmup" } else { "measured" }.into();
            offer.scheduled = clock.elapsed();
            let slot = state.start(node, clock, offer.clone())?;
            batch.push((slot, offer));
        }
        for (slot, offer) in batch {
            state
                .finish(slot, node, clock, &offer, &observing.diagnostic, writer)
                .await?;
        }
    }
    writer.sample(&json!({"kind":"proof","label":"batch-window","phase":template.phase,"phase_kind":if first==0{"warmup"}else{"measured"},"first_index":first.to_string(),"count":count.to_string(),"width":width.to_string(),"started_nanos":started.to_string(),"finished_nanos":clock.elapsed().to_string(),"scope":"invoke-status-validation-and-retention"}))
}
fn clone_fixture(value: &Fixture) -> Fixture {
    Fixture {
        artifact: value.artifact.clone(),
        deployment: value.deployment.clone(),
        tenant: value.tenant.clone(),
        service: value.service.clone(),
        contract: value.contract.clone(),
        release_digest: value.release_digest.clone(),
        target: value.target.clone(),
    }
}

fn options(node: &Node) -> Value {
    let mut value = super::super::evidence::options(node);
    value["pool_capacity"] = json!("4");
    value["queue_capacity"] = json!("64");
    value["control_workers"] = json!("4");
    value
}
