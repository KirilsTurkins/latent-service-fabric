use super::{capacity, count, row, ResourceOwnership, Row};

pub(super) fn policy_rows(
    maximum_jobs: usize,
    active_jobs: usize,
    maximum_read_owners: usize,
    retained_read_owners: usize,
) -> [Row; capacity::POLICY_ROWS] {
    [
        row(
            "capability-policy-control-jobs",
            "command",
            ResourceOwnership::NodeFixed,
            count(maximum_jobs),
            Some(count(active_jobs)),
        ),
        row(
            "capability-policy-read-owners",
            "response-or-snapshot",
            ResourceOwnership::NodeFixed,
            count(maximum_read_owners + 4),
            Some(count(retained_read_owners)),
        ),
    ]
}

pub(super) fn http_rows(s: crate::standalone::http::HttpSnapshot) -> [Row; capacity::HTTP_ROWS] {
    [
        row(
            "http-listener",
            "listener",
            ResourceOwnership::NodeFixed,
            1,
            Some(u64::from(s.listener_alive)),
        ),
        row(
            "http-owner",
            "task",
            ResourceOwnership::NodeFixed,
            1,
            Some(u64::from(s.owner_alive)),
        ),
        row(
            "http-connections",
            "connection",
            ResourceOwnership::NodeFixed,
            count(s.maximum_connections),
            Some(count(s.connections)),
        ),
        row(
            "http-exchanges",
            "exchange",
            ResourceOwnership::NodeFixed,
            count(s.maximum_exchanges),
            Some(count(s.exchanges)),
        ),
        row(
            "http-buffer-reservations",
            "byte",
            ResourceOwnership::NodeFixed,
            count(s.maximum_buffer_bytes),
            Some(count(s.reserved_buffer_bytes)),
        ),
    ]
}

pub(super) fn rollout_rows(
    maximum_queued_commands: usize,
    snapshot: latent_rollout::CoordinatorSnapshot,
) -> [Row; capacity::ROLLOUT_ROWS] {
    [
        row(
            "rollout-coordinator",
            "blocking-task",
            ResourceOwnership::NodeFixed,
            1,
            Some(u64::from(snapshot.worker_live)),
        ),
        row(
            "rollout-control-commands",
            "command",
            ResourceOwnership::NodeFixed,
            count(maximum_queued_commands.saturating_add(1)),
            Some(count(snapshot.queued_commands + snapshot.active_commands)),
        ),
    ]
}

pub(super) fn canary_rows(
    limits: latent_telemetry::Phase2CanaryOutcomeWindowConfig,
    snapshot: latent_telemetry::Phase2CanaryWindowSnapshot,
) -> [Row; capacity::CANARY_ROWS] {
    [
        row(
            "canary-observation-windows",
            "window",
            ResourceOwnership::NodeFixed,
            count(limits.maximum_series),
            Some(count(snapshot.tracked_series)),
        ),
        row(
            "canary-retained-samples",
            "sample",
            ResourceOwnership::NodeFixed,
            count(limits.maximum_total_samples),
            Some(count(snapshot.total_samples)),
        ),
        row(
            "canary-live-samples",
            "sample",
            ResourceOwnership::NodeFixed,
            count(limits.maximum_live_samples),
            Some(count(snapshot.live_samples)),
        ),
        row(
            "canary-snapshot-owners",
            "snapshot",
            ResourceOwnership::NodeFixed,
            count(limits.maximum_snapshot_owners),
            Some(count(snapshot.snapshot_owners)),
        ),
    ]
}
