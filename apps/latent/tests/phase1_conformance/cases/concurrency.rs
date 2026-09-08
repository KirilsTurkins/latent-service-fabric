#[path = "concurrency/queue.rs"]
mod queue;
#[path = "concurrency/route.rs"]
mod route;

pub use queue::queue_admission;
pub use route::route_update;

use crate::{
    fixtures::Package,
    harness::{invoke_args, Harness, PendingCli},
};
use serde_json::Value;
use std::path::Path;
use std::time::{Duration, Instant};

fn spin(harness: &mut Harness, package: &Package, id: &str, input: &Path) -> PendingCli {
    let mut args = invoke_args(package, "spin", id, input);
    args.extend_from_slice(&["--wall-time-ms", "3000", "--cpu-fuel", "10000000000"]);
    harness.spawn_cli(package.profile(), &args)
}

async fn phase(harness: &mut Harness, profile: &str, id: &str, expected: &str) -> Value {
    let deadline = Instant::now()
        .checked_add(Duration::from_secs(2))
        .expect("phase watchdog");
    for _ in 0..20 {
        assert!(
            Instant::now() < deadline,
            "bounded phase observation expired"
        );
        let pending = harness.spawn_cli(profile, &["activation", "get", id]);
        if let Some(status) = harness.finish_status_poll(pending).await {
            assert!(
                status["data"]["terminalState"].is_null(),
                "pending invocation ended before observation"
            );
            if status["data"]["phase"] == expected {
                return status;
            }
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("expected pending phase missing after bounded status commands");
}

async fn cancel(harness: &mut Harness, id: &str) -> Value {
    let response = harness
        .call("tests", &["activation", "cancel", id], 0, "success")
        .await;
    assert_eq!(response["data"]["disposition"], "accepted");
    response
}
