use super::{
    association,
    budget::{Budget, Owned},
    limit, Failure, MAX_PACKAGE, PACKAGE_RESERVATION,
};
use crate::args::PackagePushArgs;
use latent_artifacts::{
    package::{decode_referrer, EvidenceKind, PackageSubject, OCI_MANIFEST_MEDIA_TYPE},
    AdmissionEvidence, ReleaseEvidenceUpload,
};
use latent_core::PackageDigest;
use latent_oci::{OciManifestBytes, OciPushRequest, OciReference};
use latent_packaging::{BundleInput, PackageBundle};
use serde_json::Value;

pub(super) struct Push {
    pub package: Owned<OciPushRequest>,
    pub evidence: Owned<Vec<OciPushRequest>>,
    pub summary: Value,
}
pub(super) fn prepare(
    args: &PackagePushArgs,
    mut reference: OciReference,
    budget: &Budget,
) -> Result<Push, Failure> {
    let package_charge = budget.reserve(PACKAGE_RESERVATION)?;
    let package = super::super::read(&args.directory)?;
    if package_size(&package) > MAX_PACKAGE {
        return Err(limit());
    }
    let subject = subject(&package);
    let summary = super::super::summary(&package);
    let evidence_charge = budget.reserve(super::super::MAX_EVIDENCE)?;
    let evidence = match (&args.evidence_index, &args.evidence_root) {
        (Some(index), Some(root)) => super::super::evidence(index, root, &subject.digest)?,
        (None, None) => ReleaseEvidenceUpload::default(),
        _ => return Err(association()),
    };
    let selected = [
        (EvidenceKind::Signature, evidence.signatures),
        (EvidenceKind::Provenance, evidence.provenance),
        (EvidenceKind::Sbom, evidence.sboms),
    ];
    let mut requests = Vec::with_capacity(selected.iter().map(|(_, entries)| entries.len()).sum());
    for (kind, entries) in selected {
        for entry in entries {
            requests.push(evidence_request(reference.clone(), entry, kind, &subject)?);
        }
    }
    reference.reference.clone_from(&args.reference);
    let descriptors = package.layout().manifest().layers.clone();
    let paths = package
        .layout()
        .config()
        .layers
        .iter()
        .map(|layer| layer.path.clone())
        .collect::<Vec<_>>();
    let mut input = package.into_input();
    let layers = descriptors
        .into_iter()
        .zip(paths)
        .map(|(descriptor, path)| {
            let index = input
                .layers
                .iter()
                .position(|(name, _)| *name == path)
                .ok_or_else(association)?;
            Ok((descriptor, input.layers.swap_remove(index).1))
        })
        .collect::<Result<Vec<_>, Failure>>()?;
    let manifest = OciManifestBytes::new(
        input.manifest,
        super::super::limits().package.max_document_bytes,
    )
    .map_err(super::super::failure)?;
    if let Ok(expected) = reference.reference.parse::<PackageDigest>() {
        if expected != *manifest.digest() {
            return Err(association());
        }
    }
    let request = OciPushRequest::new(
        reference,
        manifest,
        input.configuration,
        layers,
        super::super::limits().package,
    )
    .map_err(super::super::failure)?;
    Ok(Push {
        package: package_charge.own(request),
        evidence: evidence_charge.own(requests),
        summary,
    })
}
fn evidence_request(
    mut reference: OciReference,
    entry: AdmissionEvidence,
    kind: EvidenceKind,
    subject: &PackageSubject,
) -> Result<OciPushRequest, Failure> {
    if entry.manifest.len() > 4096 || entry.payload.len() > payload_limit(kind) {
        return Err(limit());
    }
    let decoded = decode_referrer(&entry.manifest, super::super::limits().package)
        .map_err(super::super::failure)?;
    if decoded.subject != *subject || decoded.artifact_type != kind.artifact_type() {
        return Err(association());
    }
    let manifest = OciManifestBytes::new(entry.manifest, 4096).map_err(super::super::failure)?;
    reference.reference = manifest.digest().to_string();
    OciPushRequest::new_referrer(
        reference,
        manifest,
        entry.configuration,
        vec![(decoded.layers[0].clone(), entry.payload)],
        super::super::limits().package,
    )
    .map_err(super::super::failure)
}
pub(super) fn subject(package: &PackageBundle) -> PackageSubject {
    PackageSubject {
        media_type: OCI_MANIFEST_MEDIA_TYPE.into(),
        digest: package.layout().digest().clone(),
        size: package.manifest_bytes().len() as u64,
    }
}
fn package_size(package: &PackageBundle) -> usize {
    package.manifest_bytes().len()
        + package.config_bytes().len()
        + package
            .layers()
            .iter()
            .map(|layer| layer.bytes().len())
            .sum::<usize>()
}
pub(super) fn request_size(request: &OciPushRequest) -> Result<usize, Failure> {
    request.layers().try_fold(
        request.manifest().as_bytes().len() + request.config_bytes().len(),
        |sum, (_, bytes)| sum.checked_add(bytes.len()).ok_or_else(limit),
    )
}
pub(super) fn copy_package(
    request: &OciPushRequest,
    budget: &Budget,
) -> Result<Owned<PackageBundle>, Failure> {
    let layout = request.layout().ok_or_else(association)?;
    let size = request_size(request)?;
    if size > MAX_PACKAGE {
        return Err(limit());
    }
    let charge = budget.reserve(size)?;
    let input = BundleInput {
        manifest: request.manifest().as_bytes().to_vec(),
        configuration: request.config_bytes().to_vec(),
        layers: layout
            .config()
            .layers
            .iter()
            .zip(request.layers())
            .map(|(layer, (_, bytes))| (layer.path.clone(), bytes.to_vec()))
            .collect(),
    };
    let package = latent_packaging::inspect_bundle(input, super::super::limits())
        .map_err(super::super::failure)?;
    Ok(charge.own(package))
}
pub(super) fn kind(artifact_type: &str) -> Option<EvidenceKind> {
    [
        EvidenceKind::Signature,
        EvidenceKind::Provenance,
        EvidenceKind::Sbom,
    ]
    .into_iter()
    .find(|kind| kind.artifact_type() == artifact_type)
}
pub(super) const fn payload_limit(kind: EvidenceKind) -> usize {
    match kind {
        EvidenceKind::Signature => 4096,
        EvidenceKind::Provenance => 49152,
        EvidenceKind::Sbom => 1024 * 1024,
    }
}
pub(super) fn append_evidence(
    request: &OciPushRequest,
    kind: EvidenceKind,
    subject: &PackageSubject,
    evidence: &mut ReleaseEvidenceUpload,
    remaining: &mut usize,
) -> Result<(), Failure> {
    let manifest = request.referrer().ok_or_else(association)?;
    if manifest.subject != *subject
        || manifest.artifact_type != kind.artifact_type()
        || request.manifest().as_bytes().len() > 4096
    {
        return Err(association());
    }
    let (_, payload) = request.layers().next().ok_or_else(association)?;
    if payload.len() > payload_limit(kind) {
        return Err(limit());
    }
    let entries = match kind {
        EvidenceKind::Signature => &mut evidence.signatures,
        EvidenceKind::Provenance => &mut evidence.provenance,
        EvidenceKind::Sbom => &mut evidence.sboms,
    };
    if entries.len() >= 8 {
        return Err(limit());
    }
    let size = request_size(request)?;
    *remaining = remaining.checked_sub(size).ok_or_else(limit)?;
    // Entire output allowance is owned before any detached bytes are cloned.
    entries.push(AdmissionEvidence {
        manifest: request.manifest().as_bytes().to_vec(),
        configuration: request.config_bytes().to_vec(),
        payload: payload.to_vec(),
    });
    Ok(())
}
