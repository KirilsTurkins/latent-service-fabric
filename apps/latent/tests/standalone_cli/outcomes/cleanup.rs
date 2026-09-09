use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::support::{Harness, NODE_ID};

pub(super) fn wait_idle(harness: &Harness) -> Value {
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(2))
        .expect("cleanup slot observation bound");
    for _ in 0..20 {
        assert!(Instant::now() < deadline, "cleanup slot was not refunded");
        let inventory = harness.call("operator", &["node", "get", NODE_ID], 0, "success");
        let entries = inventory["data"]["inventory"]["topology"]["entries"]
            .as_array()
            .expect("actual node topology");
        let driver = entries
            .iter()
            .find(|entry| entry["name"] == "invocation-cleanup-driver")
            .expect("owned cleanup driver");
        assert_eq!(driver["activeCount"], "1");
        let slots = entries
            .iter()
            .find(|entry| entry["name"] == "invocation-cleanup-slots")
            .expect("finite cleanup slots");
        // Terminal publication can precede destruction of the continuation.
        if slots["activeCount"] == "0" {
            return inventory;
        }
        thread::sleep(Duration::from_millis(10));
    }
    panic!("cleanup continuation remained owned after terminal publication");
}

pub(super) fn assert_joined(stopped: &Value) {
    let report = &stopped["report"];
    assert_eq!(report["quarantinedCells"], 0);
    let cleanup = &report["cleanup"];
    assert_eq!(cleanup["accepting"], false);
    assert_eq!(cleanup["driverAlive"], false);
    assert_eq!(cleanup["driverJoined"], true);
    assert_eq!(cleanup["failed"], false);
    assert_eq!(
        cleanup["handoffs"], 1,
        "only the actual Running CLI interruption transfers its owner"
    );
    assert_eq!(cleanup["completed"], 1);
    for field in [
        "reserved",
        "queued",
        "running",
        "timedOut",
        "panicked",
        "fallbacks",
    ] {
        assert_eq!(cleanup[field], 0, "{field}");
    }
}
