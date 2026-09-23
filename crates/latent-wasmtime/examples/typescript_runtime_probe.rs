//! Compiler diagnostic only; this linker does not replace signed LSF admission.
use std::{
    sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    },
    time::{Duration, Instant},
};
use wasmtime::component::{Component, Linker, Val};
use wasmtime::{Config, Engine, Store, StoreLimits, StoreLimitsBuilder};

struct Pending(Arc<AtomicUsize>);

impl Drop for Pending {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::SeqCst);
    }
}

#[tokio::main]
async fn main() -> wasmtime::Result<()> {
    let path = std::env::args()
        .nth(1)
        .ok_or_else(|| wasmtime::Error::msg("component path required"))?;
    let mut config = Config::new();
    config.wasm_component_model_async(true).consume_fuel(true);
    let engine = Engine::new(&config)?;
    let started = Instant::now();
    let component = Component::from_file(&engine, path)?;
    println!(
        "diagnostic compile millis: {}",
        started.elapsed().as_millis()
    );
    let pending = Arc::new(AtomicUsize::new(0));
    let count = pending.clone();
    let mut linker = Linker::new(&engine);
    linker
        .instance("lsf:typescript-probe/host@1.0.0")?
        .func_wrap_async("echo", move |_, (text,): (String,)| {
            let count = count.clone();
            Box::new(async move {
                count.fetch_add(1, Ordering::SeqCst);
                let _owner = Pending(count);
                let delay = if text == "cancel" { 60_000 } else { 20 };
                tokio::time::sleep(Duration::from_millis(delay)).await;
                Ok((text,))
            })
        })?;
    for text in ["Hello, 世界! 🚚", "", "panic", "cancel", "Hello again"] {
        let input = Val::Record(vec![
            ("value".into(), Val::U64(u64::MAX)),
            ("text".into(), Val::String(text.into())),
            ("bytes".into(), Val::List(vec![Val::U8(0), Val::U8(255)])),
        ]);
        let started = Instant::now();
        let future = invoke(&engine, &component, &linker, input.clone());
        if text == "cancel" {
            assert!(
                tokio::time::timeout(Duration::from_millis(100), future)
                    .await
                    .is_err()
            );
        } else {
            let actual = future.await;
            println!("diagnostic invocation: {text:?}; result: {actual:?}");
            if text == "panic" {
                assert!(actual.is_err(), "guest fuel exhaustion must trap");
            } else {
                let expected = if text.is_empty() {
                    Val::Result(Err(Some(Box::new(Val::String(
                        "Please enter text.".into(),
                    )))))
                } else {
                    Val::Result(Ok(Some(Box::new(input))))
                };
                assert_eq!(actual?, expected);
            }
        }
        assert_eq!(pending.load(Ordering::SeqCst), 0, "host future leaked");
        println!(
            "diagnostic invocation millis: {}",
            started.elapsed().as_millis()
        );
    }
    println!(
        "TypeScript async boundary passed; signed admission and SDK qualification remain required"
    );
    Ok(())
}

async fn invoke(
    engine: &Engine,
    component: &Component,
    linker: &Linker<StoreLimits>,
    input: Val,
) -> wasmtime::Result<Val> {
    let limits = StoreLimitsBuilder::new()
        .memory_size(128 * 1024 * 1024)
        .build();
    let mut store = Store::new(engine, limits);
    store.limiter(|limits| limits);
    store.set_fuel(100_000_000)?;
    let instance = linker.instantiate_async(&mut store, component).await?;
    let (_, interface) = instance
        .get_export(&mut store, None, "lsf:typescript-probe/probe@1.0.0")
        .ok_or_else(|| wasmtime::Error::msg("missing contract"))?;
    let (_, index) = instance
        .get_export(&mut store, Some(&interface), "run")
        .ok_or_else(|| wasmtime::Error::msg("missing function"))?;
    let function = instance
        .get_func(&mut store, index)
        .ok_or_else(|| wasmtime::Error::msg("missing callable"))?;
    let mut output = [Val::Bool(false)];
    function
        .call_async(&mut store, &[input], &mut output)
        .await?;
    Ok(output.into_iter().next().expect("one output"))
}
