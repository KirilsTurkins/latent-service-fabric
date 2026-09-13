use super::{validate_builder_id, BuilderRequirement};
use crate::{
    provenance, BuildObservation, SignatureFailure, SignatureResult, PROVENANCE_BUILD_TYPE,
};

pub(super) fn validate(requirements: &mut [BuilderRequirement]) -> SignatureResult<()> {
    for item in requirements.iter() {
        validate_builder_id(&item.builder_id).map_err(|_| SignatureFailure::InvalidPolicy)?;
        if item.build_type != PROVENANCE_BUILD_TYPE {
            return Err(SignatureFailure::InvalidPolicy.into());
        }
        provenance::validate_repository(&item.source_repository)
            .map_err(|_| SignatureFailure::InvalidPolicy)?;
        if let Some(revision) = &item.source_revision {
            provenance::validate_revision(revision).map_err(|_| SignatureFailure::InvalidPolicy)?;
        }
        if let Some(digest) = &item.source_snapshot_digest {
            provenance::validate_digest(digest).map_err(|_| SignatureFailure::InvalidPolicy)?;
        }
    }
    requirements.sort();
    if requirements.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(SignatureFailure::InvalidPolicy.into());
    }
    Ok(())
}

pub(crate) fn authorize(
    requirements: &[BuilderRequirement],
    builder: &str,
    observation: &BuildObservation,
) -> SignatureResult<()> {
    let mut known_builder = false;
    let mut known_predicate = false;
    for item in requirements {
        if item.builder_id != builder {
            continue;
        }
        known_builder = true;
        if item.build_type != observation.build_type {
            continue;
        }
        known_predicate = true;
        if item.source_repository == observation.source.repository
            && item
                .source_revision
                .as_ref()
                .is_none_or(|revision| revision == &observation.source.revision)
            && item
                .source_snapshot_digest
                .as_ref()
                .is_none_or(|digest| digest == &observation.source.snapshot_digest)
            && (!item.require_reproducible
                || observation.reproducibility == "two-build-byte-equality")
        {
            return Ok(());
        }
    }
    Err(if !known_builder {
        SignatureFailure::UntrustedBuilder
    } else if !known_predicate {
        SignatureFailure::PredicateDisallowed
    } else {
        SignatureFailure::SourceDisallowed
    }
    .into())
}
