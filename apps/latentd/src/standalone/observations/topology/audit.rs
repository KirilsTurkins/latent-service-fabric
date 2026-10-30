//! One fixed, read-only view of the existing journal owner. No audit append,
//! filesystem probe, background collector or mutation reservation is performed.
use latent_audit::{AuditHandle, AuditLimits, AuditSnapshot};

use super::{count, Metadata, NodeTopologyEntry, ResourceOwnership};

pub(super) fn entry(handle: Option<&AuditHandle>) -> NodeTopologyEntry {
    let attributes = handle.map_or_else(
        || {
            let mut attributes = Metadata::new();
            attributes.insert("profile".into(), "audit-capacity-v1".into());
            attributes.insert("measurementStatus".into(), "not-configured".into());
            attributes
        },
        |handle| measurements(handle.limits(), handle.snapshot()),
    );
    NodeTopologyEntry {
        name: "audit-journal".into(),
        kind: "store".into(),
        ownership: ResourceOwnership::NodeFixed,
        configured_count: u64::from(handle.is_some()),
        // A retained handle is not a measurement of a live filesystem worker.
        active_count: None,
        attributes,
    }
}

pub(super) fn measurements(limits: AuditLimits, snapshot: AuditSnapshot) -> Metadata {
    let mut attributes = Metadata::new();
    attributes.insert("profile".into(), "audit-capacity-v1".into());
    attributes.insert("measurementStatus".into(), "available".into());
    for (name, value) in [
        ("maximumRecords", count(limits.maximum_records)),
        ("maximumDiskBytes", count(limits.maximum_disk_bytes)),
        ("maximumRecordBytes", count(limits.maximum_record_bytes)),
        (
            "maximumQueuedOperations",
            count(limits.maximum_queued_operations),
        ),
        ("maximumQueuedBytes", count(limits.maximum_queued_bytes)),
        ("maximumQueryOwners", count(limits.maximum_query_owners)),
        ("audit_retained_records", count(snapshot.retained_records)),
        ("audit_retained_bytes", count(snapshot.retained_bytes)),
        ("audit_reserved_records", count(snapshot.reserved_records)),
        ("audit_reserved_bytes", count(snapshot.reserved_bytes)),
        ("audit_queued_operations", count(snapshot.queued_operations)),
        ("audit_queued_bytes", count(snapshot.queued_bytes)),
        ("audit_pending_attempts", count(snapshot.pending_attempts)),
        ("audit_query_owners", count(snapshot.query_owners)),
        ("audit_query_bytes", count(snapshot.query_bytes)),
        ("audit_stage_bytes", count(snapshot.stage_bytes)),
        (
            "audit_node_metadata_maximum_bytes",
            count(snapshot.node_metadata_maximum_bytes),
        ),
        (
            "audit_node_metadata_reserved_bytes",
            count(snapshot.node_metadata_reserved_bytes),
        ),
        (
            "audit_node_metadata_quarantined_reserved_bytes",
            count(snapshot.node_metadata_quarantined_reserved_bytes),
        ),
        ("audit_closed", u64::from(snapshot.closed)),
        (
            "audit_recovery_pending",
            u64::from(snapshot.recovery_pending),
        ),
        ("audit_next_sequence", snapshot.next_sequence),
        ("audit_unknown_outcomes", snapshot.unknown_outcomes),
        ("audit_dropped_observations", snapshot.dropped_observations),
        ("audit_unavailable_events", snapshot.unavailable_events),
        (
            "audit_previous_session_loss_unknown",
            u64::from(snapshot.previous_session_loss_unknown),
        ),
    ] {
        attributes.insert(name.into(), value.to_string());
    }
    attributes
}
