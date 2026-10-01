//! First clock floor for a new disposable qualification store. Existing owner
//! history is never replaced, lowered, or represented as proven continuity.
use latent_core::{ActivationClock, SystemActivationClock};
use serde_json::json;
use std::path::Path;

pub(super) fn create(output: &Path, node: &str) -> Result<(), Box<dyn std::error::Error>> {
    if !output.is_absolute()
        || output.exists()
        || node.is_empty()
        || node.len() > 128
        || !node
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        return Err(
            "clock fixture requires a fresh absolute private root and bounded node identity".into(),
        );
    }
    let sample = SystemActivationClock.sample();
    let checkpoint = serde_json::to_vec(&json!({
        "formatVersion": 1, "nodeId": node, "ownerEpoch": 1,
        "clockFloorUnixMillis": sample.unix_millis()
    }))?;
    super::authoring::directory(output)?;
    super::authoring::write(&output.join("state-clock.json"), &checkpoint)?;
    let record = json!({
        "schemaVersion": "latent.qualification.fresh-clock-bootstrap.v1",
        "nodeId": node, "freshStore": true, "ownerEpoch": 1,
        "clockSource": "latent_core::SystemActivationClock",
        "checkpointDigest": latent_artifacts::package::artifact_blob_digest(&checkpoint).as_str(),
        "productionRestoreQualified": false
    });
    super::authoring::write(
        &output.join("clock-bootstrap.json"),
        &serde_json::to_vec(&record)?,
    )?;
    println!("{}", serde_json::to_string(&record)?);
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn fresh_clock_fixture_uses_native_sample_and_refuses_existing_owner_history() {
        let root = tempfile::tempdir().unwrap();
        let owner = root.path().join("fresh");
        let before = latent_core::ActivationClock::sample(&latent_core::SystemActivationClock);
        super::create(&owner, "fixture-node").unwrap();
        let raw = std::fs::read(owner.join("state-clock.json")).unwrap();
        let checkpoint: serde_json::Value = serde_json::from_slice(&raw).unwrap();
        let after = latent_core::ActivationClock::sample(&latent_core::SystemActivationClock);
        let floor = checkpoint["clockFloorUnixMillis"].as_u64().unwrap();
        assert!((before.unix_millis()..=after.unix_millis()).contains(&floor));
        assert_eq!(checkpoint["ownerEpoch"], 1);
        assert!(checkpoint.get("continuityProven").is_none());
        assert!(super::create(&owner, "fixture-node").is_err());
        assert_eq!(std::fs::read(owner.join("state-clock.json")).unwrap(), raw);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                std::fs::metadata(&owner).unwrap().permissions().mode() & 0o777,
                0o700
            );
            assert_eq!(
                std::fs::metadata(owner.join("state-clock.json"))
                    .unwrap()
                    .permissions()
                    .mode()
                    & 0o777,
                0o600
            );
        }
    }
}
