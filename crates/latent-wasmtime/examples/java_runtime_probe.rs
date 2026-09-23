//! Compiler/runtime diagnostic only, not signed standalone-node qualification.
use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc,
};
use std::time::{Instant, SystemTime, UNIX_EPOCH};
use wasmtime::component::{Component, Linker, Val};
use wasmtime::{Config, Engine, Store, StoreLimits, StoreLimitsBuilder};

#[tokio::main]
async fn main() -> wasmtime::Result<()> {
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| wasmtime::Error::msg("component path required"))?;
    let mut config = Config::new();
    config.wasm_component_model_async(true).consume_fuel(true);
    #[cfg(feature = "java-guest-diagnostic")]
    config
        .wasm_gc(false)
        .wasm_exceptions(true)
        .gc_heap_initial_size(64 * 1024)
        .gc_heap_reservation(4 * 1024 * 1024)
        .gc_heap_reservation_for_growth(0)
        .gc_heap_may_move(false);
    if !cfg!(feature = "java-guest-diagnostic") {
        return Err(wasmtime::Error::msg(
            "enable the explicit java-guest-diagnostic feature; node qualification is separate",
        ));
    }
    let engine = Engine::new(&config)?;
    let started = Instant::now();
    let component = Component::from_file(&engine, path)?;
    println!(
        "Java diagnostic compile millis: {}",
        started.elapsed().as_millis()
    );
    let calls = Arc::new(AtomicUsize::new(0));
    for denied in [true, false, false, false] {
        let linker = linker(&engine, denied, Arc::clone(&calls))?;
        let limits = StoreLimitsBuilder::new()
            .memory_size(64 * 1024 * 1024)
            .build();
        let mut store = Store::new(&engine, limits);
        store.limiter(|limits| limits);
        store.set_fuel(1_000_000_000)?;
        let started = Instant::now();
        let outcome = async {
            let instance = linker.instantiate_async(&mut store, &component).await?;
            let (_, interface) = instance
                .get_export(&mut store, None, "tests:java-feasibility/probe@1.0.0")
                .ok_or_else(|| wasmtime::Error::msg("missing Java export interface"))?;
            for (name, input, expected) in [
                ("identity", vec![Val::S64(i64::MIN)], Val::S64(i64::MIN)),
                ("identity", vec![Val::S64(i64::MAX)], Val::S64(i64::MAX)),
                ("smoke", vec![], Val::U32(4)),
                ("next", vec![], Val::U32(1)),
                ("next", vec![], Val::U32(2)),
            ] {
                let (_, index) = instance
                    .get_export(&mut store, Some(&interface), name)
                    .ok_or_else(|| wasmtime::Error::msg("missing Java export function"))?;
                let function = instance
                    .get_func(&mut store, index)
                    .ok_or_else(|| wasmtime::Error::msg("missing Java callable"))?;
                let mut output = [Val::Bool(false)];
                function.call_async(&mut store, &input, &mut output).await?;
                assert_eq!(output, [expected]);
            }
            Ok::<_, wasmtime::Error>(())
        }
        .await;
        if denied {
            let failure = outcome.expect_err("actual Java runtime must require its declared clock");
            assert!(
                format!("{failure:#}").contains("clock-denied"),
                "wrong diagnostic: {failure:#}"
            );
        } else {
            outcome?;
        }
        println!(
            "Java diagnostic activation denied={denied} millis={} fuel={}",
            started.elapsed().as_millis(),
            1_000_000_000 - store.get_fuel()?
        );
        // No Store, Java heap, guest static or host clock owner is retained.
        drop(store);
    }
    assert!(calls.load(Ordering::SeqCst) >= 4);
    println!("Java integer, UTF-8, caught-exception, GC and fresh-state diagnostic passed; signed node qualification remains required");
    Ok(())
}

fn linker(
    engine: &Engine,
    denied: bool,
    calls: Arc<AtomicUsize>,
) -> wasmtime::Result<Linker<StoreLimits>> {
    let mut linker = Linker::new(engine);
    let monotonic = Arc::clone(&calls);
    let origin = Instant::now();
    linker
        .instance("latent:clock/monotonic@0.1.0")?
        .func_wrap("now-nanos", move |_, (): ()| {
            monotonic.fetch_add(1, Ordering::SeqCst);
            if denied {
                return Err(wasmtime::Error::msg("clock-denied"));
            }
            Ok((u64::try_from(origin.elapsed().as_nanos())?,))
        })?;
    linker.instance("latent:clock/wall@0.1.0")?.func_wrap(
        "now-unix-millis",
        move |_, (): ()| {
            calls.fetch_add(1, Ordering::SeqCst);
            if denied {
                return Err(wasmtime::Error::msg("clock-denied"));
            }
            Ok((u64::try_from(
                SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
            )?,))
        },
    )?;
    Ok(linker)
}
