use super::super::proto;
use latent_control_store::http_routes::{
    TriggerOperationAction, TriggerOperationLookup, TriggerOperationReceipt, VersionedTrigger,
};
use latent_core::{ContractId, ServiceId, TenantId, TriggerId};
use latent_manifest::{
    __serde_json as json, ApplicationTriggerTarget, ObjectMetadata, StaticWebTriggerTarget,
    TriggerKind, TriggerManifest, TriggerTarget,
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
    let publication = publication
        .id
        .parse()
        .map_err(|_| Status::invalid_argument("invalid publication identity"))?;
    let target = match proto::TriggerTargetKind::try_from(target.kind)
        .map_err(|_| Status::invalid_argument("invalid trigger target kind"))?
    {
        proto::TriggerTargetKind::StaticWeb => {
            TriggerTarget::StaticWeb(StaticWebTriggerTarget { publication })
        }
        proto::TriggerTargetKind::Unspecified | proto::TriggerTargetKind::Application => {
            TriggerTarget::Application(ApplicationTriggerTarget {
                service: ServiceId(target.service),
                contract: ContractId(target.contract),
                function: target.function,
                route: target.route,
                publication: Some(publication),
                revision: target.revision,
                deployment_generation: target.deployment_generation,
            })
        }
    };
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
        target,
        configuration: value
            .configuration
            .into_iter()
            .map(|(k, v)| (k, json::Value::String(v)))
            .collect(),
    })
}
pub(super) fn trigger(value: VersionedTrigger) -> proto::Trigger {
    manifest_to_proto(value.manifest, value.generation)
}
pub(super) fn manifest_to_proto(manifest: TriggerManifest, generation: u64) -> proto::Trigger {
    proto::Trigger {
        id: manifest.id.0,
        kind: "HttpTrigger".into(),
        generation,
        target: Some(match manifest.target {
            TriggerTarget::Application(target) => proto::TriggerTarget {
                service: target.service.0,
                contract: target.contract.0,
                function: target.function,
                route: target.route,
                publication: target.publication.map(|publication| proto::PublicationRef {
                    id: publication.into_string(),
                    tenant: manifest
                        .metadata
                        .tenant
                        .as_ref()
                        .expect("scoped HTTP trigger")
                        .0
                        .clone(),
                }),
                revision: target.revision,
                deployment_generation: target.deployment_generation,
                kind: proto::TriggerTargetKind::Application as i32,
            },
            TriggerTarget::StaticWeb(target) => proto::TriggerTarget {
                publication: Some(proto::PublicationRef {
                    id: target.publication.into_string(),
                    tenant: manifest
                        .metadata
                        .tenant
                        .as_ref()
                        .expect("scoped HTTP trigger")
                        .0
                        .clone(),
                }),
                kind: proto::TriggerTargetKind::StaticWeb as i32,
                ..Default::default()
            },
        }),
        configuration: manifest
            .configuration
            .into_iter()
            .map(|(key, value)| match value {
                json::Value::String(value) => (key, value),
                _ => unreachable!("closed stored trigger profile"),
            })
            .collect(),
        metadata: Some(proto::ObjectMetadata {
            name: manifest.metadata.name,
            tenant: manifest.metadata.tenant.map(|tenant| tenant.0),
            namespace: manifest.metadata.namespace,
            labels: manifest.metadata.labels.into_iter().collect(),
            annotations: manifest.metadata.annotations.into_iter().collect(),
        }),
    }
}
pub(super) fn receipt(r: TriggerOperationReceipt) -> proto::TriggerOperationReceipt {
    use latent_artifacts::ReleaseActorKind as D;
    use latent_control_store::http_routes::TriggerTargetIdentity;
    let actor = match r.actor.kind {
        D::User => proto::ReleaseActorKind::User,
        D::Service => proto::ReleaseActorKind::Service,
        D::Node => proto::ReleaseActorKind::Node,
        D::Trigger => proto::ReleaseActorKind::Trigger,
        D::Administrator => proto::ReleaseActorKind::Administrator,
        D::Anonymous => proto::ReleaseActorKind::Anonymous,
        D::Host => proto::ReleaseActorKind::Host,
    };
    let tenant = r.tenant.clone();
    let target = r.target.clone().map(|target| match target {
        TriggerTargetIdentity::Application {
            publication,
            component,
            deployment_id,
            deployment_generation,
            revision,
        } => proto::TriggerReceiptTarget {
            kind: proto::TriggerReceiptTargetKind::Application as i32,
            publication: Some(proto::PublicationRef {
                id: publication.id.into_string(),
                tenant: tenant.clone(),
            }),
            component_digest: component.0,
            deployment_id,
            deployment_generation,
            revision,
            ..Default::default()
        },
        TriggerTargetIdentity::StaticWeb {
            publication,
            web_manifest_digest,
            assets_digest,
            web_generation,
        } => proto::TriggerReceiptTarget {
            kind: proto::TriggerReceiptTargetKind::StaticWeb as i32,
            publication: Some(proto::PublicationRef {
                id: publication.id.into_string(),
                tenant: tenant.clone(),
            }),
            web_manifest_digest,
            assets_digest,
            web_generation,
            ..Default::default()
        },
    });
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
        publication: r.publication.map(|publication| proto::PublicationRef {
            id: publication.id.into_string(),
            tenant,
        }),
        component_digest: r
            .component
            .map_or_else(String::new, |component| component.0),
        deployment_id: r.deployment_id.unwrap_or_default(),
        deployment_generation: r.deployment_generation.unwrap_or_default(),
        revision: r.revision.unwrap_or_default(),
        completed_at_unix_millis: r.completed_at_unix_millis,
        receipt_digest: r.receipt_digest,
        target,
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
