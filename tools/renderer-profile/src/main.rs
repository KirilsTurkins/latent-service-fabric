//! Operator-controlled qualification tool, not a node execution/admission path.
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    io::Read,
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    time::Instant,
};
use wasmtime::{
    component::{Component, Linker},
    Config, Engine, Store,
};

const MEMORY: usize = 256 * 1024 * 1024;
const FUEL: u64 = 2_000_000_000;
const HOSTCALL: usize = 128 * 1024;

fn message(error: impl std::fmt::Display) -> String {
    error.to_string()
}

mod ownership;
use ownership::{state, State, Ticker};

fn released(live: &Arc<AtomicUsize>) -> Result<(), String> {
    if live.load(Ordering::Acquire) != 0 {
        return Err("store owner retained after drop".into());
    }
    Ok(())
}
fn instance(
    engine: &Engine,
    component: &Component,
    store: &mut Store<State>,
) -> Result<wasmtime::component::Instance, String> {
    // Empty linker proves there are no ambient WASI/provider imports.
    Linker::new(engine)
        .instantiate(store, component)
        .map_err(message)
}
fn call(
    instance: &wasmtime::component::Instance,
    store: &mut Store<State>,
    export: &str,
    input: &str,
) -> wasmtime::Result<String> {
    let function = instance.get_typed_func::<(&str,), (String,)>(&mut *store, export)?;
    let (value,) = function.call(store, (input,))?;
    Ok(value)
}
fn render(
    engine: &Engine,
    component: &Component,
    live: &Arc<AtomicUsize>,
    name: &str,
) -> Result<(Value, String), String> {
    let started = Instant::now();
    let mut store = state(engine, live, MEMORY)?;
    let instance = instance(engine, component, &mut store)?;
    let setup_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let started = Instant::now();
    let output = call(&instance, &mut store, "render", name).map_err(message)?;
    let millis = started.elapsed().as_secs_f64() * 1_000.0;
    let value: Value = serde_json::from_str(&output).map_err(message)?;
    let html = value
        .get("html")
        .and_then(Value::as_str)
        .ok_or("renderer did not produce HTML")?;
    let escaped = name
        .replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;");
    if value["calls"] != 1 || !html.contains("ngh=") || !html.contains(&escaped) {
        return Err("fresh renderer state or hydration metadata mismatch".into());
    }
    let report = json!({"name":name,"setup_millis":setup_ms,"render_millis":millis,
        "html_bytes":html.len(),"fuel":FUEL-store.get_fuel().map_err(message)?,
        "peak_linear_memory_bytes":store.data().peak_memory,"live_stores_after_drop":0});
    drop(store);
    released(live)?;
    Ok((report, html.to_owned()))
}
fn reject(
    engine: &Engine,
    component: &Component,
    live: &Arc<AtomicUsize>,
    mode: &str,
    fuel: u64,
    epochs: u64,
) -> Result<Value, String> {
    let mut store = state(engine, live, MEMORY)?;
    let instance = instance(engine, component, &mut store)?;
    store.set_fuel(fuel).map_err(message)?;
    store.set_epoch_deadline(epochs);
    let started = Instant::now();
    let error =
        call(&instance, &mut store, "probe", mode).expect_err("adversarial probe must fail");
    let millis = started.elapsed().as_secs_f64() * 1_000.0;
    let trap = error.downcast_ref::<wasmtime::Trap>();
    if fuel == 100_000 && trap != Some(&wasmtime::Trap::OutOfFuel) {
        return Err("expected fuel interruption".into());
    }
    if epochs == 25 && trap != Some(&wasmtime::Trap::Interrupt) {
        return Err("expected epoch interruption".into());
    }
    if mode == "allocate" && store.data().memory_denials == 0 {
        return Err("allocation did not reach the memory limiter".into());
    }
    if mode == "output"
        && (!error.chain().any(|cause| {
            cause
                .to_string()
                .contains("fuel allocated for hostcalls has been exhausted")
        }) || store.get_fuel().map_err(message)? == 0)
    {
        return Err("oversized output did not reach the host allocation limiter".into());
    }
    let result = json!({"probe":mode,"millis":millis,"trap":trap.map(|t|format!("{t:?}")),
        "guest_fuel_remaining":store.get_fuel().map_err(message)?,
        "memory_denials":store.data().memory_denials,"peak_linear_memory_bytes":store.data().peak_memory});
    drop(store);
    released(live)?;
    // A real successful SSR after every failure, including a fresh JS module counter.
    let _ = render(engine, component, live, "AfterFailure")?;
    Ok(result)
}
fn negative_reuse(
    engine: &Engine,
    component: &Component,
    live: &Arc<AtomicUsize>,
) -> Result<(), String> {
    let mut store = state(engine, live, MEMORY)?;
    let instance = instance(engine, component, &mut store)?;
    for count in [1, 2] {
        let output = call(&instance, &mut store, "render", "Retained").map_err(message)?;
        let value: Value = serde_json::from_str(&output).map_err(message)?;
        if value["calls"] != count {
            return Err("reuse negative control mismatch".into());
        }
    }
    drop(store);
    released(live)
}

fn profile() -> Result<String, String> {
    let bytes = include_str!("../../../examples/renderer-profile/profile.json");
    let value: Value = serde_json::from_str(bytes).map_err(message)?;
    for (key, expected) in [
        ("linearMemoryBytes", MEMORY as u64),
        ("guestFuel", FUEL),
        ("hostcallBytes", HOSTCALL as u64),
        ("stackBytes", 2 * 1024 * 1024),
        ("memories", 1),
        ("tables", 4),
        ("tableElements", 131_072),
        ("instances", 32),
        ("epochTicks", 5_000),
    ] {
        if value[key].as_u64() != Some(expected) {
            return Err("qualification limits differ from the recorded profile".into());
        }
    }
    Ok(format!("sha256:{:x}", Sha256::digest(bytes)))
}
fn run() -> Result<(), String> {
    let profile_digest = profile()?;
    let mut args = std::env::args_os().skip(1);
    let path = args
        .next()
        .ok_or("usage: latent-renderer-profile COMPONENT OUTPUT_HTML")?;
    let output = args.next().ok_or("output HTML path required")?;
    if args.next().is_some() {
        return Err("unexpected argument".into());
    }
    let mut bytes = Vec::new();
    std::fs::File::open(path)
        .map_err(message)?
        .take(32 * 1024 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(message)?;
    if bytes.len() > 32 * 1024 * 1024 {
        return Err("component input limit".into());
    }
    let mut config = Config::new();
    config
        .wasm_component_model(true)
        .wasm_component_model_async(true)
        .consume_fuel(true)
        .epoch_interruption(true)
        .max_wasm_stack(2 * 1024 * 1024);
    let engine = Engine::new(&config).map_err(message)?;
    let started = Instant::now();
    let component = Component::new(&engine, &bytes).map_err(message)?;
    let preparation_ms = started.elapsed().as_secs_f64() * 1_000.0;
    let _ticker = Ticker::start(engine.clone());
    let live = Arc::new(AtomicUsize::new(0));
    let mut samples = Vec::new();
    for name in ["Alice <unsafe>", "Bob", "Alice <unsafe>"] {
        let (sample, html) = render(&engine, &component, &live, name)?;
        if samples.is_empty() {
            std::fs::write(&output, html).map_err(message)?;
        }
        samples.push(sample);
    }
    negative_reuse(&engine, &component, &live)?;
    let mut store = state(&engine, &live, 1024 * 1024)?;
    if instance(&engine, &component, &mut store).is_ok() || store.data().memory_denials == 0 {
        return Err("undersized guest memory was not rejected by the limiter".into());
    }
    drop(store);
    released(&live)?;
    let mut failures = Vec::new();
    for (mode, fuel, epochs) in [
        ("spin", 100_000, 5_000),
        ("spin", u64::MAX, 25),
        ("promise-storm", u64::MAX, 25),
        ("allocate", FUEL, 5_000),
        ("throw", FUEL, 5_000),
        ("output", u64::MAX, 5_000),
        ("delayed-timer", FUEL, 5_000),
        ("interval", FUEL, 5_000),
        ("timer-limit", FUEL, 5_000),
        ("microtask-limit", FUEL, 5_000),
    ] {
        failures.push(reject(&engine, &component, &live, mode, fuel, epochs)?);
    }
    println!(
        "{}",
        json!({"format_version":1,"engine":"wasmtime-47.0.4","profile_sha256":profile_digest,
        "target_os":std::env::consts::OS,"target_arch":std::env::consts::ARCH,
        "component_sha256":format!("sha256:{:x}",Sha256::digest(&bytes)),"component_bytes":bytes.len(),
        "preparation_millis":preparation_ms,"memory_limit_bytes":MEMORY,"hostcall_bytes":HOSTCALL,
        "fuel":FUEL,"samples":samples,"failures":failures,"small_memory_rejected":true,
        "reuse_negative_control":true,"success_after_each_failure":true,"live_stores":0})
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("renderer-profile: {error}");
        std::process::exit(1);
    }
}
