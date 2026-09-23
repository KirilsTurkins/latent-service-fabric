//! Explicit short-lived local development approval, never a production trust default.
//! Private signing keys are generated in memory and discarded, not written to disk.
use base64::{engine::general_purpose::STANDARD, Engine};
use latent_artifacts::{
    package::{artifact_blob_digest, PackageLimits},
    AdmissionEvidence, ReleaseEvidenceUpload,
};
use latent_core::PublisherId;
use latent_packaging::{
    read_package_directory, write_package_directory, write_package_evidence, PackagingLimits,
};
use latent_signing::*;
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    error::Error,
    fs,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Request {
    format_version: u32,
    repository: String,
    projects: Vec<Project>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Project {
    name: String,
    directory: String,
}

fn safe_name(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 64
        && name.as_bytes()[0].is_ascii_lowercase()
        && name
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        && name.as_bytes()[name.len() - 1].is_ascii_alphanumeric()
}
fn read(path: &Path, maximum: usize) -> Result<Vec<u8>, Box<dyn Error>> {
    if fs::symlink_metadata(path)?.file_type().is_symlink() || !path.is_file() {
        return Err("local approval requires regular input files".into());
    }
    super::read(path.to_str().ok_or("non-UTF-8 path")?, maximum)
}
fn write(path: &Path, bytes: &[u8]) -> Result<(), Box<dyn Error>> {
    use std::io::Write;
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)?.write_all(bytes)?;
    Ok(())
}

pub(super) fn create(request: &str, output: &str) -> Result<(), Box<dyn Error>> {
    let request: Request = serde_json::from_slice(&super::read(request, 65536)?)?;
    if request.format_version != 1 || request.projects.is_empty() || request.projects.len() > 16 {
        return Err("local approval accepts 1 to 16 explicitly selected builds".into());
    }
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let publisher_key = generate_signing_key().map_err(|e| e.message)?;
    let publisher_public = *publisher_key.public_key();
    let publisher = LocalSigner::from_pkcs8(
        publisher_key.into_pkcs8(),
        PublisherId("guest-publisher".into()),
        publisher_public,
    )
    .map_err(|e| e.message)?;
    let builder_key = generate_signing_key().map_err(|e| e.message)?;
    let builder_public = *builder_key.public_key();
    let builder = LocalBuilderSigner::from_pkcs8(
        builder_key.into_pkcs8(),
        "guest-builder".into(),
        builder_public,
    )
    .map_err(|e| e.message)?;
    let publisher_policy = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now.saturating_sub(60),"validUntil":now+3600,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,"keys":[{"publisherId":"guest-publisher","publicKey":STANDARD.encode(publisher_public),"validFrom":now.saturating_sub(60),"validUntil":now+3600}]});
    let builder_policy = json!({"formatVersion":1,"scope":"tests","generation":1,"validFrom":now.saturating_sub(60),"validUntil":now+3600,
        "maxSignatureLifetimeSeconds":2000,"maxProofAgeSeconds":60,"keys":[{"builderId":"guest-builder","publicKey":STANDARD.encode(builder_public),"validFrom":now.saturating_sub(60),"validUntil":now+3600}],
        "requirements":[{"builderId":"guest-builder","buildType":RUST_CAPSULE_BUILD_TYPE,"sourceRepository":request.repository,"requireReproducible":false}]});
    let pd = PublisherPolicy::from_json(
        &serde_json::to_vec(&publisher_policy)?,
        SignatureLimits::default(),
    )
    .map_err(|e| e.message)?
    .digest()
    .to_string();
    let bd = BuilderPolicy::from_json(
        &serde_json::to_vec(&builder_policy)?,
        ProvenanceLimits::default(),
    )
    .map_err(|e| e.message)?
    .digest()
    .to_string();
    let policy = json!({"formatVersion":1,"generation":1,"scope":"tests","validFrom":now.saturating_sub(60),"validUntil":now+3600,
        "tenants":[{"tenant":"tests","publishers":["guest-publisher"]}],"publisher":publisher_policy,"builder":builder_policy,
        "publisherRevocations":{"formatVersion":1,"scope":"tests","policyDigest":pd,"generation":1,"validFrom":now.saturating_sub(60),"validUntil":now+3600,"revokedKeys":[],"revokedPublishers":[]},
        "builderRevocations":{"formatVersion":1,"scope":"tests","policyDigest":bd,"generation":1,"validFrom":now.saturating_sub(60),"validUntil":now+3600,"revokedKeys":[],"revokedBuilders":[]},
        "sbom":{"formatVersion":1,"embedded":"required","detached":"optional","requireSource":[],"requireLicense":[]}});
    // Validate every association and sign before exposing a completed trust directory.
    let mut names = std::collections::BTreeSet::new();
    let mut builds = Vec::new();
    for selected in request.projects {
        if !safe_name(&selected.name) || !names.insert(selected.name.clone()) {
            return Err("invalid or duplicate selected project".into());
        }
        let directory = Path::new(&selected.directory);
        if !directory.is_absolute() || directory.canonicalize()? != directory {
            return Err("build directory must be an absolute unlinked path".into());
        }
        let bytes = read(&directory.join("build-observation.json"), 32768)?;
        let observation =
            decode_build_observation(&bytes, ProvenanceLimits::default()).map_err(|e| e.message)?;
        let marker: Value =
            serde_json::from_slice(&read(&directory.join("BUILD-COMPLETE.json"), 65536)?)?;
        let inputs = read(&directory.join("source-inputs.json"), 1024 * 1024)?;
        if observation.build_type != RUST_CAPSULE_BUILD_TYPE
            || observation.source.repository != request.repository
            || marker["formatVersion"] != 1
            || marker["observationDigest"] != artifact_blob_digest(&bytes)
            || observation.source.snapshot_digest != artifact_blob_digest(&inputs)
            || directory.join("BUILD-FAILED.json").exists()
        {
            return Err("build association or explicit source approval mismatch".into());
        }
        let bundle = read_package_directory(&directory.join("package"), PackagingLimits::default())
            .map_err(|e| e.message)?;
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .map_err(|e| e.message)?;
        let validity = SignatureValidity {
            issued_at: now,
            expires_at: now + 1200,
        };
        let signature = publisher
            .sign_package(&subject, validity, SignatureLimits::default())
            .map_err(|e| e.message)?;
        let provenance = builder
            .sign_build(
                &subject,
                &observation,
                validity,
                ProvenanceLimits::default(),
            )
            .map_err(|e| e.message)?;
        let evidence = ReleaseEvidenceUpload {
            signatures: vec![AdmissionEvidence {
                manifest: signature.manifest_bytes().to_vec(),
                configuration: b"{}".to_vec(),
                payload: signature.payload_bytes().to_vec(),
            }],
            provenance: vec![AdmissionEvidence {
                manifest: provenance.manifest_bytes().to_vec(),
                configuration: b"{}".to_vec(),
                payload: provenance.payload_bytes().to_vec(),
            }],
            sboms: vec![],
        };
        builds.push((selected.name, bundle, observation, evidence));
    }
    let output = Path::new(output);
    fs::create_dir(output)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(output, fs::Permissions::from_mode(0o700))?;
    }
    write(&output.join("policy.json"), &serde_json::to_vec(&policy)?)?;
    let mut records = Vec::new();
    for (name, bundle, observation, evidence) in builds {
        let directory = output.join(&name);
        fs::create_dir(&directory)?;
        write_package_directory(&bundle, &directory.join("package")).map_err(|e| e.message)?;
        let digest = bundle.layout().digest();
        write_package_evidence(digest, &evidence, &directory.join("evidence"), 1024 * 1024)
            .map_err(|e| e.message)?;
        records.push(json!({"name":name,"packageDigest":digest.as_str(),"componentDigest":bundle.layout().component_release().ok_or("missing component")?.0,"buildObservation":observation}));
    }
    write(
        &output.join("fixture.json"),
        &serde_json::to_vec(
            &json!({"schemaVersion":"latent.rust.authoring.local-trust.v1","tenant":"tests","fixtures":records,"privateKeysPersisted":false,"productionTrust":false}),
        )?,
    )?;
    println!(
        "{}",
        json!({"approvedBuilds":names.len(),"tenant":"tests","productionTrust":false,"validUntil":now+1200})
    );
    Ok(())
}
