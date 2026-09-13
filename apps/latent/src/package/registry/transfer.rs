use super::{
    budget::Budget, check, data, Failure, HttpOciRegistry, Instant, Outcome, PACKAGE_RESERVATION,
};
use crate::args::{PackageCommand, PackagePullArgs};
use latent_artifacts::ReleaseEvidenceUpload;
use latent_oci::{OciReference, OciRegistry};
use serde_json::{json, Value};
use std::path::Path;

#[derive(Default)]
pub(super) struct Progress {
    pub dispatched: bool,
    pub uncertain: Option<String>,
    package: Option<String>,
    confirmed: Vec<String>,
    remaining: Vec<String>,
    package_exported: bool,
    evidence_exported: bool,
}
impl Progress {
    pub fn summary(&self, cleanup: bool) -> Value {
        json!({"packageDigest":self.package,"confirmedDigests":self.confirmed,
            "uncertainDigest":self.uncertain,"notAttemptedDigests":self.remaining,
            "packageExported":self.package_exported,"evidenceExported":self.evidence_exported,
            "registryCleanupConfirmed":cleanup,"trustEvaluated":false,"executionAuthorized":false})
    }
}
pub(super) async fn run(
    registry: &HttpOciRegistry,
    mut reference: OciReference,
    command: &PackageCommand,
    budget: &Budget,
    progress: &mut Progress,
    deadline: Instant,
) -> Result<Outcome, Failure> {
    match command {
        PackageCommand::Push(args) => {
            let prepared = data::prepare(args, reference, budget)?;
            check(deadline)?;
            progress.package = Some(prepared.package.value.manifest().digest().to_string());
            progress.remaining = std::iter::once(&prepared.package.value)
                .chain(prepared.evidence.value.iter())
                .map(|request| request.manifest().digest().to_string())
                .collect();
            let (request, _package_charge) = prepared.package.into_parts();
            let (evidence, _evidence_charge) = prepared.evidence.into_parts();
            for request in std::iter::once(request).chain(evidence) {
                check(deadline)?;
                let digest = request.manifest().digest().to_string();
                progress.remaining.remove(0);
                progress.uncertain = Some(digest.clone());
                progress.dispatched = true;
                let actual = registry
                    .push(request)
                    .await
                    .map_err(super::super::failure)?;
                if actual.as_str() != digest {
                    return Err(super::association());
                }
                progress.confirmed.push(digest);
                progress.uncertain = None;
            }
            let mut outcome = Outcome::success(
                json!({"package":prepared.summary,"transfer":progress.summary(true)}),
            );
            outcome.request_dispatched = true;
            Ok(outcome)
        }
        PackageCommand::Pull(args) => {
            reference.reference = args.reference.clone();
            pull(registry, reference, args, budget, progress, deadline).await
        }
        _ => Err(super::association()),
    }
}
async fn pull(
    registry: &HttpOciRegistry,
    reference: OciReference,
    args: &PackagePullArgs,
    budget: &Budget,
    progress: &mut Progress,
    deadline: Instant,
) -> Result<Outcome, Failure> {
    output(&args.output_dir)?;
    output(&args.evidence_output)?;
    // Both parents must already exist. This prevents putting a newly exported
    // evidence tree inside the exact package inventory or vice versa.
    let package_parent = parent(&args.output_dir)
        .canonicalize()
        .map_err(|_| super::association())?;
    let evidence_parent = parent(&args.evidence_output)
        .canonicalize()
        .map_err(|_| super::association())?;
    if package_parent.join(args.output_dir.file_name().ok_or_else(super::association)?)
        == evidence_parent.join(
            args.evidence_output
                .file_name()
                .ok_or_else(super::association)?,
        )
    {
        return Err(super::association());
    }
    check(deadline)?;
    let remote_charge = budget.reserve(PACKAGE_RESERVATION)?;
    progress.dispatched = true;
    let received = remote_charge.own(
        registry
            .pull_package(&reference)
            .await
            .map_err(super::super::failure)?,
    );
    let package = data::copy_package(received.value.request(), budget)?;
    let subject = data::subject(&package.value);
    progress.package = Some(subject.digest.to_string());
    let pinned = received.value.request().reference().clone();
    check(deadline)?;
    let descriptors = registry
        .list_referrers(&pinned, None)
        .await
        .map_err(super::super::failure)?;
    let mut evidence = budget
        .reserve(super::super::MAX_EVIDENCE)?
        .own(ReleaseEvidenceUpload::default());
    let mut remaining = super::super::MAX_EVIDENCE;
    let mut unsupported = 0_usize;
    for descriptor in descriptors {
        let Some(kind) = descriptor.artifact_type.as_deref().and_then(data::kind) else {
            unsupported += 1;
            continue;
        };
        check(deadline)?;
        if descriptor.size_bytes > 4096 {
            return Err(super::limit());
        }
        let mut selected = pinned.clone();
        selected.reference = descriptor.digest;
        let charge = budget.reserve(PACKAGE_RESERVATION)?;
        let entry = charge.own(
            registry
                .pull_package(&selected)
                .await
                .map_err(super::super::failure)?,
        );
        if entry.value.request().manifest().as_bytes().len() as u64 != descriptor.size_bytes {
            return Err(super::association());
        }
        data::append_evidence(
            entry.value.request(),
            kind,
            &subject,
            &mut evidence.value,
            &mut remaining,
        )?;
    }
    check(deadline)?;
    latent_packaging::write_package_directory(&package.value, &args.output_dir)
        .map_err(super::super::failure)?;
    progress.package_exported = true;
    check(deadline)?;
    latent_packaging::write_package_evidence(
        &subject.digest,
        &evidence.value,
        &args.evidence_output,
        super::super::MAX_EVIDENCE,
    )
    .map_err(super::super::failure)?;
    progress.evidence_exported = true;
    let mut result = Outcome::success(
        json!({"package":super::super::summary(&package.value),"transfer":progress.summary(true),"unsupportedReferrersSkipped":unsupported}),
    );
    result.request_dispatched = true;
    // Both original OCI graph ownership and the charged copy remain live until
    // the final export completes. They carry no publisher/admission authority.
    drop(received);
    Ok(result)
}
fn parent(path: &Path) -> &Path {
    path.parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
}
fn output(path: &Path) -> Result<(), Failure> {
    if std::fs::symlink_metadata(path).is_ok() || !parent(path).is_dir() {
        return Err(super::invalid(
            "registry-output",
            "Both output directories must be new children of existing directories.",
        ));
    }
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(super::association)?;
    latent_artifacts::package::validate_package_path(name, super::super::limits().package)
        .map_err(super::super::failure)
}
