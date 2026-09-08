use std::io::Read;
use std::process::{Child, Command, Stdio};
use std::time::Instant;

use super::*;

const CHILD_SCENARIO: &str = "LSF_WASMTIME_EPOCH_TEST";
const COMPLETED: &str = "epoch-scenario-completed";

struct SupervisedChild(Child);

impl Drop for SupervisedChild {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

// A regressed blocking join must fail a tiny test rather than hang the suite.
fn supervise(name: &str, scenario: fn()) {
    if std::env::var(CHILD_SCENARIO).as_deref() == Ok(name) {
        scenario();
        println!("{COMPLETED}");
        return;
    }
    let mut child = SupervisedChild(
        Command::new(std::env::current_exe().expect("test executable"))
            .args(["--exact", name, "--nocapture", "--test-threads=1"])
            .env(CHILD_SCENARIO, name)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("start supervised epoch scenario"),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    let status = loop {
        if let Some(status) = child.0.try_wait().expect("poll epoch scenario") {
            break status;
        }
        assert!(
            Instant::now() < deadline,
            "epoch scenario exceeded five seconds: {name}"
        );
        std::thread::sleep(Duration::from_millis(10));
    };
    let mut output = String::new();
    child
        .0
        .stdout
        .take()
        .expect("scenario output")
        .take(64 * 1024)
        .read_to_string(&mut output)
        .expect("read bounded scenario output");
    assert!(status.success(), "epoch scenario failed: {name}\n{output}");
    assert!(
        output.contains(COMPLETED),
        "exact child scenario was not executed: {output}"
    );
}

fn wait_for_tick(observation: &crate::containment::EpochObservation, previous: u64) {
    let deadline = Instant::now() + Duration::from_secs(1);
    while observation.ticks() <= previous {
        assert!(
            !observation.completed(),
            "a live runtime owner must retain its worker"
        );
        assert!(
            Instant::now() < deadline,
            "worker did not advance the engine epoch"
        );
        std::thread::sleep(Duration::from_millis(1));
    }
}

#[test]
fn explicit_ticker_stop_wakes_a_long_interval_and_is_idempotent() {
    supervise(
        "factory::tests::explicit_ticker_stop_wakes_a_long_interval_and_is_idempotent",
        || {
            let engine = Engine::default();
            let mut ticker =
                EpochTicker::start(&engine, Duration::from_secs(3600)).expect("one helper");
            let observation = ticker.observation();
            ticker.stop_and_join().expect("wake and join immediately");
            assert!(observation.completed());
            ticker.stop_and_join().expect("already joined is harmless");
            drop(ticker);
            assert!(
                engine.weak().upgrade().is_some(),
                "engine remains alive after joined stop"
            );
        },
    );
}

#[test]
fn repeated_ticker_drop_joins_every_worker() {
    supervise(
        "factory::tests::repeated_ticker_drop_joins_every_worker",
        || {
            let engine = Engine::default();
            for _ in 0..3 {
                let ticker = EpochTicker::start(&engine, Duration::from_secs(3600))
                    .expect("one helper at a time");
                let observation = ticker.observation();
                drop(ticker);
                assert!(observation.completed(), "Drop must join before returning");
            }
            assert!(engine.weak().upgrade().is_some());
        },
    );
}

#[test]
fn unique_factory_shutdown_joins_with_an_engine_reference_still_alive() {
    supervise(
        "factory::tests::unique_factory_shutdown_joins_with_an_engine_reference_still_alive",
        || {
            let factory =
                WasmtimeComponentEngineFactory::new(WasmtimeConfig::default()).expect("factory");
            let observation = factory.shared.epoch_observation();
            let engine = factory.engine.clone();
            factory.shutdown().expect("unique runtime can shut down");
            assert!(observation.completed());
            assert!(
                engine.weak().upgrade().is_some(),
                "shutdown cannot depend on engine expiry"
            );
        },
    );
}

#[test]
fn busy_shutdown_preserves_backend_epoch_progress_until_last_owner_drop() {
    supervise(
        "factory::tests::busy_shutdown_preserves_backend_epoch_progress_until_last_owner_drop",
        || {
            let factory =
                WasmtimeComponentEngineFactory::new(WasmtimeConfig::default()).expect("factory");
            let observation = factory.shared.epoch_observation();
            let first = factory.create_backend_instance();
            let last = factory.create_backend_instance();
            let failure = factory
                .shutdown()
                .expect_err("live backends reject shutdown");
            assert_eq!(failure.code, PlatformErrorCode::Unavailable);
            assert_eq!(failure.message, "wasmtime-runtime-still-owned");
            assert!(!failure.retryable, "consumed factory cannot be retried");
            wait_for_tick(&observation, observation.ticks());
            drop(first);
            wait_for_tick(&observation, observation.ticks());
            drop(last);
            assert!(observation.completed());
        },
    );
}

#[test]
fn ordinary_factory_drop_retains_worker_for_a_surviving_runtime_owner() {
    supervise(
        "factory::tests::ordinary_factory_drop_retains_worker_for_a_surviving_runtime_owner",
        || {
            let factory =
                WasmtimeComponentEngineFactory::new(WasmtimeConfig::default()).expect("factory");
            let observation = factory.shared.epoch_observation();
            let backend = factory.create_backend_instance();
            // Prepared-use handles retain exactly this Arc independently of the
            // backend. Model that ownership without compiling another fixture.
            let retained_runtime = Arc::clone(&factory.shared);
            let engine = factory.engine.clone();
            drop(factory);
            drop(backend);
            wait_for_tick(&observation, observation.ticks());
            drop(retained_runtime);
            assert!(observation.completed());
            assert!(engine.weak().upgrade().is_some());
        },
    );
}
