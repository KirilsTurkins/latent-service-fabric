use super::*;
use serde_json::json;

pub(in super::super) fn fixture() -> Plan {
    serde_json::from_value(json!({
        "schema":"latent.optimization.client-plan.v1","run_id":"test-run","arm":"lsf",
        "server_process_id":123,"endpoint":"http://127.0.0.1:1","token_file":"private-token",
        "tenant":"tests","services":["alpha","beta"],"contract":"optimization:benchmark/workloads@0.1.0",
        "route":null,"function":"echo","payload":["test"],"warmup_attempts":2,"measured_attempts":4,
        "batch_size":2,"concurrency":2,"runtime_workers":2,"schedule":{"mode":"closed-loop"},
        "budget_millis":1000,"cpu_fuel":10000000,"memory_bytes":16777216,"log_bytes":0,
        "connect_timeout_millis":1000,"response_timeout_millis":1000,"maximum_output_bytes":16777216
    }))
    .unwrap()
}

#[test]
fn plan_preflight_computes_exact_parity_and_removes_private_input_locations() {
    let plan = fixture();
    let prepared = plan.prepare().unwrap();
    assert_eq!(prepared.payload, br#"["test"]"#);
    assert_eq!(prepared.expected, prepared.payload);
    for key in ["token_file", "endpoint", "payload"] {
        assert!(prepared.public_plan.get(key).is_none());
    }
    assert_eq!(prepared.public_plan["services"], json!(["alpha", "beta"]));
    assert_eq!(
        prepared.public_plan["payload_sha256"],
        record::digest(&prepared.payload)
    );
}

#[test]
fn work_and_output_limits_reject_before_connecting() {
    let mut plan = fixture();
    plan.concurrency = 65;
    assert!(plan.validate().is_err());
    plan.concurrency = 2;
    plan.maximum_output_bytes = 1024;
    assert!(plan.validate().is_err());
    plan.maximum_output_bytes = 16 * 1024 * 1024;
    plan.schedule = Schedule::Scheduled {
        interval_nanos: u64::MAX,
    };
    assert!(plan.validate().is_err());
    plan.schedule = Schedule::Scheduled { interval_nanos: 1 };
    plan.budget_millis = 5001;
    assert!(plan.validate().is_err());
}

#[test]
fn every_requested_short_budget_and_slack_budget_is_valid() {
    let mut plan = fixture();
    for budget in [1, 2, 5, 10, 1000, 5000] {
        plan.budget_millis = budget;
        plan.response_timeout_millis = budget.max(1000);
        assert!(plan.prepare().is_ok(), "{budget}");
    }
}

#[test]
fn malformed_workload_and_unknown_plan_fields_are_rejected() {
    let mut plan = fixture();
    plan.function = "compute".into();
    plan.payload = json!([1, 1000001]);
    assert_eq!(plan.prepare().err(), Some("invalid-workload-input"));
    let mut value = serde_json::to_value(plan).unwrap();
    value["retry_count"] = json!(1);
    assert!(serde_json::from_value::<Plan>(value).is_err());
}
