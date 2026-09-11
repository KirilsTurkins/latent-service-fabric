use serde_json::{json, Value};

use super::{assert_idle, cycle};

#[test]
fn full_warmup_exercises_every_measured_fault_family() {
    let mut counts = std::collections::BTreeMap::new();
    for index in 0..1000 {
        *counts.entry(cycle(index).name()).or_insert(0_u32) += 1;
    }
    assert_eq!(counts.remove("success"), Some(450));
    assert_eq!(counts.len(), 11);
    for case in [
        "domain",
        "trap",
        "fuel",
        "memory",
        "deadline",
        "cancel",
        "malformed",
        "log_denied",
        "log_accepted",
        "context",
        "fresh_store",
    ] {
        assert_eq!(counts[case], 50, "missing mixed warmup family {case}");
    }
}

#[test]
fn bounded_retention_is_allowed_but_active_owners_or_missing_observations_fail() {
    let baseline = idle();
    assert_idle(&baseline).unwrap();
    for (owner, field, value) in [
        ("cancellation", "active_registrations", json!("1")),
        ("journal", "reserved_bytes", json!("1")),
        ("observer", "active_correlations", json!("1")),
        ("sink", "retained_bytes", json!("1025")),
        ("pipeline", "queue_depth", json!("5")),
        ("journal", "terminal", Value::Null),
    ] {
        let mut sample = baseline.clone();
        sample["ownership"][owner][field] = value;
        assert!(
            assert_idle(&sample).is_err(),
            "unchecked ownership {owner}.{field}"
        );
    }
}

fn idle() -> Value {
    json!({"backend":{"active_invocations":"0","live_stores":"0","live_host_states":"0",
        "live_component_instances":"0","live_temporary_buffers":"0","live_cancellation_probes":"0"},
        "inventory":{"cellCapacity":[{"active":0,"queueDepth":0,"quarantined":0}],"cacheSummary":{"preparing":"0"},
            "quotas":{"usage":{"activeActivations":0,"queuedActivations":0,"reservedCpuFuel":"0","reservedMemoryBytes":"0"}}},
        "ownership":{"cancellation":{"active_registrations":"0"},"observer":{"active_correlations":"0"},
            "journal":{"active":"0","reserved_bytes":"0","terminal":"4","maximum_terminal":"4","retained_bytes":"128","maximum_retained_bytes":"256"},
            "sink":{"entries":"2","maximum_entries":"2","retained_bytes":"1024","maximum_bytes":"1024"},
            "pipeline":{"queue_depth":"2","queue_capacity":"4"}}})
}
