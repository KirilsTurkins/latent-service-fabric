//! Finite public scheduler measurements. No guest execution or worker tasks.

pub(in crate::local) mod fixture;
mod input;
mod load;
mod offer;
mod output;
mod storm;
mod validation;

use std::future::Future;
use std::pin::Pin;
use std::task::{Context, Poll};
use std::time::{Duration, Instant};

use serde_json::{json, Value};

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

fn platform(error: latent_core::PlatformError) -> Box<dyn std::error::Error> {
    let message = format!("scheduler fixture platform error: {error:?}");
    drop(error);
    message.into()
}

const FRAME: &str = "latent_scheduler::local::measurement::measured_cancel_and_settle";

#[derive(Clone, Copy)]
struct Clock(Instant);

impl Clock {
    fn now(self) -> u64 {
        self.offset(Instant::now())
    }
    fn offset(self, value: Instant) -> u64 {
        u64::try_from(
            value
                .checked_duration_since(self.0)
                .expect("same monotonic origin")
                .as_nanos(),
        )
        .expect("finite scheduler observation")
    }
    fn at(self, nanos: u64) -> Instant {
        self.0 + Duration::from_nanos(nanos)
    }
}

struct Run {
    rows: Vec<offer::Row>,
    checkpoints: Vec<Value>,
    started: u64,
    finished: u64,
    frame: Value,
}

impl Run {
    fn checkpoint(&mut self, fixture: &fixture::Fixture, label: &str, clock: Clock) -> Result<()> {
        if self.checkpoints.len() >= 128 {
            return Err("scheduler checkpoint bound".into());
        }
        self.checkpoints
            .push(output::checkpoint(fixture, label, clock)?);
        Ok(())
    }
}

/// One actual poll of the original cancellation/settlement future. The caller
/// records poll counts and clocks; JSON, fixture construction and checks stay outside.
#[inline(never)]
fn measured_cancel_and_settle(
    future: &mut Pin<Box<dyn Future<Output = ()> + '_>>,
    context: &mut Context<'_>,
) -> Poll<()> {
    let result = std::hint::black_box(future).as_mut().poll(context);
    std::hint::black_box(result)
}

#[test]
#[ignore = "explicit bounded scheduler measurement only"]
fn phase1_scheduler_collector() {
    collect().expect("scheduler collector; retained raw describes failed work");
}

fn collect() -> Result<()> {
    let clock = Clock(Instant::now());
    let input = input::Input::load()?;
    let settings = input.plan.settings()?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let fixture = fixture::Fixture::new(settings.tenants, settings.queue_capacity)?;
    let mut run = Run {
        rows: Vec::with_capacity(usize::try_from(
            settings.measured_offers + settings.warmup_offers,
        )?),
        checkpoints: Vec::with_capacity(80),
        started: 0,
        finished: 0,
        frame: Value::Null,
    };
    run.checkpoint(&fixture, "ready", clock)?;
    output::emit(&output::event(&input, clock, false))?;
    std::thread::sleep(Duration::from_millis(100));
    let result = runtime.block_on(async {
        if input.plan.storm() {
            storm::execute(&fixture, &settings, clock, &mut run).await
        } else {
            load::execute(&fixture, &settings, clock, &mut run).await
        }
    });
    fixture
        .scheduler
        .reset_work(crate::CellClass::Standard, false);
    fixture.scheduler.shutdown();
    let idle = fixture.idle();
    run.checkpoint(&fixture, "shutdown", clock)?;
    run.rows.sort_unstable_by_key(|row| row.ordinal);
    let failure = result
        .err()
        .or_else(|| idle.err())
        .map(|error| error.to_string());
    let failure = failure.or_else(|| {
        validation::validate(&input.plan, &settings, &run)
            .err()
            .map(|error| error.to_string())
    });
    drop(fixture);
    drop(runtime);
    let outcome = if failure.is_none() {
        "passed"
    } else {
        "failed"
    };
    let raw = json!({
        "schema":"latent.optimization.scheduler-arm.v1", "plan":input.plan,"identity":input.identity,
        "process_id":std::process::id(),"plan_sha256":input.plan_sha256,"identity_sha256":input.identity_sha256,
        "settings":settings, "started_nanos":run.started.to_string(),"finished_nanos":run.finished.to_string(),
        "elapsed_nanos":clock.now().to_string(), "outcome":outcome,"failure":failure,
        "counts":output::counts(&run.rows,1),"rows":run.rows.iter().map(output::row).collect::<Vec<_>>(),
        "checkpoints":run.checkpoints,"frame":run.frame,
        "runtime_dropped":true,"fixture_dropped":true,"invokes":"0",
    });
    let bytes = serde_json::to_vec(&raw)?;
    input::write_new(&input.output.join("scheduler.json"), &bytes)?;
    let mut complete = output::event(&input, clock, true);
    complete["outcome"] = json!(outcome);
    complete["raw"] = json!({"path":"scheduler.json","bytes":bytes.len().to_string(),"sha256":input::sha256(&bytes)});
    output::emit(&complete)?;
    std::thread::sleep(Duration::from_millis(100));
    if outcome != "passed" {
        return Err("scheduler work failed; original raw retained".into());
    }
    Ok(())
}
