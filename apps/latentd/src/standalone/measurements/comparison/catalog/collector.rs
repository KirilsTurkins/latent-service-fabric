use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;

use latent_routing::RouteResolver;
use serde_json::json;

use super::{
    files::{self, Inputs},
    fixture,
    observation::{self, Counts},
    sampler::Sampler,
    sequence, Clock, Node, Result, Writer,
};
use crate::standalone::measurements::{fixtures::Fixture, runtime};

#[expect(
    clippy::too_many_lines,
    reason = "one ordered owner chain records all failures before joining the node, observers and runtimes"
)]
pub(super) fn execute() -> Result<()> {
    if !cfg!(target_os = "linux") {
        return Err("catalog collector requires Linux".into());
    }
    let clock = Clock::new()?;
    let input = Inputs::load()?;
    let plan = &input.plan;
    let fixture = Fixture::echo()?;
    let template = fixture::template(&fixture)?;
    input.ready(clock)?;
    std::thread::sleep(Duration::from_millis(100));
    let mut sampler = if plan.mode == "allocation" {
        None
    } else {
        Some(Sampler::start(&input.directory, plan, clock)?)
    };
    let before = super::super::engine::resources::capture("before-node", clock)?;
    let threads = crate::standalone::RuntimeThreads::default();
    let invocation = runtime(2, &threads.invocation);
    let control = runtime(1, &threads.control);
    let mut node = invocation.block_on(Node::start_configured(
        plan.commands(),
        plan.configuration(&input.data),
        fixture,
        control.handle().clone(),
        crate::standalone::RuntimeThreads {
            invocation: threads.invocation.clone(),
            control: threads.control.clone(),
        },
        clock.origin,
    ))?;
    let artifacts = Arc::downgrade(&node.artifacts);
    let deployments = Arc::downgrade(&node.deployments);
    let preparation = node.owner.backend.preparation_observer();
    preparation.enable();
    let factory = node
        .owner
        .factory
        .as_ref()
        .ok_or("catalog factory missing")?;
    let compiler = factory.compiler_observer();
    let ledger = node.owner.backend.prepared_runtime_observer();
    let profile = factory.profile();
    let header = json!({"schema":"latent.optimization.catalog-arm.v1","plan":plan,"identity":input.identity,
        "plan_sha256":input.plan_sha256,"identity_sha256":input.identity_sha256,"fixture_template":template,
        "configuration":node.config,"startup":node.startup,"clock":clock.record(),
        "data_identity":input.data_identity,"reopen_receipt":input.reopen,"population":plan.population(),
        "bounds":{"arm_seconds":plan.seconds().to_string(),"raw_bytes":"33554432","raw_records":"2048",
            "raw_record_bytes":"262144","publication_chunk":"256","resolve_chunk":"128"},
        "configured_runtimes":{"invocation":2,"control":1},"before_node_memory":before,
        "effective_engine":{"id":profile.id,"wasmtime_version":profile.wasmtime_version,
            "pooling_allocator":profile.pooling_allocator,"configuration":profile.configuration}});
    let mut writer = match Writer::named(&input.directory, "catalog.json", 2048, &header) {
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
    let mut counts = Counts::default();
    let initial_generation = node.deployments.generation().0;
    let expected_generation = if plan.mode == "reopen" {
        plan.scales().len() as u64 + 1
    } else {
        0
    };
    let result = if initial_generation == expected_generation {
        control.block_on(async {
            tokio::time::timeout(
                Duration::from_secs(plan.seconds()),
                sequence::run(&mut node, &mut writer, &mut counts, plan, clock),
            )
            .await
            .map_err(|_| {
                Box::<dyn std::error::Error + Send + Sync>::from("catalog source watchdog")
            })?
        })
    } else {
        Err("catalog initial generation differs".into())
    };
    let final_verification = observation::verification(&node);
    let before_shutdown = observation::checkpoint(
        &node,
        &mut writer,
        clock,
        "before-shutdown",
        plan.count(),
        false,
    );
    let sampling_receipt = sampler.as_mut().map_or_else(
        || Ok(json!({"enabled":false,"reason":"allocation-mode"})),
        Sampler::finish,
    );
    let work = node.work;
    let populations = counts.complete(&plan.population(), work.commands);
    let drained = invocation.block_on(super::super::cold::observation::drain(&preparation, clock));
    let shutdown = invocation.block_on(Box::pin(node.shutdown()));
    drop(control);
    drop(invocation);
    let joined_threads = json!({"invocation":threads.invocation.load(Ordering::Acquire),
        "control":threads.control.load(Ordering::Acquire)});
    let mut final_compiler = serde_json::to_value(compiler.snapshot())?;
    let mut final_runtime = serde_json::to_value(ledger.snapshot())?;
    observation::decimals(&mut final_compiler);
    observation::decimals(&mut final_runtime);
    let owners = json!({"artifacts":artifacts.strong_count()==0,"deployments":deployments.strong_count()==0});
    let data_after = files::data_identity(&input.data)?;
    let passed = result.is_ok()
        && final_verification.is_ok()
        && before_shutdown.is_ok()
        && sampling_receipt.is_ok()
        && populations.is_ok()
        && drained.is_ok()
        && shutdown.as_ref().is_ok_and(clean_shutdown)
        && joined_threads == json!({"invocation":0,"control":0})
        && owners == json!({"artifacts":true,"deployments":true})
        && data_after == input.data_identity
        && work.commands == plan.commands()
        && work.invoke_attempts == 0
        && !work.budget_exhausted
        && clock.elapsed() < u128::from(plan.seconds()) * 1_000_000_000;
    writer.finish(&json!({"status":if passed{"passed"}else{"failed"},"reason":(!passed).then_some("catalog-comparison-failed"),
        "work":work,"operations":counts.snapshot(),"shutdown":shutdown.ok(),"runtime_threads_after_join":joined_threads,
        "catalog_owners_released":owners,"data_identity_after_shutdown":data_after,
        "final_preparation":super::super::cold::observation::snapshot(&preparation,clock)?,
        "final_compiler":final_compiler,"final_runtime_accounting":final_runtime,
        "final_verification":final_verification.ok(),"sampler":sampling_receipt.ok(),
        "after_shutdown_memory":super::super::engine::resources::capture("after-shutdown",clock)?,
        "elapsed_nanos":clock.elapsed().to_string()}))?;
    input.complete(passed, clock)?;
    std::thread::sleep(Duration::from_millis(100));
    result?;
    if !passed {
        return Err("catalog collector did not qualify".into());
    }
    Ok(())
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
