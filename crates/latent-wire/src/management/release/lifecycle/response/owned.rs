use super::{conversion, proto};
use latent_artifacts::{
    ReleaseActor, ReleaseLifecycleRecord, ReleaseOperationReceipt, ReleasePolicyIdentity,
};

fn actor(value: &ReleaseActor) -> proto::ReleaseActor {
    proto::ReleaseActor {
        subject: value.subject.clone(),
        kind: conversion::release_actor_kind(value.kind),
    }
}
fn policy(value: &ReleasePolicyIdentity) -> proto::ReleasePolicyIdentity {
    proto::ReleasePolicyIdentity {
        scope: value.scope.clone(),
        generation: value.generation,
        digest: value.digest.as_str().to_owned(),
    }
}
pub(super) fn record(value: &ReleaseLifecycleRecord) -> proto::ReleaseLifecycleRecord {
    proto::ReleaseLifecycleRecord {
        tenant: value
            .scope
            .tenant()
            .expect("checked tenant scope")
            .0
            .clone(),
        component_digest: value.release.0.clone(),
        package_digest: value.package.as_ref().map(|v| v.as_str().to_owned()),
        state: conversion::release_lifecycle_state(value.state),
        generation: value.generation,
        actor: Some(actor(&value.actor)),
        reason: conversion::release_lifecycle_reason(value.reason),
        operation_id: value.operation_id.clone(),
        policy: value.policy.as_ref().map(policy),
        observed_at_unix_millis: value.observed_at_unix_millis,
        evidence_revision_digest: value
            .evidence_revision_digest
            .as_ref()
            .map(|v| v.as_str().to_owned()),
    }
}
pub(super) fn receipt(value: &ReleaseOperationReceipt) -> proto::ReleaseOperationReceipt {
    proto::ReleaseOperationReceipt {
        operation_id: value.operation_id.clone(),
        request_digest: value.request_digest.as_str().to_owned(),
        tenant: value
            .scope
            .tenant()
            .expect("checked tenant scope")
            .0
            .clone(),
        actor: Some(actor(&value.actor)),
        action: conversion::release_lifecycle_action(value.action),
        disposition: conversion::release_operation_disposition(value.disposition),
        reason: conversion::release_lifecycle_reason(value.reason),
        component_digest: value.component_digest.as_ref().map(|v| v.0.clone()),
        package_manifest_digest: value
            .package_manifest_digest
            .as_ref()
            .map(|v| v.as_str().to_owned()),
        expected_generation: value.expected_generation,
        record: value.record.as_ref().map(record),
        policy: value.policy.as_ref().map(policy),
        observed_at_unix_millis: value.observed_at_unix_millis,
    }
}
