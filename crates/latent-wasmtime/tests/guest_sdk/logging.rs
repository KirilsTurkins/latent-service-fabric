use latent_artifacts::ArtifactRepository;
use latent_core::{ActivationBudget, ActivationId, ClockSample, EffectiveActivationBudget};
use latent_executor::{BoundImport, ExecutionCancellation};
use latent_wasmtime::{
    CapturedLog, LogSinkError, StructuredLogSink, WasmtimeComponentEngineFactory,
    WasmtimeHostServices,
};
use std::sync::Arc;

struct Control {
    id: ActivationId,
    budget: ActivationBudget,
}
impl ExecutionCancellation for Control {
    fn activation_id(&self) -> &ActivationId {
        &self.id
    }
    fn is_cancelled(&self) -> bool {
        false
    }
    fn reason(&self) -> Option<String> {
        None
    }
    fn budget_accounting(&self) -> Option<&ActivationBudget> {
        Some(&self.budget)
    }
}
struct Reject;
impl StructuredLogSink for Reject {
    fn try_emit(&self, _: &CapturedLog, _: &[u8]) -> Result<(), LogSinkError> {
        Err(LogSinkError::Unavailable)
    }
}

#[tokio::test]
#[ignore = "Requires actual signed Java standard logging component"]
async fn standard_java_console_preserves_encoding_original_budget_errors_and_fresh_state() {
    if !super::languages().contains(&"java") {
        return;
    }
    let root = tempfile::tempdir().unwrap();
    let (catalog, release, receipt) = super::package::publish(root.path(), "java-logging").await;
    let ceiling = catalog
        .fetch(&release)
        .await
        .unwrap()
        .manifest
        .execution
        .resource_budget_ceiling;
    assert_eq!(ceiling.log_bytes, 8192);
    // This existing core log path is explicitly authorized by the admitted
    // component import and original LogBytes grant, with no provider session.
    // Broker policy/audit controls stay in capabilities_backend and are not
    // replaced by this standard-runtime integration fixture.
    for rejected_sink in [false, true] {
        let services = WasmtimeHostServices {
            log_sink: if rejected_sink {
                Some(Arc::new(Reject))
            } else {
                None
            },
            ..WasmtimeHostServices::default()
        };
        let factory = WasmtimeComponentEngineFactory::with_catalog(
            super::support::config(),
            services,
            catalog.lifecycle_authority(),
        )
        .unwrap();
        let backend = factory.create_backend_instance();
        let mut key = factory.preparation_key(release.clone());
        key.publication = Some(receipt.publication.id.clone());
        let ready = backend
            .prepare_ready_from_repository(catalog.clone(), key)
            .await
            .unwrap();
        let prepared = ready.descriptor().clone();
        drop(ready);
        for iteration in 0..2 {
            for mode in if rejected_sink {
                vec![5]
            } else {
                vec![0, 1, 2, 3, 4, 6, 7]
            } {
                let id = ActivationId(format!("java-log-{rejected_sink}-{iteration}-{mode}"));
                let mut grant = ceiling.clone();
                grant.log_bytes = if mode == 4 { 0 } else { 8192 };
                let control = Control {
                    id: id.clone(),
                    budget: ActivationBudget::new(
                        EffectiveActivationBudget::admit_at(
                            &grant,
                            &grant,
                            &grant,
                            None,
                            ClockSample::system_now(),
                        )
                        .unwrap(),
                    ),
                };
                let mut request = super::support::request(
                    prepared.clone(),
                    &id,
                    "tests:logging/api@1.0.0",
                    "run",
                    b"[]",
                    grant,
                );
                super::input(&mut request, mode, "", 0);
                request.imports.push(BoundImport {
                    capability: latent_core::CapabilityId("latent:log/log@0.1.0".into()),
                    contract: "latent:log/log@0.1.0".into(),
                    opaque_handle: "explicit-core-log-test-grant".into(),
                });
                assert_eq!(super::run(&backend, request, &control).await, 42);
                let captured = backend.log_sink().snapshot_for(&id);
                let expected = match mode {
                    0 => "plain café 🌍".to_owned(),
                    1 => "failure\n".to_owned(),
                    2 => "42:ok".to_owned(),
                    6 => "A".repeat(256),
                    _ => String::new(),
                };
                assert_eq!(
                    captured
                        .iter()
                        .map(|entry| entry.message.as_str())
                        .collect::<String>(),
                    expected
                );
                assert!(captured.len() <= 16);
                for entry in &captured {
                    assert_eq!(entry.level, if mode == 1 { "error" } else { "info" });
                    assert_eq!(entry.activation_id, id);
                    assert_eq!(entry.fields["latent.activation_id"], id.0);
                    assert_eq!(entry.fields["latent.trace_id"], "trace-generic");
                    assert_eq!(entry.fields["latent.span_id"], "span-generic");
                    assert_eq!(entry.fields.len(), 3);
                }
                let spent = control
                    .budget
                    .snapshot_at(std::time::Instant::now())
                    .log_bytes;
                assert_eq!(spent == 0, expected.is_empty());
                assert_eq!(control.budget.outstanding_reservations(), 0);
                super::support::idle(&backend);
                assert_eq!(backend.active_instance_reservations(), 0);
                backend.log_sink().clear();
            }
        }
    }
}
