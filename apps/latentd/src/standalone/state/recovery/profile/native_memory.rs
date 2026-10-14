//! Exactly the newly captured component; older associations keep their proofs.
pub(super) const COMPONENT: &str =
    "sha256:b46606299b77eeb9efb12abb2bdb793d5bba78bb1f8dc42d1be4bc92f5463115";

#[cfg(test)]
mod tests {
    use super::super::{digest, CurrentHttpInput, HttpCustody, Profile};
    use super::COMPONENT;

    fn input() -> CurrentHttpInput<'static> {
        CurrentHttpInput {
            component: COMPONENT,
            companion: "sha256:24a689c7166ffbdbaacefa8d7d7efe18a98d532adc94fc4392968aaab837349d",
            marker: include_bytes!("fixtures/http-marker-fresh.json"),
            requirements_digest:
                "sha256:49c9b8af6be278198d286b776f492e0fda9a6621b9b2fcd36aa788d77a2e5c54",
            requirements: include_bytes!("fixtures/http-requirements-fresh.json"),
        }
    }

    #[test]
    fn native_memory_component_review_preserves_original_diagnostic_codec_proof() {
        let proof = [
            49, 186, 144, 162, 90, 169, 122, 133, 119, 155, 3, 84, 24, 4, 75, 30, 85, 33, 148, 209,
            193, 148, 207, 159, 239, 93, 169, 229, 149, 63, 111, 100,
        ];
        assert_eq!(
            Profile::CurrentDiagnostic
                .conformance_with_marker(HttpCustody::Fresh.marker())
                .unwrap(),
            proof
        );
        let profile =
            Profile::installed(COMPONENT).expect("only the captured component is installed");
        assert_eq!(profile, Profile::CurrentDiagnostic);
        let packet: serde_json::Value = serde_json::from_slice(include_bytes!(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../docs/testing/evidence/java-current-native-memory-capture-2026-10-14.json"
        )))
        .unwrap();
        let materials = &packet["captures"]["variants"]["put-once-diagnostics"]["materials"];
        let source = include_bytes!("fixtures/native-memory-diagnostic.java");
        let declaration = include_bytes!("fixtures/native-memory-diagnostic-schema.json");
        let input = input();
        assert_eq!(materials["component"]["sha256"], COMPONENT);
        assert_eq!(materials["companion"]["sha256"], input.companion);
        assert_eq!(
            materials["requirements"]["sha256"],
            input.requirements_digest
        );
        assert_eq!(
            materials["currentHttpMarker"]["sha256"],
            format!("sha256:{}", digest(input.marker))
        );
        assert_eq!(
            materials["capsuleSource"]["sha256"],
            format!("sha256:{}", digest(source))
        );
        assert_eq!(
            materials["applicationSchemaInputs"]["sha256"],
            format!("sha256:{}", digest(declaration))
        );
        let schema = profile
            .review([1; 32], declaration, source, None, Some(input))
            .expect("the exact new diagnostic tuple preserves the captured codec");
        assert_eq!(schema.proof_digest(), proof);
        assert_eq!(packet["memoryExhaustionQualified"], false);
    }

    #[test]
    fn native_memory_review_refuses_original_marker_foreign_profile_source_and_unknown_component() {
        let input = input();
        for changed in [
            CurrentHttpInput {
                component:
                    "sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
                ..input
            },
            CurrentHttpInput {
                companion:
                    "sha256:e5719a610fb20811a402aed0531d13d71547978104048d9e275ae7b7ae061c49",
                ..input
            },
            CurrentHttpInput {
                marker: include_bytes!("fixtures/http-marker-original.json"),
                requirements_digest:
                    "sha256:dfa7b1459dbe78c9dc1a43aef3171916d84f78f49fc8df50ea09dc13036f80ab",
                requirements: include_bytes!("fixtures/http-requirements-original.json"),
                ..input
            },
            CurrentHttpInput {
                marker: b"unreviewed",
                ..input
            },
            CurrentHttpInput {
                requirements: include_bytes!("fixtures/http-writer-requirements-fresh.json"),
                ..input
            },
        ] {
            assert!(HttpCustody::select(Profile::CurrentDiagnostic, &changed).is_err());
        }
        assert!(HttpCustody::select(Profile::CurrentLegacy, &input).is_err());
        let declaration = include_bytes!("fixtures/native-memory-diagnostic-schema.json");
        assert!(Profile::CurrentDiagnostic
            .review([1; 32], declaration, b"changed source", None, Some(input))
            .is_err());
        assert!(Profile::CurrentDiagnostic
            .review(
                [1; 32],
                include_bytes!("fixtures/current-legacy-schema.json"),
                include_bytes!("fixtures/current-legacy.java"),
                None,
                Some(input),
            )
            .is_err());
    }
}
