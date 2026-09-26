mod execute;
mod prepare;
#[cfg(test)]
mod tests;

use latent_rpc::control::v1 as proto;
use prost::Message;

pub use execute::execute;
pub use prepare::prepare;

pub enum WebOperation {
    Publish(proto::PublishWebPackageRequest),
    Get(proto::GetWebPublicationRequest),
    Prepare(proto::PrepareWebPublicationRequest),
    Operation(proto::GetWebOperationRequest),
    Change(proto::ChangeWebLifecycleRequest),
    Renew(proto::RenewWebEvidenceRequest),
}

impl WebOperation {
    pub fn recovery(&self) -> Option<serde_json::Value> {
        let (operation, publication) = match self {
            Self::Publish(request) => (request.operation.as_ref(), None),
            Self::Change(request) => (request.operation.as_ref(), request.publication.as_ref()),
            Self::Renew(request) => (request.operation.as_ref(), request.publication.as_ref()),
            Self::Get(_) | Self::Prepare(_) | Self::Operation(_) => return None,
        };
        operation.map(|operation| {
            serde_json::json!({
                "family": "web",
                "operationId": operation.operation_id,
                "publicationId": publication.map(|reference| &reference.id),
                "expectedGeneration": operation.expected_generation.map(|value| value.to_string()),
            })
        })
    }

    pub fn encoded_len(&self) -> usize {
        match self {
            Self::Publish(request) => request.encoded_len(),
            Self::Get(request) => request.encoded_len(),
            Self::Prepare(request) => request.encoded_len(),
            Self::Operation(request) => request.encoded_len(),
            Self::Change(request) => request.encoded_len(),
            Self::Renew(request) => request.encoded_len(),
        }
    }
}

pub(super) fn publication(
    package: &latent_core::PackageDigest,
    tenant: &str,
) -> Result<proto::PublicationRef, crate::error::Failure> {
    let reference = latent_artifacts::PublicationRef::package(
        latent_artifacts::LifecycleScope::Tenant(latent_core::TenantId(tenant.to_owned())),
        package,
    )
    .map_err(|_| super::invalid_response())?;
    Ok(proto::PublicationRef {
        id: reference.id.as_str().to_owned(),
        tenant: tenant.to_owned(),
    })
}

fn invalid_input() -> crate::error::Failure {
    crate::error::Failure::local(
        "invalid-web-control-input",
        "One exact web publication and bounded operation are required.",
    )
}
