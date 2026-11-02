//! Finite, typed operator workflow. Every mutation is one RPC, never a retry loop.
mod execute;
mod prepare;
#[cfg(test)]
mod tests;
pub use execute::execute;
use latent_rpc::control::v1 as proto;
pub use prepare::{prepare, validate_arguments};
use prost::Message;
pub enum MaintenanceOperation {
    Snapshot(proto::GetPublicationRetentionRequest),
    Maintain(proto::MaintainPublicationsRequest),
    Assess(proto::AssessPublicationReclamationRequest),
    Lookup(proto::GetPublicationMaintenanceOperationRequest),
}
impl MaintenanceOperation {
    pub fn encoded_len(&self) -> usize {
        match self {
            Self::Snapshot(v) => v.encoded_len(),
            Self::Maintain(v) => v.encoded_len(),
            Self::Assess(v) => v.encoded_len(),
            Self::Lookup(v) => v.encoded_len(),
        }
    }
    pub fn recovery(&self) -> Option<serde_json::Value> {
        let Self::Maintain(request) = self else {
            return None;
        };
        let command = request.command.as_ref()?;
        let selection = command.selection.as_ref()?;
        Some(
            serde_json::json!({"family":"publication-maintenance", "kind":proto::PublicationMaintenanceKind::try_from(command.kind).ok()?.as_str_name(), "operationId":selection.operation_id, "originalCatalogFence":hex(&selection.catalog_fence), "reclamationCatalogFence":(!command.reclamation_catalog_fence.is_empty()).then(||hex(&command.reclamation_catalog_fence)), "automaticReplay":false}),
        )
    }
}
pub(super) fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut value = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        value.push(HEX[(b >> 4) as usize] as char);
        value.push(HEX[(b & 15) as usize] as char);
    }
    value
}
fn invalid() -> crate::error::Failure {
    crate::error::Failure::local("invalid-publication-maintenance", "Supply 1–32 unique exact publications, positive generations, an explicit operation ID, canonical catalog fences and finite work limits. Preserve the original delete request for assessment and reclamation.")
}
