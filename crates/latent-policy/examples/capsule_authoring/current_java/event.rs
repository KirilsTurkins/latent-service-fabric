//! One independently captured event guest, signed only under disposable fixture trust.
use super::{sign_selected, Result};
use std::{ffi::OsString, path::Path};

const SOURCE: &str = "9a19b0239ae66f88ec2b2f51013f7b60c3d3c71f";
const PROFILE: &str =
    "js-window-v1:94c859368e06236a91d6f00be73bd3018bb49d3a06b5d763fa67b49cd573a459";
const PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-event-capture-9a19-2026-11-08.json"
));
const LIVE_SOURCE: &str = "49eaca04be33f71d993e093576343ee89afb0cf0";
const LIVE_PROFILE: &str =
    "js-window-v1:3444a7838fbf3990b9426fb34268c0c9954ebc96cdb465fbc4a500f6f8aadf74";
const LIVE_PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-event-capture-49ea-2026-11-08.json"
));

pub(crate) fn sign_captured_event_java(
    output: &Path,
    source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(output, source, paths, &["aggregate"], PINS, PROFILE, SOURCE)
}

pub(crate) fn sign_live_event_java(output: &Path, source: &str, paths: &[OsString]) -> Result<()> {
    sign_selected(
        output,
        source,
        paths,
        &["aggregate"],
        LIVE_PINS,
        LIVE_PROFILE,
        LIVE_SOURCE,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn exact_capture_does_not_claim_execution_and_rejects_unpinned_input() {
        let packet: serde_json::Value = serde_json::from_slice(PINS).unwrap();
        assert_eq!(packet["captures"]["sourceCommit"], SOURCE);
        assert_eq!(packet["captures"]["nativeIdempotencyProfile"], PROFILE);
        assert_eq!(packet["executionQualified"], false);
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("absent");
        assert!(sign_captured_event_java(&output, "wrong", &[root.path().into()]).is_err());
        assert!(sign_captured_event_java(&output, SOURCE, &[root.path().into()]).is_err());
        assert!(!output.exists());
        let live: serde_json::Value = serde_json::from_slice(LIVE_PINS).unwrap();
        assert_eq!(live["captures"]["sourceCommit"], LIVE_SOURCE);
        assert_eq!(live["captures"]["nativeIdempotencyProfile"], LIVE_PROFILE);
        assert_eq!(live["executionQualified"], false);
        assert!(sign_live_event_java(&output, SOURCE, &[root.path().into()]).is_err());
        assert!(sign_live_event_java(&output, LIVE_SOURCE, &[root.path().into()]).is_err());
        assert!(!output.exists());
    }
}
