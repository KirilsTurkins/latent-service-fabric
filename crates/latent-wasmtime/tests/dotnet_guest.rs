//! Execute the real NativeAOT output; raw WASI is never admitted by LSF.
#![cfg(target_os = "linux")]
#[path = "generic_backend/support.rs"]
#[allow(dead_code)]
mod support;

use latent_core::{CapabilityId, ContractId};
use latent_executor::{BoundImport, ExecutionBackend};
use latent_manifest::ContractImport;
use latent_wasmtime::WasmtimeComponentEngineFactory;

const CONTRACT: &str = "example:dotnetprobe/operations@1.0.0";
const CLOCK: &str = "latent:clock/monotonic@0.1.0";
const MEMORY: u64 = 128 * 1024 * 1024;

#[tokio::test]
#[ignore = "Requires the compiled .NET qualification components"]
async fn admitted_dotnet_component_preserves_values_and_drops_every_activation_heap() {
    let directory = std::path::PathBuf::from(
        std::env::var_os("LSF_DOTNET_PROBE").expect("compiled probe path"),
    );
    let mut config = support::config();
    config.maximum_memory_bytes = MEMORY;
    let factory = WasmtimeComponentEngineFactory::new(config).unwrap();
    let backend = factory.create_backend_instance();
    let raw = support::artifact_bytes(
        std::fs::read(directory.join("raw.wasm")).unwrap(),
        &[CONTRACT],
    );
    assert!(backend
        .prepare(
            &raw,
            &factory.preparation_key(raw.descriptor.release_digest.clone())
        )
        .await
        .is_err());
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    let mut artifact = support::artifact_bytes(
        std::fs::read(directory.join("component.wasm")).unwrap(),
        &[CONTRACT],
    );
    artifact
        .manifest
        .execution
        .resource_budget_ceiling
        .memory_bytes = MEMORY;
    // The package must describe the compiler's real dependency, not fabricate
    // an optional grant or relax the node's supported-import allowlist.
    artifact.manifest.imports.push(ContractImport {
        contract: ContractId(CLOCK.to_owned()),
        optional: false,
    });
    let started = std::time::Instant::now();
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .unwrap();
    println!(
        "dotnet cold prepare: {:?}; component bytes: {}",
        started.elapsed(),
        artifact.component_bytes.len()
    );
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    let mut budget = support::budget();
    budget.memory_bytes = MEMORY;
    let denied = support::Cancellation::new("dotnet-clock-denied");
    let request = support::request(
        prepared.clone(),
        &denied.id,
        CONTRACT,
        "echo",
        b"[\"denied\"]",
        budget.clone(),
    );
    assert!(support::run(&backend, request, &denied).await.is_err());
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    support::idle(&backend);
    let populated = serde_json::json!({
        "text": "Hello\0世界 🚚", "unsigned": "18446744073709551615", "signed": "-9223372036854775808",
        "maybe": {"some": "9007199254740993"},
        "items": [{"text": "", "amount": "0"}, {"text": "nested\0🚚", "amount": "18446744073709551615"}]
    });
    let empty = serde_json::json!({
        "text": "empty-list", "unsigned": "0", "signed": "9223372036854775807",
        "maybe": {"none": null}, "items": []
    });
    let rejected = serde_json::json!({
        "text": "", "unsigned": "9007199254740993", "signed": "-9007199254740993",
        "maybe": {"some": "0"}, "items": []
    });
    for (index, (function, input, expected)) in [
        ("echo", serde_json::json!([""]), serde_json::json!([""])),
        (
            "echo",
            serde_json::json!(["Hello, 世界!\0🚚"]),
            serde_json::json!(["Hello, 世界!\0🚚"]),
        ),
        (
            "wide",
            serde_json::json!(["18446744073709551615"]),
            serde_json::json!(["18446744073709551615"]),
        ),
        (
            "mirror",
            serde_json::json!([populated.clone()]),
            serde_json::json!([{"ok": populated}]),
        ),
        (
            "mirror",
            serde_json::json!([empty.clone()]),
            serde_json::json!([{"ok": empty}]),
        ),
        (
            "mirror",
            serde_json::json!([rejected]),
            serde_json::json!([{"err": "empty\0text 世界"}]),
        ),
        ("profile", serde_json::json!([]), serde_json::json!([17])),
        ("next", serde_json::json!([]), serde_json::json!([1])),
        ("next", serde_json::json!([]), serde_json::json!([1])),
    ]
    .into_iter()
    .enumerate()
    {
        let control = support::Cancellation::new(&format!("dotnet-{index}"));
        let mut request = support::request(
            prepared.clone(),
            &control.id,
            CONTRACT,
            function,
            &serde_json::to_vec(&input).unwrap(),
            budget.clone(),
        );
        request.imports.push(BoundImport {
            capability: CapabilityId(CLOCK.to_owned()),
            contract: CLOCK.to_owned(),
            opaque_handle: "activation-scoped-test-clock".to_owned(),
        });
        let started = std::time::Instant::now();
        let outcome = support::run(&backend, request, &control).await.unwrap();
        println!("dotnet {function}: {:?}; {outcome:?}", started.elapsed());
        assert_eq!(support::returned(outcome), expected);
        support::idle(&backend);
    }
}

#[tokio::test]
#[ignore = "Requires the compiled .NET qualification component; diagnostic only"]
async fn diagnostic_dotnet_component_requires_only_the_declared_clock() {
    use wasmtime::component::{Component, Linker, Val};
    use wasmtime::{Config, Engine, Store, StoreLimitsBuilder, WasmBacktraceDetails};
    let directory = std::path::PathBuf::from(
        std::env::var_os("LSF_DOTNET_PROBE").expect("compiled probe path"),
    );
    let mut config = Config::new();
    config.wasm_component_model_async(true).consume_fuel(true);
    config.wasm_backtrace_details(WasmBacktraceDetails::Enable);
    let engine = Engine::new(&config).unwrap();
    let component = Component::new(
        &engine,
        std::fs::read(directory.join("component.wasm")).unwrap(),
    )
    .unwrap();
    let mut linker = Linker::new(&engine);
    let epoch = std::time::Instant::now();
    // A diagnostic linker is not admission evidence. The backend test above
    // independently proves that the absent clock grant rejects before a store.
    linker
        .instance(CLOCK)
        .unwrap()
        .func_wrap("now-nanos", move |_, (): ()| {
            Ok((u64::try_from(epoch.elapsed().as_nanos()).unwrap(),))
        })
        .unwrap();
    let limits = StoreLimitsBuilder::new()
        .memory_size(MEMORY as usize)
        .build();
    let mut store = Store::new(&engine, limits);
    store.limiter(|limits| limits);
    store.set_fuel(1_000_000_000).unwrap();
    let instance = linker
        .instantiate_async(&mut store, &component)
        .await
        .unwrap();
    let (_, interface) = instance.get_export(&mut store, None, CONTRACT).unwrap();
    let (_, index) = instance
        .get_export(&mut store, Some(&interface), "echo")
        .unwrap();
    let function = instance.get_func(&mut store, index).unwrap();
    let mut output = [Val::String(String::new())];
    let result = function
        .call_async(&mut store, &[Val::String("hello".to_owned())], &mut output)
        .await;
    assert!(result.is_ok(), "NativeAOT startup failed: {result:?}");
    assert!(matches!(&output[0], Val::String(value) if value == "hello"));
}
