use super::{settings, Catalogs, TempDir};
use crate::standalone::{RuntimeThreads, StandaloneNode};
use latent_telemetry::{LogRecord, LogSeverity};

#[tokio::test]
async fn provider_bootstrap_transfers_the_same_exporter_to_the_running_node() {
    let directory = TempDir::new().unwrap();
    let settings = settings(&directory);
    let mut catalogs = Catalogs::open(&settings).await.unwrap();
    catalogs.telemetry =
        Some(crate::standalone::telemetry::TelemetryOwner::start(&settings).unwrap());
    let owner = catalogs.telemetry.as_ref().unwrap();
    let before = owner.handle.clone();
    let sink = owner.sink.clone();
    let node = Box::pin(StandaloneNode::start_with_catalogs(
        settings,
        catalogs,
        tokio::runtime::Handle::current(),
        RuntimeThreads::default(),
    ))
    .await
    .unwrap();
    before
        .try_emit_log(LogRecord {
            severity: LogSeverity::Info,
            body: "owned-exporter-handoff".into(),
            trace: None,
            attributes: std::collections::BTreeMap::default(),
            observed_at_unix_millis: 1,
        })
        .unwrap();
    let report = node.shutdown().await.unwrap();
    assert!(report.clean && report.telemetry_flushed && before.is_closed());
    assert!(sink.records().iter().any(|record| matches!(record,
        latent_telemetry::TelemetryRecord::Log(log) if log.body == "owned-exporter-handoff")));
}

#[tokio::test]
async fn changed_exporter_limits_reject_composition_and_join_the_bootstrap_owner() {
    let directory = TempDir::new().unwrap();
    let mut settings = settings(&directory);
    let mut catalogs = Catalogs::open(&settings).await.unwrap();
    catalogs.telemetry =
        Some(crate::standalone::telemetry::TelemetryOwner::start(&settings).unwrap());
    let before = catalogs.telemetry.as_ref().unwrap().handle.clone();
    settings.telemetry.queue_capacity += 1;
    let error = Box::pin(StandaloneNode::start_with_catalogs(
        settings,
        catalogs,
        tokio::runtime::Handle::current(),
        RuntimeThreads::default(),
    ))
    .await
    .err()
    .unwrap();
    assert_eq!(error.code, latent_core::PlatformErrorCode::PermissionDenied);
    assert!(before.is_closed());
}
