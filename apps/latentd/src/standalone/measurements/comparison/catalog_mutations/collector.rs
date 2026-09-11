use std::sync::{atomic::Ordering, Arc};
use std::time::Duration;

use latent_control_store::{CatalogWorkObserver, CatalogWorkOperation, CatalogWorkSnapshot};
use latent_routing::RouteResolver;
use serde_json::{json, Value};

use super::super::{
    catalog::{files, fixture, sampler::Sampler},
    node::observed::ObservedStart,
};
use super::{
    files::Inputs,
    observation::{self, Counts},
    sequence, Clock, Node, Result, Writer,
};
use crate::standalone::{
    measurements::{fixtures::Fixture, runtime},
    RuntimeThreads,
};

struct Session {
    input: Inputs,
    clock: Clock,
    node: Node,
    writer: Writer,
    sampler: Option<Sampler>,
    observer: CatalogWorkObserver,
    threads: RuntimeThreads,
    invocation: tokio::runtime::Runtime,
    control: tokio::runtime::Runtime,
}

pub(super) fn execute() -> Result<()> {
    if !cfg!(target_os = "linux") {
        return Err("catalog mutation collector requires Linux".into());
    }
    let clock = Clock::new()?;
    let input = Inputs::load()?;
    let fixture = Fixture::echo()?;
    let template = fixture::template(&fixture)?;
    input.ready(clock)?;
    std::thread::sleep(Duration::from_millis(100));
    let mut sampler = if input.plan.profiled() {
        None
    } else {
        Some(Sampler::start_for_mode(
            &input.directory,
            input.plan.reopen(),
            clock,
        )?)
    };
    let before = super::super::engine::resources::capture("before-node", clock)?;
    let threads = RuntimeThreads::default();
    let invocation = runtime(2, &threads.invocation);
    let control = runtime(1, &threads.control);
    let observer = CatalogWorkObserver::new();
    let (node, opening) = invocation.block_on(
        ObservedStart {
            maximum_commands: input.plan.commands(),
            config: input.plan.configuration(&input.data),
            fixture,
            control: control.handle().clone(),
            threads: RuntimeThreads {
                invocation: threads.invocation.clone(),
                control: threads.control.clone(),
            },
            clock,
            observer: observer.clone(),
            profile_reopen: input.plan.mode == "allocation-reopen",
        }
        .start(),
    )?;
    node.owner.backend.preparation_observer().enable();
    let header = header(&node, &input, clock, template, before, opening)?;
    let writer = match Writer::named(&input.directory, "catalog-mutations.json", 2048, &header) {
        Ok(writer) => writer,
        Err(error) => {
            if let Some(sampler) = sampler.as_mut() {
                let _ = sampler.finish();
            }
            let _ = invocation.block_on(Box::pin(node.shutdown()));
            drop(control);
            drop(invocation);
            return Err(error);
        }
    };
    Session {
        input,
        clock,
        node,
        writer,
        sampler,
        observer,
        threads,
        invocation,
        control,
    }
    .run()
}

fn header(
    node: &Node,
    input: &Inputs,
    clock: Clock,
    template: Value,
    before: Value,
    opening: Value,
) -> Result<Value> {
    let profile = node
        .owner
        .factory
        .as_ref()
        .ok_or("mutation factory missing")?
        .profile();
    let mut value = json!({"schema":"latent.optimization.catalog-mutation-arm.v1","plan":input.plan,"identity":input.identity,
        "plan_sha256":input.plan_sha256,"identity_sha256":input.identity_sha256,"fixture_template":null,
        "configuration":node.config,"startup":node.startup,"clock":clock.record(),"opening":null,
        "data_identity":input.data_identity,"reopen_receipt":input.reopen,"population":input.plan.population(),
        "bounds":{"arm_seconds":input.plan.seconds().to_string(),"raw_bytes":"33554432","raw_records":"2048",
            "raw_record_bytes":"262144","publication_chunk":"256"},"configured_runtimes":{"invocation":2,"control":1},
        "before_node_memory":null,"effective_engine":{"id":profile.id,"wasmtime_version":profile.wasmtime_version,
            "pooling_allocator":profile.pooling_allocator,"configuration":profile.configuration}});
    value["fixture_template"] = template;
    value["opening"] = opening;
    value["before_node_memory"] = before;
    Ok(value)
}

impl Session {
    fn run(mut self) -> Result<()> {
        let mut counts = Counts::default();
        let expected = if self.input.plan.reopen() { 5 } else { 0 };
        let opening = observation::associated(
            &CatalogWorkSnapshot::default(),
            &self.observer.snapshot(),
            CatalogWorkOperation::Open,
            expected,
        );
        let result = if self.node.deployments.generation().0 != expected {
            Err("mutation initial generation differs".into())
        } else if let Err(error) = opening {
            Err(error)
        } else {
            self.control.block_on(async {
                tokio::time::timeout(
                    Duration::from_secs(self.input.plan.seconds()),
                    sequence::run(
                        &mut self.node,
                        &mut self.writer,
                        &mut counts,
                        &self.input.plan,
                        self.clock,
                        &self.observer,
                    ),
                )
                .await
                .map_err(|_| {
                    Box::<dyn std::error::Error + Send + Sync>::from("mutation source watchdog")
                })?
            })
        };
        self.finish(result, &counts)
    }

    fn finish(mut self, result: Result<()>, counts: &Counts) -> Result<()> {
        let artifacts = Arc::downgrade(&self.node.artifacts);
        let deployments = Arc::downgrade(&self.node.deployments);
        let preparation = self.node.owner.backend.preparation_observer();
        let compiler = self
            .node
            .owner
            .factory
            .as_ref()
            .ok_or("mutation final factory missing")?
            .compiler_observer();
        let ledger = self.node.owner.backend.prepared_runtime_observer();
        let final_verification = observation::verification(&self.node);
        let checkpoint = observation::checkpoint(
            &self.node,
            &mut self.writer,
            self.clock,
            "before-shutdown",
            self.input.plan.populated_size,
            false,
        );
        let sampler = self.sampler.as_mut().map_or_else(
            || Ok(json!({"enabled":false,"reason":"allocation-mode"})),
            Sampler::finish,
        );
        let work = self.node.work;
        let population = counts.complete(&self.input.plan, work.commands);
        let drained = self
            .invocation
            .block_on(super::super::cold::observation::drain(
                &preparation,
                self.clock,
            ));
        let shutdown = self.invocation.block_on(Box::pin(self.node.shutdown()));
        drop(self.control);
        drop(self.invocation);
        let threads = json!({"invocation":self.threads.invocation.load(Ordering::Acquire),"control":self.threads.control.load(Ordering::Acquire)});
        let owners = json!({"artifacts":artifacts.strong_count()==0,"deployments":deployments.strong_count()==0});
        let data_after = files::data_identity(&self.input.data)?;
        let observed = self.observer.snapshot();
        let passed = result.is_ok()
            && final_verification.is_ok()
            && checkpoint.is_ok()
            && sampler.is_ok()
            && population.is_ok()
            && drained.is_ok()
            && shutdown.as_ref().is_ok_and(clean_shutdown)
            && threads == json!({"invocation":0,"control":0})
            && owners == json!({"artifacts":true,"deployments":true})
            && data_after == self.input.data_identity
            && work.commands == self.input.plan.commands()
            && work.invoke_attempts == 0
            && !work.budget_exhausted
            && !observed.overflowed
            && !observed.poisoned
            && observed.active == 0
            && observed.started == observed.finished
            && self.clock.elapsed() < u128::from(self.input.plan.seconds()) * 1_000_000_000;
        let mut final_compiler = serde_json::to_value(compiler.snapshot())?;
        observation::decimals(&mut final_compiler);
        let mut final_runtime = serde_json::to_value(ledger.snapshot())?;
        observation::decimals(&mut final_runtime);
        let final_preparation =
            super::super::cold::observation::snapshot(&preparation, self.clock)?;
        let memory = super::super::engine::resources::capture("after-shutdown", self.clock)?;
        self.writer.finish(&json!({"status":if passed{"passed"}else{"failed"},"reason":(!passed).then_some("catalog-mutation-comparison-failed"),
            "work":work,"operations":counts.snapshot(),"shutdown":shutdown.ok(),"runtime_threads_after_join":threads,
            "catalog_owners_released":owners,"data_identity_after_shutdown":data_after,
            "final_preparation":final_preparation,"final_compiler":final_compiler,
            "final_runtime_accounting":final_runtime,"final_verification":final_verification.ok(),"final_catalog_work":observation::project(&observed)?,
            "sampler":sampler.ok(),"after_shutdown_memory":memory,"elapsed_nanos":self.clock.elapsed().to_string()}))?;
        self.input.complete(passed, self.clock)?;
        std::thread::sleep(Duration::from_millis(100));
        result?;
        if !passed {
            return Err("catalog mutation collector did not qualify".into());
        }
        Ok(())
    }
}

fn clean_shutdown(value: &crate::standalone::ShutdownReport) -> bool {
    value.clean
        && value.telemetry_flushed
        && value.epoch_helper_joined
        && value.cleanup.driver_joined
        && !value.cleanup.driver_alive
        && !value.cleanup.accepting
        && value.cleanup.reserved == 0
        && value.cleanup.queued == 0
        && value.cleanup.running == 0
        && !value.cleanup.failed
}
