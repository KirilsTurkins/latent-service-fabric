//! One separately captured diagnostic set, with no authority from the selector.
use std::{ffi::OsString, path::Path};

use super::{sign_selected, Result, FRESH_HTTP_PROFILE, NAMES};

const SOURCE: &str = "eba0d96e9439028aacd6c1f9a85d4ce0118a19bc";
const PINS: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-native-memory-capture-2026-10-14.json"
));

pub(crate) fn sign_native_memory_current_java(
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
        FRESH_HTTP_PROFILE,
        SOURCE,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::Value;

    #[test]
    fn native_memory_capture_keeps_compiler_source_and_original_current_materials_closed() {
        let packet: Value = serde_json::from_slice(PINS).unwrap();
        let prior: Value = serde_json::from_slice(super::super::FRESH_HTTP_PINS).unwrap();
        assert_eq!(packet["captures"]["sourceCommit"], SOURCE);
        assert_eq!(prior["captures"]["sourceCommit"], super::super::SOURCE);
        assert_eq!(packet["constructor"], prior["constructor"]);
        assert_eq!(
            packet["captures"]["nativeIdempotencyProfile"],
            FRESH_HTTP_PROFILE
        );
        assert_eq!(packet["captures"]["variants"].as_object().unwrap().len(), 6);
        for name in super::super::WITH_NEGATIVE {
            let before = &prior["captures"]["variants"][name]["materials"];
            let after = &packet["captures"]["variants"][name]["materials"];
            assert_ne!(before["report"], after["report"]);
            for (key, value) in before.as_object().unwrap() {
                if name != "put-once-diagnostics"
                    && !matches!(
                        key.as_str(),
                        "report"
                            | "compilerInputs"
                            | "sourceInputs"
                            | "sourceArchive"
                            | "recipeInputs"
                    )
                {
                    assert_eq!(value, &after[key]);
                }
            }
        }
        assert_ne!(
            prior["captures"]["variants"]["put-once-diagnostics"]["materials"]["component"],
            packet["captures"]["variants"]["put-once-diagnostics"]["materials"]["component"]
        );
        assert_eq!(
            packet["diagnosticProbe"]["helper"]["sha256"],
            "sha256:7da3fb40e27adda8af63df6cfd793b076f991bdf61c3f7b20cae5e7a55112091"
        );
        assert_eq!(
            packet["compilerInputs"]["vendoredBytesMatchCompilerSource"],
            true
        );
        assert_eq!(
            packet["compilerInputs"]["recipeBytesMatchCompilerSource"],
            true
        );
        assert_eq!(packet["compilerInputs"]["ordinaryJavaHeapBytes"], 4_194_304);
        assert_eq!(
            packet["compilerInputs"]["nativeMemoryGrantBytes"],
            67_108_864
        );
        assert_eq!(packet["signingQualified"], false);
        assert_eq!(packet["executionQualified"], false);
        assert_eq!(packet["memoryExhaustionQualified"], false);
        assert_eq!(packet["packagedDistributionQualified"], false);
        assert!(packet.get("recipient").is_none());
        assert!(packet.get("receiptIdentities").is_none());
    }

    #[test]
    fn native_memory_fixture_refuses_old_source_pins_profile_and_partial_sets_before_output() {
        let directory = tempfile::tempdir().unwrap();
        let output = directory.path().join("not-created");
        let paths = vec![OsString::from(directory.path()); NAMES.len()];
        assert!(sign_native_memory_current_java(&output, SOURCE, &[]).is_err());
        for source in [super::super::SOURCE, "unreviewed"] {
            assert!(sign_native_memory_current_java(&output, source, &paths).is_err());
        }
        for (pins, profile, source) in [
            (super::super::FRESH_HTTP_PINS, FRESH_HTTP_PROFILE, SOURCE),
            (PINS, super::super::PROFILE, SOURCE),
            (PINS, FRESH_HTTP_PROFILE, super::super::SOURCE),
        ] {
            assert!(sign_selected(&output, source, &paths, &NAMES, pins, profile, source).is_err());
        }
        assert!(!output.exists());
    }
}
