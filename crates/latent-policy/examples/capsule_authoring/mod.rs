mod inputs;
mod policy;

use std::{
    collections::BTreeSet,
    ffi::OsString,
    fs,
    io::Write,
    path::Path,
    time::{SystemTime, UNIX_EPOCH},
};

use latent_artifacts::package::{artifact_blob_digest, package_digest, PackageLimits};
use latent_artifacts::{AdmissionEvidence, ReleaseEvidenceUpload};
use latent_core::{PublisherId, TenantId};
use latent_packaging::{write_package_directory, write_package_evidence};
use latent_policy::supply_chain::{verify_package_once, PackageVerificationRequest};
use latent_signing::{
    generate_signing_key, LocalBuilderSigner, LocalSigner, PackageSigningSubject, ProvenanceLimits,
    SignatureLimits, SignatureValidity,
};
use serde_json::json;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
const PUBLISHER: &str = "local-demo-publisher";
const BUILDER: &str = "local-demo-builder";
const TENANT: &str = "examples";

fn write(path: &Path, bytes: &[u8]) -> Result<()> {
    if bytes.len() > 4 * 1024 * 1024 {
        return Err("demo document byte limit".into());
    }
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    Ok(())
}

fn directory(path: &Path) -> Result<()> {
    fs::create_dir(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

pub(super) fn sign_demo(output: &Path, paths: &[OsString]) -> Result<()> {
    if !output.is_absolute() || output.exists() || !(1..=16).contains(&paths.len()) {
        return Err("choose a fresh absolute output and one to sixteen completed builds".into());
    }
    let mut builds = Vec::new();
    let mut names = BTreeSet::new();
    for path in paths {
        let build = inputs::load(Path::new(path))?;
        if !names.insert(build.bundle.layout().config().name.clone()) {
            return Err("duplicate demo package name".into());
        }
        builds.push(build);
    }
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let validity = SignatureValidity {
        issued_at: now,
        expires_at: now + 1800,
    };
    // Keys are generated only AFTER every build input is read and checked. No
    // compiler runs in this process; private keys are never written or printed.
    let publisher_key = generate_signing_key()?;
    let publisher_public = *publisher_key.public_key();
    let publisher = LocalSigner::from_pkcs8(
        publisher_key.into_pkcs8(),
        PublisherId(PUBLISHER.into()),
        publisher_public,
    )?;
    let builder_key = generate_signing_key()?;
    let builder_public = *builder_key.public_key();
    let builder =
        LocalBuilderSigner::from_pkcs8(builder_key.into_pkcs8(), BUILDER.into(), builder_public)?;
    let (policy, policy_document) =
        policy::create(now, &publisher_public, &builder_public, &builds)?;
    directory(output)?;
    write(&output.join("policy.json"), &policy_document)?;
    let mut releases = Vec::new();
    for build in builds {
        let subject = PackageSigningSubject::from_package(
            build.bundle.manifest_bytes(),
            build.bundle.config_bytes(),
            PackageLimits::default(),
        )?;
        let signature = publisher.sign_package(&subject, validity, SignatureLimits::default())?;
        let provenance = builder.sign_build(
            &subject,
            &build.observation,
            validity,
            ProvenanceLimits::default(),
        )?;
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
        // The same enforced-policy verifier is used again by the actual node.
        verify_package_once(
            &policy,
            PackageVerificationRequest {
                tenant: &TenantId(TENANT.into()),
                package: &build.bundle,
                evidence: &evidence,
                unix_seconds: now,
            },
        )
        .map_err(|error| error.message)?;
        let name = &build.bundle.layout().config().name;
        let destination = output.join(name);
        directory(&destination)?;
        write_package_directory(&build.bundle, &destination.join("package"))
            .map_err(|error| error.message)?;
        let digest = package_digest(build.bundle.manifest_bytes());
        write_package_evidence(
            &digest,
            &evidence,
            &destination.join("evidence"),
            1024 * 1024,
        )
        .map_err(|error| error.message)?;
        write(&destination.join("deployment.json"), &build.deployment)?;
        write(
            &destination.join("build-observation.json"),
            &serde_json::to_vec(&build.observation)?,
        )?;
        releases.push(json!({"name": name, "world": build.world, "service": build.service,
            "packageDigest": digest.to_string(), "componentDigest": build.observation.component_digest,
            "sourceSnapshotDigest": build.observation.source.snapshot_digest,
            "observationDigest": artifact_blob_digest(&serde_json::to_vec(&build.observation)?).to_string()}));
    }
    // Written last; failed/partial signing attempts have no success marker.
    let record = json!({"schemaVersion":"latent.rust-capsule.demo.v1", "tenant":TENANT,
        "trust":"isolated-short-lived-demo-only", "expiresAtUnixSeconds": validity.expires_at,
        "policyDigest": artifact_blob_digest(&policy_document).to_string(), "releases": releases});
    write(
        &output.join("release-set.json"),
        &serde_json::to_vec_pretty(&record)?,
    )?;
    println!("{}", serde_json::to_string(&record)?);
    Ok(())
}
