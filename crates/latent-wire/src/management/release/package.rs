use latent_artifacts::{AdmissionEvidence, PackageAdmissionUpload};
use tonic::Status;

use super::super::{proto, ManagementLimits, RequestBudget};

// Fixed transport profile ceilings intersect the existing aggregate management
// request bound. The repository/authority may impose additional lower limits.
const MAX_DOCUMENT_BYTES: usize = 256 * 1024;
const MAX_LAYERS: usize = 256;
const MAX_EVIDENCE: usize = 8;

pub(super) fn validate(
    upload: &proto::PackageAdmissionUpload,
    budget: &mut RequestBudget,
    limits: &ManagementLimits,
) -> Result<(), Status> {
    let document_limit = MAX_DOCUMENT_BYTES.min(limits.max_manifest_bytes);
    for bytes in [&upload.manifest, &upload.configuration] {
        budget.bytes(bytes, document_limit)?;
        required(bytes)?;
    }
    budget.sequence(
        &upload.layers,
        MAX_LAYERS.min(limits.max_collection_entries),
    )?;
    // Conversion moves buffers, but both input/output slot vectors coexist.
    budget.allocation::<(String, Vec<u8>)>(upload.layers.len())?;
    if upload.layers.is_empty() {
        return Err(Status::invalid_argument("package layers are required"));
    }
    for layer in &upload.layers {
        budget.string(&layer.path, 240.min(limits.max_string_bytes))?;
        super::super::identifier(&layer.path, 240.min(limits.max_string_bytes))?;
        budget.bytes(&layer.data, limits.max_component_bytes)?;
    }
    for (entries, payload_limit) in [
        (&upload.signatures, 4096),
        (&upload.provenance, 49_152),
        (&upload.sboms, 1024 * 1024),
    ] {
        budget.sequence(entries, MAX_EVIDENCE.min(limits.max_collection_entries))?;
        budget.allocation::<AdmissionEvidence>(entries.len())?;
        for entry in entries {
            budget.bytes(&entry.manifest, document_limit)?;
            budget.bytes(&entry.configuration, 2)?;
            budget.bytes(&entry.payload, payload_limit)?;
            for bytes in [&entry.manifest, &entry.configuration, &entry.payload] {
                required(bytes)?;
            }
        }
    }
    Ok(())
}

fn required(bytes: &[u8]) -> Result<(), Status> {
    if bytes.is_empty() {
        return Err(Status::invalid_argument("package document is required"));
    }
    Ok(())
}

pub(super) fn into_upload(
    upload: proto::PackageAdmissionUpload,
) -> Result<PackageAdmissionUpload, Status> {
    let mut layers = Vec::new();
    layers
        .try_reserve_exact(upload.layers.len())
        .map_err(|_| super::super::bounds::exhausted())?;
    for layer in upload.layers {
        layers.push((layer.path, layer.data));
    }
    Ok(PackageAdmissionUpload {
        manifest: upload.manifest,
        configuration: upload.configuration,
        layers,
        signatures: evidence(upload.signatures)?,
        provenance: evidence(upload.provenance)?,
        sboms: evidence(upload.sboms)?,
    })
}

fn evidence(
    entries: Vec<proto::PackageAdmissionEvidence>,
) -> Result<Vec<AdmissionEvidence>, Status> {
    let mut output = Vec::new();
    output
        .try_reserve_exact(entries.len())
        .map_err(|_| super::super::bounds::exhausted())?;
    for entry in entries {
        output.push(AdmissionEvidence {
            manifest: entry.manifest,
            configuration: entry.configuration,
            payload: entry.payload,
        });
    }
    Ok(output)
}
