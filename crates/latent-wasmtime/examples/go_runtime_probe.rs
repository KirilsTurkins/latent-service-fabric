//! Compiler diagnostic only: this linker does not replace signed LSF admission.
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Instant;
use wasmtime::component::{Component, Linker, Val};
use wasmtime::{Config, Engine, Store, StoreLimits, StoreLimitsBuilder};

const CONTRACT: &str = "lsf:go-probe/probe@1.0.0";

#[tokio::main]
async fn main() -> wasmtime::Result<()> {
    let mut args = std::env::args().skip(1);
    let path = args
        .next()
        .ok_or_else(|| wasmtime::Error::msg("component path required"))?;
    let recovery = match args.next().as_deref() {
        None => false,
        Some("--recovery") => true,
        _ => return Err(wasmtime::Error::msg("unknown diagnostic mode")),
    };
    if args.next().is_some() {
        return Err(wasmtime::Error::msg("unexpected diagnostic argument"));
    }
    let mut config = Config::new();
    config.wasm_component_model_async(true).consume_fuel(true);
    let engine = Engine::new(&config)?;
    let began = Instant::now();
    let component = Component::from_file(&engine, path)?;
    println!("diagnostic compile millis: {}", began.elapsed().as_millis());
    let (linker, calls) = linker(&engine)?;
    if recovery {
        for which in [0, 3, 0] {
            let before = calls.each_ref().map(|count| count.load(Ordering::Relaxed));
            let result = invoke(&engine, &component, &linker, Val::U32(which), true).await;
            let used = std::array::from_fn::<_, 3, _>(|index| {
                calls[index].load(Ordering::Relaxed) - before[index]
            });
            println!("diagnostic recovery {which}: {result:?}; clock/random calls: {used:?}");
            if which == 0 {
                assert_eq!(result?, Val::U32(1));
            } else {
                assert_eq!(
                    result.unwrap_err().downcast_ref::<wasmtime::Trap>(),
                    Some(&wasmtime::Trap::OutOfFuel)
                );
                // The bounded worker fixture tests fuel/Store reclamation,
                // not an unbounded sequence of runtime capability effects.
                assert!(used[0] <= 4096 && used[1] <= 4096 && used[2] <= 4096);
            }
        }
        println!("Go recovery diagnostic passed; no signed admission or capability-policy qualification claimed");
        return Ok(());
    }
    for (text, signed) in [
        ("Hello, 世界!\0 🚚", i64::MIN),
        ("Signed maximum", i64::MAX),
        ("", 0),
        ("panic", -1),
        ("Hello again", 0),
    ] {
        let bytes = if signed == i64::MAX {
            Vec::new()
        } else {
            vec![Val::U8(0), Val::U8(255)]
        };
        let input = Val::Record(vec![
            ("value".into(), Val::U64(u64::MAX)),
            ("signed".into(), Val::S64(signed)),
            ("unsigned".into(), Val::U32(u32::MAX)),
            ("text".into(), Val::String(text.into())),
            ("bytes".into(), Val::List(bytes)),
        ]);
        let started = Instant::now();
        let result = invoke(&engine, &component, &linker, input.clone(), false).await;
        println!(
            "diagnostic invocation millis: {}; result: {result:?}",
            started.elapsed().as_millis()
        );
        if text == "panic" {
            assert!(result.is_err(), "explicit guest panic must trap");
        } else {
            let actual = result?;
            let expected = if text.is_empty() {
                Val::Result(Err(Some(Box::new(Val::String(
                    "Please enter text.".into(),
                )))))
            } else {
                Val::Result(Ok(Some(Box::new(input))))
            };
            assert_eq!(actual, expected);
        }
    }
    println!("Go runtime diagnostic passed; signed admission and real-node qualification remain required");
    Ok(())
}

fn linker(engine: &Engine) -> wasmtime::Result<(Linker<StoreLimits>, Arc<[AtomicU64; 3]>)> {
    let mut linker = Linker::new(engine);
    let calls = Arc::new(std::array::from_fn(|_| AtomicU64::new(0)));
    let monotonic_calls = Arc::clone(&calls);
    let epoch = Instant::now();
    linker
        .instance("latent:clock/monotonic@0.1.0")?
        .func_wrap_async("now-nanos", move |_, (): ()| {
            monotonic_calls[0].fetch_add(1, Ordering::Relaxed);
            Box::new(async move { Ok((u64::try_from(epoch.elapsed().as_nanos())?,)) })
        })?;
    let wall_calls = Arc::clone(&calls);
    linker
        .instance("latent:clock/wall@0.1.0")?
        .func_wrap_async("now-unix-millis", move |_, (): ()| {
            wall_calls[1].fetch_add(1, Ordering::Relaxed);
            Box::new(async move {
                Ok((u64::try_from(
                    std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)?
                        .as_millis(),
                )?,))
            })
        })?;
    let random_calls = Arc::clone(&calls);
    linker
        .instance("latent:random/random@0.1.0")?
        .func_new_async("u64-value", move |_, _, _, output| {
            random_calls[2].fetch_add(1, Ordering::Relaxed);
            Box::new(async move {
                tokio::task::yield_now().await;
                let mut bytes = [0; 8];
                getrandom::fill(&mut bytes)
                    .map_err(|_| wasmtime::Error::msg("system entropy unavailable"))?;
                output[0] = Val::Result(Ok(Some(Box::new(Val::U64(u64::from_le_bytes(bytes))))));
                Ok(())
            })
        })?;
    Ok((linker, calls))
}

async fn invoke(
    engine: &Engine,
    component: &Component,
    linker: &Linker<StoreLimits>,
    input: Val,
    recovery: bool,
) -> wasmtime::Result<Val> {
    let limits = StoreLimitsBuilder::new()
        .memory_size(64 * 1024 * 1024)
        .build();
    let mut store = Store::new(engine, limits);
    store.limiter(|limits| limits);
    store.set_fuel(1_000_000_000)?;
    let instance = linker.instantiate_async(&mut store, component).await?;
    let (_, interface) = instance
        .get_export(
            &mut store,
            None,
            if recovery {
                "examples:recovery/api@1.0.0"
            } else {
                CONTRACT
            },
        )
        .ok_or_else(|| wasmtime::Error::msg("missing contract"))?;
    let (_, index) = instance
        .get_export(
            &mut store,
            Some(&interface),
            if recovery { "run" } else { "check" },
        )
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
