//! Compiler diagnostic only; this linker does not replace signed LSF admission.
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
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
    let optimization = std::env::args().nth(2).unwrap_or_else(|| "speed".into());
    config.cranelift_opt_level(match optimization.as_str() {
        "none" => wasmtime::OptLevel::None,
        "speed" => wasmtime::OptLevel::Speed,
        _ => return Err(wasmtime::Error::msg("unsupported diagnostic optimization")),
    });
    println!("diagnostic compiler optimization: {optimization}");
    let engine = Engine::new(&config)?;
    let started = Instant::now();
    let component = Component::from_file(&engine, path)?;
    println!(
        "diagnostic compile millis: {}",
        started.elapsed().as_millis()
    );
    if std::env::args().nth(3).as_deref() == Some("sdk-random") {
        return sdk_random(&engine, &component).await;
    }
    let pending = Arc::new(AtomicUsize::new(0));
    let count = pending.clone();
    let mut linker = Linker::new(&engine);
    let mut host = linker.instance("lsf:typescript-probe/host@1.0.0")?;
    host.func_wrap_concurrent("echo", move |_, (text,): (String,)| {
        let count = count.clone();
        Box::pin(async move {
            count.fetch_add(1, Ordering::SeqCst);
            let _owner = Pending(count);
            let delay = if text == "cancel" { 60_000 } else { 20 };
            tokio::time::sleep(Duration::from_millis(delay)).await;
            Ok((text,))
        })
    })?;
    host.func_wrap_concurrent(
        "roundtrip",
        |_, (value, minimum, maximum): (u64, i64, i64)| {
            Box::pin(async move { Ok(((value, minimum, maximum),)) })
        },
    )?;
    for text in ["Hello, \0世界! 🚚", "", "panic", "cancel", "Hello again"] {
        let input = Val::Record(vec![
            ("value".into(), Val::U64(u64::MAX)),
            ("minimum".into(), Val::S64(i64::MIN)),
            ("maximum".into(), Val::S64(i64::MAX)),
            ("text".into(), Val::String(text.into())),
            ("bytes".into(), Val::List(vec![Val::U8(0), Val::U8(255)])),
        ]);
        let started = Instant::now();
        let future = invoke(&engine, &component, &linker, "run", input.clone());
        if text == "cancel" {
            assert!(tokio::time::timeout(Duration::from_millis(100), future)
                .await
                .is_err());
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
    for value in [i64::MIN, -1, 0, i64::MAX] {
        assert_eq!(
            invoke(&engine, &component, &linker, "echo-signed", Val::S64(value)).await?,
            Val::S64(value)
        );
    }
    println!("TypeScript async and signed scalar boundaries passed; signed admission and SDK qualification remain required");
    Ok(())
}

async fn sdk_random(engine: &Engine, component: &Component) -> wasmtime::Result<()> {
    let mut linker = Linker::new(engine);
    let mut random = linker.instance("latent:random/random@0.1.0")?;
    random.func_new_async("bytes", |_, _, input, output| {
        Box::new(async move {
            let Val::U32(length) = input[0] else {
                panic!("length type")
            };
            println!("diagnostic random bytes host called: {length}");
            assert!(
                length == 32 || length == u32::MAX,
                "u32 must preserve all 32 bits"
            );
            output[0] = if length > 4096 {
                Val::Result(Err(Some(Box::new(Val::Variant(
                    "invalid-length".into(),
                    None,
                )))))
            } else {
                Val::Result(Ok(Some(Box::new(Val::List(vec![
                    Val::U8(1);
                    length as usize
                ])))))
            };
            Ok(())
        })
    })?;
    random.func_new_async("u64-value", |_, _, _, output| {
        Box::new(async move {
            println!("diagnostic scalar random host called");
            output[0] = Val::Result(Ok(Some(Box::new(Val::U64(u64::MAX)))));
            Ok(())
        })
    })?;
    for (which, expected) in [(0, 32), (1, 8), (2, 10), (0, 32)] {
        let mut store = Store::new(
            engine,
            StoreLimitsBuilder::new()
                .memory_size(128 * 1024 * 1024)
                .build(),
        );
        store.limiter(|limits| limits);
        store.set_fuel(1_000_000_000)?;
        let instance = linker.instantiate_async(&mut store, component).await?;
        let (_, interface) = instance
            .get_export(&mut store, None, "tests:random/api@1.0.0")
            .expect("random API");
        let (_, index) = instance
            .get_export(&mut store, Some(&interface), "run")
            .expect("run");
        let function = instance.get_func(&mut store, index).expect("function");
        let mut output = [Val::Bool(false)];
        let result = function
            .call_async(
                &mut store,
                &[Val::U32(which), Val::String(String::new()), Val::U64(0)],
                &mut output,
            )
            .await;
        println!("diagnostic random case {which}: {result:?}, output {output:?}");
        result?;
        assert_eq!(output, [Val::U64(expected)]);
    }
    Ok(())
}

async fn invoke(
    engine: &Engine,
    component: &Component,
    linker: &Linker<StoreLimits>,
    function: &str,
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
        .get_export(&mut store, Some(&interface), function)
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
