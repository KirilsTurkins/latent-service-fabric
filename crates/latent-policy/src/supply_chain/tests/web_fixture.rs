use super::*;
use latent_artifacts::{
    package::{LayerRole, PackageKind},
    web::*,
};
use latent_packaging::{LayerInput, PackageInput};
use std::collections::BTreeMap;

pub fn web_input(renderer: Option<&[u8]>) -> PackageInput {
    let html = b"<h1>Example</h1>";
    let asset = WebAsset {
        path: "/index.html".into(),
        layer: "public/index.html".into(),
        digest: artifact_blob_digest(html).to_string(),
        size: html.len() as u64,
        media_type: "text/html".into(),
    };
    let assets = vec![asset];
    let assets_digest = asset_tree_digest(&assets).unwrap().to_string();
    let web = WebApplicationManifest {
        format_version: 1,
        profile: WEB_RELEASE_PROFILE.into(),
        assets_digest: assets_digest.clone(),
        assets,
        routes: vec![WebRoute {
            path: "/".into(),
            mode: if renderer.is_some() {
                WebRenderMode::Server
            } else {
                WebRenderMode::Client
            },
            asset: renderer.is_none().then(|| "/index.html".into()),
        }],
        static_routing: None,
        renderer: renderer.map(|bytes| WebRenderer {
            layer: "server/renderer.wasm".into(),
            digest: artifact_blob_digest(bytes).to_string(),
            size: bytes.len() as u64,
            profile: WebRendererProfile::WasmWebBufferedV1,
            profile_digest: renderer_profile_digest(WebRendererProfile::WasmWebBufferedV1)
                .to_string(),
            assets_digest,
            backend_profile: WebBackendProfile::None,
        }),
    };
    let mut layers = vec![
        LayerInput {
            path: "public/index.html".into(),
            role: LayerRole::Asset,
            media_type: "text/html".into(),
            bytes: html.to_vec(),
        },
        LayerInput {
            path: WEB_MANIFEST_PATH.into(),
            role: LayerRole::Asset,
            media_type: "application/json".into(),
            bytes: serde_json::to_vec(&web).unwrap(),
        },
        LayerInput {
            path: "metadata/private.json".into(),
            role: LayerRole::Asset,
            media_type: "application/json".into(),
            bytes: b"{}".to_vec(),
        },
    ];
    if let Some(bytes) = renderer {
        layers.push(LayerInput {
            path: "server/renderer.wasm".into(),
            role: LayerRole::Renderer,
            media_type: "application/wasm".into(),
            bytes: bytes.to_vec(),
        });
    }
    PackageInput {
        kind: if renderer.is_some() {
            PackageKind::SsrPackage
        } else {
            PackageKind::BrowserAssets
        },
        name: "web-example".into(),
        version: "1.0.0".into(),
        entrypoint: if renderer.is_some() {
            "server/renderer.wasm"
        } else {
            "public/index.html"
        }
        .into(),
        annotations: BTreeMap::new(),
        layers,
    }
}

impl Fixture {
    pub fn enable_web_builder(&mut self) {
        let mut requirement = self.policy["builder"]["requirements"][0].clone();
        requirement["buildType"] = WEB_ASSEMBLY_BUILD_TYPE.into();
        self.policy["builder"]["requirements"]
            .as_array_mut()
            .unwrap()
            .push(requirement);
        let builder = BuilderPolicy::from_json(
            &serde_json::to_vec(&self.policy["builder"]).unwrap(),
            ProvenanceLimits::default(),
        )
        .unwrap();
        self.policy["builderRevocations"]["policyDigest"] = builder.digest().to_string().into();
    }

    pub fn web_upload(
        &self,
        input: PackageInput,
        with_inventory: bool,
        corrected: bool,
    ) -> PackageAdmissionUpload {
        let bundle = if with_inventory {
            let mut inventory = sbom::inventory(&input);
            if corrected {
                inventory.entries[0].license_expression = Some("MIT".into());
            }
            build_package_with_sbom(input, inventory, PackagingLimits::default()).unwrap()
        } else {
            latent_packaging::build_package(input, PackagingLimits::default()).unwrap()
        };
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let outputs = subject.web_outputs().unwrap();
        // A trusted test builder's assertions test policy and byte binding here.
        // Production observed assembly and compiler qualification are separate.
        let snapshot = format!("sha256:{}", "b".repeat(64));
        let observed = WebBuildObservation {
            format_version: 1,
            build_type: WEB_ASSEMBLY_BUILD_TYPE.into(),
            source: BuildSource {
                repository: "https://example.com/source".into(),
                revision: "b".repeat(64),
                snapshot_digest: snapshot.clone(),
                repository_trust: "operator-asserted".into(),
                capture: "explicit-input-files".into(),
            },
            outputs_digest: outputs.digest().to_string(),
            outputs_count: outputs.count(),
            outputs_bytes: outputs.bytes(),
            materials: [
                "source-snapshot",
                "build-recipe",
                "toolchain-config",
                "package-assembler",
            ]
            .into_iter()
            .map(|name| BuildMaterial {
                name: name.into(),
                digest: snapshot.clone(),
                size: 1,
            })
            .collect(),
            parameters: WebAssemblyRecipe {
                assembler: "lsf-web-package-assembly".into(),
                recipe_version: 1,
                input_mode: "explicit-supplied-files".into(),
            }
            .into(),
            started_at: 900,
            finished_at: 1000,
            reproducibility: "not-checked".into(),
            hermetic: false,
            dependency_completeness: "declared-inputs-incomplete".into(),
        };
        self.sign_observed_web(bundle, &observed, 1000)
    }

    pub fn sign_observed_web(
        &self,
        bundle: PackageBundle,
        observed: &WebBuildObservation,
        issued_at: u64,
    ) -> PackageAdmissionUpload {
        let subject = PackageSigningSubject::from_package(
            bundle.manifest_bytes(),
            bundle.config_bytes(),
            PackageLimits::default(),
        )
        .unwrap();
        let validity = SignatureValidity {
            issued_at,
            expires_at: issued_at + 1000,
        };
        let signature = self
            .publisher_signer
            .sign_package(&subject, validity, SignatureLimits::default())
            .unwrap();
        let provenance = self
            .builder_signer
            .sign_web_build(&subject, observed, validity, ProvenanceLimits::default())
            .unwrap();
        let input = bundle.into_input();
        PackageAdmissionUpload {
            manifest: input.manifest,
            configuration: input.configuration,
            layers: input.layers,
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

    /// Approve the maintained test builder at the actual observation time.
    /// Observed bytes and timestamps are never rewritten to fit fixture clocks.
    pub fn enable_observed_angular_builder(&mut self, now: u64) {
        fn shift(value: &mut Value, delta: u64) {
            match value {
                Value::Object(object) => {
                    for (key, value) in object {
                        if matches!(key.as_str(), "validFrom" | "validUntil") {
                            *value = (value.as_u64().unwrap() + delta).into();
                        } else {
                            shift(value, delta);
                        }
                    }
                }
                Value::Array(array) => {
                    for value in array {
                        shift(value, delta);
                    }
                }
                _ => (),
            }
        }
        shift(&mut self.policy, now - NOW);
        self.clock.set(now);
        self.policy["builder"]["requirements"][0]["buildType"] = ANGULAR_BUILD_TYPE.into();
        self.policy["publisherRevocations"]["policyDigest"] = PublisherPolicy::from_json(
            &serde_json::to_vec(&self.policy["publisher"]).unwrap(),
            SignatureLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string()
        .into();
        self.policy["builderRevocations"]["policyDigest"] = BuilderPolicy::from_json(
            &serde_json::to_vec(&self.policy["builder"]).unwrap(),
            ProvenanceLimits::default(),
        )
        .unwrap()
        .digest()
        .to_string()
        .into();
    }
}
