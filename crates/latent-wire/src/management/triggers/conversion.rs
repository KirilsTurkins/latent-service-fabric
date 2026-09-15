use super::super::proto;
use latent_control_store::http_routes::{
    TriggerOperationAction, TriggerOperationLookup, TriggerOperationReceipt, VersionedTrigger,
};
use latent_core::{ContractId, ServiceId, TenantId, TriggerId};
use latent_manifest::{
    __serde_json as json, ObjectMetadata, TriggerKind, TriggerManifest, TriggerTarget,
};
use tonic::Status;

pub(super) fn manifest(value: proto::Trigger) -> Result<TriggerManifest, Status> {
    let metadata = value
        .metadata
        .ok_or_else(|| Status::invalid_argument("trigger metadata is required"))?;
    let target = value
        .target
        .ok_or_else(|| Status::invalid_argument("trigger target is required"))?;
    let publication = target
        .publication
        .ok_or_else(|| Status::invalid_argument("explicit trigger publication is required"))?;
    Ok(TriggerManifest {
        api_version: latent_manifest::MANIFEST_API_VERSION.into(),
        id: TriggerId(value.id),
        kind: TriggerKind::Http,
        metadata: ObjectMetadata {
            name: metadata.name,
            tenant: metadata.tenant.map(TenantId),
            namespace: metadata.namespace,
            labels: metadata.labels.into_iter().collect(),
            annotations: metadata.annotations.into_iter().collect(),
        },
        target: TriggerTarget {
            service: ServiceId(target.service),
            contract: ContractId(target.contract),
            function: target.function,
            route: target.route,
            publication: Some(
                publication
                    .id
                    .parse()
                    .map_err(|_| Status::invalid_argument("invalid publication identity"))?,
            ),
            revision: target.revision,
            deployment_generation: target.deployment_generation,
        },
        configuration: value
            .configuration
            .into_iter()
            .map(|(k, v)| (k, json::Value::String(v)))
            .collect(),
    })
}
pub(super) fn trigger(value: VersionedTrigger) -> proto::Trigger {
    let m = value.manifest;
    proto::Trigger {
        id: m.id.0,
        kind: "HttpTrigger".into(),
        generation: value.generation,
        target: Some(proto::TriggerTarget {
            service: m.target.service.0,
            contract: m.target.contract.0,
            function: m.target.function,
            route: m.target.route,
            publication: m.target.publication.map(|id| proto::PublicationRef {
                id: id.into_string(),
                tenant: m
                    .metadata
                    .tenant
                    .as_ref()
                    .expect("scoped HTTP trigger")
                    .0
                    .clone(),
            }),
            revision: m.target.revision,
            deployment_generation: m.target.deployment_generation,
        }),
        configuration: m
            .configuration
            .into_iter()
            .map(|(k, v)| match v {
                json::Value::String(v) => (k, v),
                _ => unreachable!("closed stored trigger profile"),
            })
            .collect(),
        metadata: Some(proto::ObjectMetadata {
            name: m.metadata.name,
            tenant: m.metadata.tenant.map(|t| t.0),
            namespace: m.metadata.namespace,
            labels: m.metadata.labels.into_iter().collect(),
            annotations: m.metadata.annotations.into_iter().collect(),
        }),
    }
}
pub(super) fn receipt(r: TriggerOperationReceipt) -> proto::TriggerOperationReceipt {
    use latent_artifacts::ReleaseActorKind as D;
    let actor = match r.actor.kind {
        D::User => proto::ReleaseActorKind::User,
        D::Service => proto::ReleaseActorKind::Service,
        D::Node => proto::ReleaseActorKind::Node,
        D::Trigger => proto::ReleaseActorKind::Trigger,
        D::Administrator => proto::ReleaseActorKind::Administrator,
        D::Anonymous => proto::ReleaseActorKind::Anonymous,
        D::Host => proto::ReleaseActorKind::Host,
    };
    proto::TriggerOperationReceipt {
        format_version: r.format_version,
        tenant: r.tenant.clone(),
        actor: Some(proto::ReleaseActor {
            subject: r.actor.subject,
            kind: actor as i32,
        }),
        operation_id: r.operation_id,
        action: match r.action {
            TriggerOperationAction::Apply => proto::TriggerOperationAction::Apply,
            TriggerOperationAction::Delete => proto::TriggerOperationAction::Delete,
        } as i32,
        trigger_id: r.trigger_id,
        request_digest: r.request_digest,
        expected_state_version: r.expected_state_version,
        expected_generation: r.expected_generation,
        object_generation: r.object_generation,
        state_version: r.state_version,
        route_generation: r.route_generation,
        manifest_digest: r.manifest_digest,
        publication: Some(proto::PublicationRef {
            id: r.publication.id.into_string(),
            tenant: r.tenant,
        }),
        component_digest: r.component.0,
        deployment_id: r.deployment_id,
        deployment_generation: r.deployment_generation,
        revision: r.revision,
        completed_at_unix_millis: r.completed_at_unix_millis,
        receipt_digest: r.receipt_digest,
    }
}
pub(super) fn lookup(value: TriggerOperationLookup) -> proto::GetTriggerOperationResponse {
    use proto::TriggerOperationLookupDisposition as D;
    let mut output = proto::GetTriggerOperationResponse::default();
    match value {
        TriggerOperationLookup::Found(r) => {
            output.disposition = D::Found as i32;
            output.receipt = Some(receipt(r));
        }
        TriggerOperationLookup::Uncertain => output.disposition = D::Uncertain as i32,
        TriggerOperationLookup::Unknown {
            retained_floor,
            high_watermark,
        } => {
            output.disposition = D::Unknown as i32;
            output.retained_floor = retained_floor;
            output.high_watermark = high_watermark;
        }
    }
    output
}
