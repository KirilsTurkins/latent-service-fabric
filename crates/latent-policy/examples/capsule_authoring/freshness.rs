//! Development qualification consumes real grants, never decoded proof reports.
use std::{
    ffi::OsString,
    path::Path,
    sync::Arc,
    time::{Duration, Instant},
};

use latent_artifacts::package::package_digest;
use latent_artifacts::{AdmissionAuthority, PackageAdmissionUpload};
use latent_core::{PlatformErrorCode, TenantId};
use latent_packaging::{
    read_package_directory, read_package_evidence, read_package_file, PackagingLimits,
};
use latent_policy::supply_chain::{
    SupplyChainAuthority, SupplyChainClock, SupplyChainPolicy, SystemSupplyChainClock,
};
use serde_json::{json, Value};

use super::{directory, write, Result, TENANT};

fn checked<T>(value: std::result::Result<T, latent_core::PlatformError>) -> Result<T> {
    value.map_err(|error| error.message.into())
}

pub(crate) fn check_stale_proofs(
    output: &Path,
    policy_path: &Path,
    artifacts: &[OsString],
) -> Result<()> {
    if !output.is_absolute() || output.exists() || !(1..=2).contains(&artifacts.len()) {
        return Err("choose a fresh absolute output and one or two signed packages".into());
    }
    let policy_bytes = checked(read_package_file(
        policy_path.parent().ok_or("policy parent required")?,
        policy_path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or("policy filename required")?,
        256 * 1024,
    ))?;
    let value: Value = serde_json::from_slice(&policy_bytes)?;
    // This finite development experiment cannot use a long policy TTL as a wait.
    if value["builder"]["maxProofAgeSeconds"] != 2 {
        return Err(
            "stale proof qualification requires an explicit two-second builder proof TTL".into(),
        );
    }
    directory(output)?;
    let mut observations = Vec::new();
    for (ordinal, artifact) in artifacts.iter().enumerate() {
        let root = Path::new(artifact);
        let package = checked(read_package_directory(
            &root.join("package"),
            PackagingLimits::default(),
        ))?;
        let package_identity = package_digest(package.manifest_bytes());
        let evidence_bytes = checked(read_package_file(
            &root.join("evidence"),
            "index.json",
            16 * 1024,
        ))?;
        let evidence = checked(read_package_evidence(
            &root.join("evidence"),
            &evidence_bytes,
            &package_identity,
            1024 * 1024,
        ))?;
        let input = package.into_input();
        let upload = PackageAdmissionUpload {
            manifest: input.manifest,
            configuration: input.configuration,
            layers: input.layers,
            signatures: evidence.signatures,
            provenance: evidence.provenance,
            sboms: evidence.sboms,
        };
        let clock = Arc::new(SystemSupplyChainClock);
        let authority = checked(SupplyChainAuthority::open(
            &output.join(format!("authority-{ordinal}")),
            checked(SupplyChainPolicy::from_json(&policy_bytes))?,
            clock.clone(),
            5,
        ))?;
        let admitted = checked(authority.verify(&TenantId(TENANT.into()), upload))?;
        checked(admitted.grant.check_current())?;
        let binding = admitted.grant.binding();
        let receipt: Value = serde_json::from_slice(&binding.receipt)?;
        let expiry = receipt["validUntil"]
            .as_u64()
            .ok_or("proof expiry required")?;
        let began = Instant::now();
        let mut polls = 0;
        while checked(clock.now())? < expiry {
            polls += 1;
            if polls > 160 || began.elapsed() > Duration::from_secs(4) {
                return Err("bounded real-clock proof expiry wait exceeded".into());
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        let error = admitted
            .grant
            .check_current()
            .err()
            .ok_or("expired proof was accepted")?;
        if error.code != PlatformErrorCode::StateConflict
            || error.message != "signature-stale-proof"
        {
            return Err("expired proof was not rejected by the signature currentness owner".into());
        }
        let mut entered = false;
        let fenced = admitted.grant.with_current(&mut |_| {
            entered = true;
            Ok(())
        });
        if entered
            || !matches!(fenced, Err(ref error) if error.code == PlatformErrorCode::StateConflict && error.message == "signature-stale-proof")
        {
            return Err("expired proof entered the actual admission fence".into());
        }
        observations.push(json!({"packageDigest":binding.package.as_str(),"componentDigest":binding.release.0.as_str(),
            "originalAdmissionReceipt":receipt,"freshCheckpointAccepted":true,"expiredAtUnixSeconds":checked(clock.now())?,
            "reusedGrantRejected":true,"fencedActionEntered":entered,"reason":"signature-stale-proof",
            "platformCode":"state-conflict"}));
        authority.retire();
    }
    write(
        &output.join("stale-proofs.json"),
        &serde_json::to_vec(&json!({
            "schemaVersion":"latent.java-paired.stale-proof.v1","status":"passed",
            "owner":"SupplyChainAuthority","clock":"SystemSupplyChainClock","guestExecuted":false,
            "proofs":observations,"retainedReceiptCreatesAuthority":false,
        }))?,
    )
}
