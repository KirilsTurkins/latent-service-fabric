use latent_core::{Metadata, PublicationId};
use latent_executor::ExecutionRequest;

pub(super) const KEY: &str = "guest.lsf.web-publication";

pub(super) fn selected(request: &ExecutionRequest) -> Option<&PublicationId> {
    if request.activation.target.contract.0 != latent_artifacts::web::WEB_CONTRACT
        || request.activation.target.function.0 != "handle"
    {
        return None;
    }
    let publication = request.prepared.key.publication.as_ref()?;
    let revision = request.activation.resolved_revision.as_ref()?;
    (revision.publication.as_ref() == Some(publication)
        && revision.release == request.prepared.key.release)
        .then_some(publication)
}

pub(super) fn bind(mut metadata: Metadata, publication: Option<PublicationId>) -> Metadata {
    metadata.remove(KEY);
    if let Some(publication) = publication {
        metadata.insert(KEY.to_owned(), publication.to_string());
    }
    metadata
}
