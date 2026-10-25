//! A real shared-engine component, not signed language-compiler provenance.
use latent_core::{diagnostic::DiagnosticReason, ContractId};
use latent_executor::{ExecutionBackend, ExecutionCleanup, GuestOutcome};
use latent_wasmtime::{WasmtimeComponentEngineFactory, WasmtimeConfig};
use serde_json::json;

use super::support::{artifact_bytes, budget, idle, request, returned, Cancellation, WATCHDOG};

const CONTRACT: &str = "examples:compatibility-stack/api@1.0.0";
const SOURCE: &[u8] = include_bytes!("../fixtures/compatibility_stack.wat");

#[tokio::test(flavor = "current_thread")]
#[ignore = "requires the exact canonical WAT parsed by the bounded compiler-diagnostics native owner"]
async fn actual_stack_overflow_keeps_original_typed_fact_and_new_store_fresh_result() {
    let path = std::env::var_os("LSF_COMPATIBILITY_STACK_COMPONENT")
        .expect("native owner supplies the one parsed component");
    let bytes = std::fs::read(path).expect("owned parsed stack component");
    assert!(!bytes.is_empty() && bytes.len() <= 65_536);
    assert!(!SOURCE.is_empty() && SOURCE.len() <= 65_536);
    let mut grant = budget();
    grant.cpu_fuel = 1_000_000_000;
    grant.wall_time_limit_millis = Some(5_000);
    let mut artifact = artifact_bytes(bytes, &[CONTRACT]);
    artifact.manifest.world = ContractId("examples:compatibility-stack/service@1.0.0".to_owned());
    artifact.manifest.execution.resource_budget_ceiling = grant.clone();
    assert!(artifact.manifest.imports.is_empty());
    let factory = WasmtimeComponentEngineFactory::new(WasmtimeConfig {
        maximum_fuel: grant.cpu_fuel,
        maximum_memory_bytes: grant.memory_bytes,
        ..WasmtimeConfig::default()
    })
    .expect("normal original engine profile");
    let backend = factory.create_backend_instance();
    let prepared = backend
        .prepare(
            &artifact,
            &factory.preparation_key(artifact.descriptor.release_digest.clone()),
        )
        .await
        .expect("real no-import component prepares");
    assert_eq!(backend.resource_snapshot().stores_created, 0);
    for (index, (id, input)) in [
        ("stack-overflow", b"[true]".as_slice()),
        ("fresh-after-stack", b"[false]".as_slice()),
    ]
    .into_iter()
    .enumerate()
    {
        let cancellation = Cancellation::new(id);
        let report = tokio::time::timeout(
            WATCHDOG,
            backend.invoke_contained(
                request(
                    prepared.clone(),
                    &cancellation.id,
                    CONTRACT,
                    "run",
                    input,
                    grant.clone(),
                ),
                &cancellation,
            ),
        )
        .await
        .expect("original finite component watchdog");
        assert_eq!(report.cleanup, ExecutionCleanup::Reusable);
        let outcome = report.outcome.expect("normal contained outcome");
        if index == 0 {
            let GuestOutcome::Trapped { trap, consumption } = outcome else {
                panic!("only actual engine StackOverflow qualifies this cell");
            };
            assert_eq!(trap.code, "guest-trap");
            assert_eq!(
                trap.metadata.get("trap").map(String::as_str),
                Some("stack-overflow")
            );
            let diagnostic = trap
                .diagnostic
                .expect("original typed engine stack diagnostic");
            assert_eq!(diagnostic.reason, DiagnosticReason::GuestStackExhausted);
            assert!(diagnostic.configured_bound.is_none());
            assert!(diagnostic.calculated_requirement.is_none());
            assert!(consumption.cpu_fuel > 0 && consumption.cpu_fuel <= grant.cpu_fuel);
            assert!(consumption.peak_memory_bytes <= grant.memory_bytes);
        } else {
            assert_eq!(returned(outcome), json!([42]));
        }
        idle(&backend);
        assert_eq!(backend.active_instance_reservations(), 0);
        assert_eq!(
            backend.resource_snapshot().stores_created,
            u64::try_from(index + 1).unwrap()
        );
    }
    println!("LSF_COMPATIBILITY_STACK_V1 stack-reason=26 fresh=42 stores=2 signed-language=false");
    backend
        .release(prepared)
        .await
        .expect("original prepared owner releases");
    let runtimes = factory.prepared_runtime_observer();
    drop(backend);
    tokio::time::timeout(WATCHDOG, factory.quiesce_compiler())
        .await
        .unwrap()
        .unwrap();
    factory.shutdown().unwrap();
    assert_eq!(runtimes.snapshot().unwrap(), Default::default());
}
