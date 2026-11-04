//! Exact fresh constructor-profile capture; this is synthetic fixture trust.
use std::{ffi::OsString, path::Path};

use super::{sign_selected, Result, NAMES};

const SOURCE: &str = "fccc27dbc52f2dd0db137078f8e7e436a41ebe8a";
const PROFILE: &str =
    "qualified-http-v1:5337619eb24838242cf05797a246bba5e50547f3f12252ed9b81e138ca8a259b";
const PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-capture-2026-11-04.json"
));
const CURRENT_SOURCE: &str = "46597407903231d2914f54358cff94dfc598878b";
const CURRENT_PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-capture-465-2026-11-04.json"
));
const POSTSTAGE_SOURCE: &str = "a1b0b7c7190610dca57171db2c31abb636935925";
const POSTSTAGE_PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-poststage-http-capture-2026-11-04.json"
));

pub(crate) fn sign_november_current_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &NAMES,
        PINS,
        PROFILE,
        SOURCE,
    )
}

pub(crate) fn sign_current_465_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &NAMES,
        CURRENT_PINS,
        PROFILE,
        CURRENT_SOURCE,
    )
}

pub(crate) fn sign_poststage_http_java(
    output: &Path,
    compiler_source: &str,
    paths: &[OsString],
) -> Result<()> {
    sign_selected(
        output,
        compiler_source,
        paths,
        &["put-once-poststage-http-denial"],
        POSTSTAGE_PINS,
        PROFILE,
        POSTSTAGE_SOURCE,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn november_capture_is_closed_and_does_not_claim_execution() {
        let packet: serde_json::Value = serde_json::from_slice(PINS).unwrap();
        assert_eq!(packet["captures"]["sourceCommit"], SOURCE);
        assert_eq!(packet["constructor"]["profile"], PROFILE);
        assert_eq!(packet["captures"]["nativeIdempotencyProfile"], PROFILE);
        assert_eq!(packet["captures"]["variants"].as_object().unwrap().len(), 6);
        assert_eq!(packet["signingQualified"], false);
        assert_eq!(packet["executionQualified"], false);
        assert_eq!(packet["packagedDistributionQualified"], false);
        assert!(!NAMES.contains(&"forbidden-http"));
        let current: serde_json::Value = serde_json::from_slice(CURRENT_PINS).unwrap();
        assert_eq!(current["captures"]["sourceCommit"], CURRENT_SOURCE);
        assert_eq!(current["captures"]["nativeIdempotencyProfile"], PROFILE);
        assert_eq!(current["executionQualified"], false);
        let poststage: serde_json::Value = serde_json::from_slice(POSTSTAGE_PINS).unwrap();
        assert_eq!(poststage["captures"]["sourceCommit"], POSTSTAGE_SOURCE);
        assert_eq!(poststage["captures"]["nativeIdempotencyProfile"], PROFILE);
        assert_eq!(poststage["postStageRollbackQualified"], false);
    }

    #[test]
    fn november_signer_refuses_wrong_source_and_unpinned_material_before_output() {
        let root = tempfile::tempdir().unwrap();
        let output = root.path().join("absent");
        let inputs = vec![root.path().as_os_str().to_owned(); NAMES.len()];
        assert!(sign_november_current_java(&output, "wrong", &inputs).is_err());
        std::fs::write(
            root.path().join("compiler-report.json"),
            br#"{"variant":"aggregate"}"#,
        )
        .unwrap();
        assert!(sign_november_current_java(&output, SOURCE, &inputs).is_err());
        assert!(!output.exists());
        assert!(sign_current_465_java(&output, SOURCE, &inputs).is_err());
        assert!(sign_current_465_java(&output, CURRENT_SOURCE, &inputs).is_err());
        assert!(sign_poststage_http_java(&output, SOURCE, &[root.path().into()]).is_err());
        assert!(
            sign_poststage_http_java(&output, POSTSTAGE_SOURCE, &[root.path().into()]).is_err()
        );
    }
}
