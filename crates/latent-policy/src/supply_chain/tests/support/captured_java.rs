//! New signatures over supplied captured Java bytes, never another compiler run.
use super::*;
use latent_packaging::PackageInput;

impl Fixture {
    pub fn captured_java() -> Self {
        let mut fixture = Self::new();
        let requirement = &mut fixture.policy["builder"]["requirements"][0];
        requirement["buildType"] = JAVA_CAPSULE_BUILD_TYPE.into();
        requirement["sourceRepository"] =
            "https://github.com/KirilsTurkins/latent-service-fabric".into();
        fixture.policy["builderRevocations"]["policyDigest"] = BuilderPolicy::from_json(
            &serde_json::to_vec(&fixture.policy["builder"]).unwrap(),
            ProvenanceLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string()
        .into();
        fixture.policy["tenants"]
            .as_array_mut()
            .unwrap()
            .push(json!({"tenant":"examples","publishers":["publisher-a"]}));
        fixture
    }

    pub fn captured_java_upload(
        &self,
        input: PackageInput,
        mut observed: BuildObservation,
    ) -> PackageAdmissionUpload {
        assert_eq!(observed.build_type, JAVA_CAPSULE_BUILD_TYPE);
        let inputs = serde_json::to_vec(&json!({
            "name":input.name,"version":input.version,"entrypoint":input.entrypoint,
            "annotations":input.annotations,"layers":input.layers.iter().map(|layer| {
                json!({"path":layer.path,"role":layer.role,"mediaType":layer.media_type,
                    "digest":artifact_blob_digest(&layer.bytes).as_str(),"bytes":layer.bytes.len()})
            }).collect::<Vec<_>>()
        }))
        .unwrap();
        let package_inputs = observed
            .materials
            .iter_mut()
            .find(|material| material.name == "package-inputs")
            .unwrap();
        package_inputs.digest = artifact_blob_digest(&inputs).to_string();
        package_inputs.size = inputs.len() as u64;
        let inventory = sbom::inventory(&input);
        let bundle = build_package_with_sbom(
            input,
            inventory,
            PackagingLimits {
                manifest_profile: packaging::transaction_profile(),
                ..Default::default()
            },
        )
        .unwrap();
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        assert_eq!(
            observed.component_digest,
            subject.component_digest().unwrap().as_str()
        );
        assert_eq!(observed.component_size, subject.component_size().unwrap());
        // The existing fixture clock bounds this newly issued test statement.
        // Captured materials/recipe stay literal Java; no Rust build is claimed.
        observed.started_at = 900;
        observed.finished_at = 1000;
        let validity = SignatureValidity {
            issued_at: 1000,
            expires_at: 2000,
        };
        let signature = self
            .publisher_signer
            .sign_package(&subject, validity, SignatureLimits::default())
            .unwrap();
        let provenance = self
            .builder_signer
            .sign_build(&subject, &observed, validity, ProvenanceLimits::default())
            .unwrap();
        PackageAdmissionUpload {
            manifest: bundle.manifest_bytes().to_vec(),
            configuration: bundle.config_bytes().to_vec(),
            layers: bundle
                .layers()
                .iter()
                .map(|blob| (blob.path().to_owned(), blob.bytes().to_vec()))
                .collect(),
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
        }
    }
}
