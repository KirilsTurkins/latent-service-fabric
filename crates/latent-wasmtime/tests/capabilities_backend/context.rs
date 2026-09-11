use std::sync::Arc;

use latent_core::{ActivationClock, ActivationId, Metadata, ServiceId, SpanId, TenantId, TraceId};
use latent_executor::GuestOutcome;
use latent_wasmtime::ContextExposurePolicy;
use serde_json::json;

use super::support::*;

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn default_context_filters_sensitive_maps_and_reuses_cell_without_identity_leakage() {
    let clock = Arc::new(ManualClock::new());
    let (backend, prepared) = prepared(config(), services(&clock)).await;
    for (id, marker) in [("context-first", "first"), ("context-second", "second")] {
        let mut grant = budget();
        grant.wall_time_limit_millis = Some(1000);
        let cancellation = Cancellation::new(id, &grant, clock.sample());
        let mut request = request(&prepared, &cancellation, "snapshot", &json!([]));
        let tenant = TenantId(format!("tenant-{marker}"));
        let service = ServiceId(format!("service-{marker}"));
        request.activation.principal.tenant = Some(tenant.clone());
        request.activation.principal.service = Some(service.clone());
        request.activation.target.tenant = tenant;
        request.activation.target.service = service;
        request.activation.root_activation_id = ActivationId(format!("root-{marker}"));
        request.activation.parent_activation_id = Some(ActivationId(format!("parent-{marker}")));
        request.activation.principal.subject = format!("subject-{marker}");
        request.activation.principal.claims = Metadata::from([
            ("role".to_owned(), marker.to_owned()),
            ("secret-token".to_owned(), "private-claim".to_owned()),
        ]);
        request.activation.trace.trace_id = TraceId(format!("trace-{marker}"));
        request.activation.trace.span_id = SpanId(format!("span-{marker}"));
        request.activation.trace.baggage = Metadata::from([
            ("guest.hint".to_owned(), "private-baggage".to_owned()),
            ("token".to_owned(), "sensitive".to_owned()),
        ]);
        request.activation.metadata = Metadata::from([
            ("guest.visible".to_owned(), marker.to_owned()),
            ("Guest.visible".to_owned(), "wrong-case".to_owned()),
            (
                "internal.credential".to_owned(),
                "private-metadata".to_owned(),
            ),
        ]);
        let output = returned(run(&backend, request, &cancellation).await);
        let value = &output[0];
        assert_eq!(value["activation"], id);
        assert_eq!(value["root"], format!("root-{marker}"));
        assert_eq!(value["parent"], json!({"some": format!("parent-{marker}")}));
        assert_eq!(value["principal"]["subject"], format!("subject-{marker}"));
        assert_eq!(value["principal"]["kind"], "service");
        assert_eq!(
            value["principal"]["tenant"],
            json!({"some": format!("tenant-{marker}")})
        );
        assert_eq!(
            value["principal"]["service"],
            json!({"some": format!("service-{marker}")})
        );
        assert_eq!(value["principal"]["claims"], json!([]));
        assert_eq!(value["trace"]["trace-id"], format!("trace-{marker}"));
        assert_eq!(value["trace"]["span-id"], format!("span-{marker}"));
        assert_eq!(value["trace"]["trace-flags"], 1);
        assert_eq!(value["trace"]["baggage"], json!([]));
        assert_eq!(value["metadata"], json!([["guest.visible", marker]]));
        assert_eq!(value["deadline"], json!({"some": "11000"}));
        assert_eq!(value["remaining"]["log-bytes"], grant.log_bytes.to_string());
        let encoded = output.to_string();
        if marker == "second" {
            assert!(
                !encoded.contains("first"),
                "previous activation context leaked across tenant reuse"
            );
        }
        for secret in [
            "private-claim",
            "private-baggage",
            "private-metadata",
            "sensitive",
        ] {
            assert!(!encoded.contains(secret));
        }
    }
    assert_eq!(backend.resource_snapshot().stores_created, 2);
    assert!(backend.log_sink().snapshot().is_empty());
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn explicit_context_policy_exposes_only_exact_claims_and_baggage() {
    let clock = Arc::new(ManualClock::new());
    let mut config = config();
    config.context_policy = ContextExposurePolicy {
        metadata_prefixes: vec!["app.".to_owned()],
        claim_keys: vec!["role".to_owned()],
        baggage_keys: vec!["locale".to_owned()],
    };
    let (backend, prepared) = prepared(config, services(&clock)).await;
    let cancellation = Cancellation::new("allowlist", &budget(), clock.sample());
    let mut request = request(&prepared, &cancellation, "snapshot", &json!([]));
    request.activation.principal.claims = Metadata::from([
        ("role".to_owned(), "reader".to_owned()),
        ("role.extra".to_owned(), "private".to_owned()),
        ("Role".to_owned(), "private".to_owned()),
    ]);
    request.activation.trace.baggage = Metadata::from([
        ("locale".to_owned(), "en".to_owned()),
        ("locale.extra".to_owned(), "private".to_owned()),
    ]);
    request.activation.metadata = Metadata::from([
        ("app.mode".to_owned(), "preview".to_owned()),
        ("guest.visible".to_owned(), "not-allowlisted".to_owned()),
    ]);
    let output = returned(run(&backend, request, &cancellation).await);
    assert_eq!(
        output[0]["principal"]["claims"],
        json!([["role", "reader"]])
    );
    assert_eq!(output[0]["trace"]["baggage"], json!([["locale", "en"]]));
    assert_eq!(output[0]["metadata"], json!([["app.mode", "preview"]]));
}

#[tokio::test]
#[ignore = "requires contracts-gate capabilities component"]
async fn remaining_budget_observes_live_guest_fuel_memory_and_host_logs() {
    let clock = Arc::new(ManualClock::new());
    let (backend, prepared) = prepared(config(), services(&clock)).await;
    let grant = budget();
    let cancellation = Cancellation::new("live-budget", &grant, clock.sample());
    let request = request(&prepared, &cancellation, "work-observe", &json!([]));
    let outcome = run(&backend, request, &cancellation).await;
    let reported = match &outcome {
        GuestOutcome::Returned { consumption, .. } => consumption.clone(),
        other => panic!("bounded work should return: {other:?}"),
    };
    let output = returned(outcome);
    let before = &output[0]["before"];
    let after = &output[0]["after"];
    assert_eq!(output[0]["checksum"], 1024);
    assert_eq!(output[0]["logged"], json!({"ok": true}));
    assert!(unsigned(&before["cpu-fuel"]) < grant.cpu_fuel);
    assert!(unsigned(&after["cpu-fuel"]) < unsigned(&before["cpu-fuel"]));
    assert!(unsigned(&before["memory-bytes"]) < grant.memory_bytes);
    assert!(unsigned(&after["memory-bytes"]) < unsigned(&before["memory-bytes"]));
    assert!(unsigned(&after["log-bytes"]) < unsigned(&before["log-bytes"]));
    let consumed = grant.log_bytes - unsigned(&after["log-bytes"]);
    let accounting = cancellation.accounting.snapshot_at(clock.monotonic_now());
    assert_eq!(accounting.log_bytes, consumed);
    assert_eq!(reported.log_bytes, consumed);
    assert!(reported.cpu_fuel >= grant.cpu_fuel - unsigned(&after["cpu-fuel"]));
    assert!(reported.peak_memory_bytes >= grant.memory_bytes - unsigned(&after["memory-bytes"]));
    assert_eq!(cancellation.accounting.outstanding_reservations(), 0);
    assert!(
        cancellation.accounting.finalized().is_none(),
        "the activation owner finalizes"
    );
}
