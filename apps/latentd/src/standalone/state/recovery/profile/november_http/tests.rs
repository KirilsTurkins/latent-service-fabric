use super::*;
use serde_json::Value;

const PACKET: &[u8] = include_bytes!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../docs/testing/evidence/java-current-http-capture-2026-11-04.json"
));
const MARKER_BYTES: &[u8] = include_bytes!("../fixtures/http-marker-november.json");
const REQUIREMENTS_BYTES: &[u8] = include_bytes!("../fixtures/http-requirements-november.json");
const WRITER_BYTES: &[u8] = include_bytes!("../fixtures/http-writer-requirements-november.json");

fn input(profile: Profile) -> CurrentHttpInput<'static> {
    let (component, writer) = match profile {
        Profile::CurrentLegacy => (
            "sha256:355dbd17c29b2a8756d5dfccb34582e878b03fd299c35c0652cbec4bb7d7338a",
            false,
        ),
        Profile::CurrentCompatible => (
            "sha256:6c31f6763a5d3d8d84aa0668a44b220c3ba619f9c257e9a0d0b441e58d94099b",
            false,
        ),
        Profile::CurrentWriter => (
            "sha256:5f2f4bd6880bf516f042d65b2fc65d06ad80036a82b7ad60a2b95438972546a8",
            true,
        ),
        Profile::CurrentDiagnostic => (
            "sha256:25258bd576a7ee6e79f20a0b7a13e10293780fce310d03f529ac811c7ccdc5e0",
            false,
        ),
        _ => panic!("current capture required"),
    };
    CurrentHttpInput {
        component,
        companion: if writer {
            "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49"
        } else {
            "sha256:24a689c7166ffbdbaacefa8d7d7efe18a98d532adc94fc4392968aaab837349d"
        },
        marker: MARKER_BYTES,
        requirements_digest: if writer {
            "sha256:2734a95873297041cbe25c5bae27b4c95c2367d57cfd82971e28c41892887eaf"
        } else {
            "sha256:17166184306ac8a81d3d0e13256afc64550403b1a6fe18e02386035dd9a7ffb8"
        },
        requirements: if writer {
            WRITER_BYTES
        } else {
            REQUIREMENTS_BYTES
        },
    }
}

#[test]
fn november_exact_component_marker_and_requirement_associations_are_installed() {
    let packet: Value = serde_json::from_slice(PACKET).unwrap();
    for (profile, name) in [
        (Profile::CurrentLegacy, "put-once-legacy-v1"),
        (Profile::CurrentCompatible, "put-once-compatible-v2"),
        (Profile::CurrentWriter, "put-once-writer-v2"),
        (Profile::CurrentDiagnostic, "put-once-diagnostics"),
    ] {
        let item = input(profile);
        let pin = &packet["captures"]["variants"][name]["materials"];
        assert_eq!(pin["component"]["sha256"], item.component);
        assert_eq!(pin["companion"]["sha256"], item.companion);
        assert_eq!(
            pin["currentHttpMarker"]["sha256"],
            format!("sha256:{}", digest(item.marker))
        );
        assert_eq!(pin["requirements"]["sha256"], item.requirements_digest);
        assert_eq!(Profile::installed(item.component).unwrap(), profile);
        assert_eq!(
            SelectedHttpCustody::select(profile, &item).unwrap(),
            SelectedHttpCustody::November
        );
        let (declaration, source, codec): (&[u8], &[u8], Option<&[u8]>) = match profile {
            Profile::CurrentLegacy => (
                include_bytes!("../fixtures/current-legacy-schema.json"),
                include_bytes!("../fixtures/current-legacy.java"),
                None,
            ),
            Profile::CurrentCompatible => (
                include_bytes!("../fixtures/current-compatible-reconstructed-schema.json"),
                include_bytes!("../fixtures/current-compatible-reconstructed.java"),
                Some(include_bytes!(concat!(
                    env!("CARGO_MANIFEST_DIR"),
                    "/../../examples/java-transaction-schema/AggregateCodec.java"
                ))),
            ),
            Profile::CurrentWriter => (
                include_bytes!("../fixtures/current-writer-reconstructed-schema.json"),
                include_bytes!("../fixtures/current-writer-reconstructed.java"),
                Some(include_bytes!(concat!(
                    env!("CARGO_MANIFEST_DIR"),
                    "/../../examples/java-transaction-schema/AggregateCodec.java"
                ))),
            ),
            Profile::CurrentDiagnostic => (
                include_bytes!("../fixtures/native-memory-diagnostic-schema.json"),
                include_bytes!("../fixtures/native-memory-diagnostic.java"),
                None,
            ),
            _ => unreachable!(),
        };
        assert_eq!(
            pin["capsuleSource"]["sha256"],
            format!("sha256:{}", digest(source))
        );
        assert_eq!(
            pin["applicationSchemaInputs"]["sha256"],
            format!("sha256:{}", digest(declaration))
        );
        let reviewed = profile
            .review([1; 32], declaration, source, codec, Some(item))
            .unwrap();
        assert_eq!(
            reviewed.proof_digest(),
            profile.conformance_with_marker(MARKER).unwrap()
        );
    }
}

#[test]
fn november_custody_rejects_mixed_or_unreviewed_inputs() {
    let original = input(Profile::CurrentLegacy);
    for changed in [
        CurrentHttpInput {
            component: input(Profile::CurrentCompatible).component,
            ..original
        },
        CurrentHttpInput {
            companion: input(Profile::CurrentWriter).companion,
            ..original
        },
        CurrentHttpInput {
            marker: include_bytes!("../fixtures/http-marker-refreshed.json"),
            ..original
        },
        CurrentHttpInput {
            requirements: WRITER_BYTES,
            ..original
        },
        CurrentHttpInput {
            requirements_digest: input(Profile::CurrentWriter).requirements_digest,
            ..original
        },
    ] {
        assert!(SelectedHttpCustody::select(Profile::CurrentLegacy, &changed).is_err());
    }
}
