//! Admit the observed Angular frontend under the same isolated demo trust as its guests.
use super::{directory, write, Result, TENANT};
use latent_artifacts::{package::PackageLimits, AdmissionEvidence, ReleaseEvidenceUpload};
use latent_core::TenantId;
use latent_packaging::{
    inspect_web_bundle, read_package_directory, read_package_file, write_package_directory,
    write_package_evidence, PackageBundle, PackagingLimits,
};
use latent_policy::supply_chain::{
    verify_web_package_once, PackageVerificationRequest, SupplyChainPolicy,
};
use latent_signing::{
    decode_web_build_observation, LocalBuilderSigner, LocalSigner, PackageSigningSubject,
    ProvenanceLimits, SignatureLimits, SignatureValidity, WebBuildObservation, ANGULAR_BUILD_TYPE,
};
use serde_json::{json, Value};
use std::path::Path;

pub(super) struct WebBuild {
    bundle: PackageBundle,
    raw_observation: Vec<u8>,
    pub observation: WebBuildObservation,
}

impl WebBuild {
    pub fn load(root: &Path) -> Result<Self> {
        let raw_observation =
            read_package_file(root, "observation.json", 65536).map_err(|error| error.message)?;
        let observation =
            decode_web_build_observation(&raw_observation, ProvenanceLimits::default())?;
        let limits = PackagingLimits::default();
        let bundle =
            read_package_directory(&root.join("package"), limits).map_err(|error| error.message)?;
        let layout =
            inspect_web_bundle(&bundle, limits.semantics).map_err(|error| error.message)?;
        if observation.build_type != ANGULAR_BUILD_TYPE
            || layout.name() != "stateful-reference"
            || !layout.manifest().renderer.as_ref().is_some_and(|renderer| {
                renderer.profile == latent_manifest::RendererProfile::AngularSsrComponentV1
                    && renderer.backend_profile
                        == latent_artifacts::web::WebBackendProfile::ScopedHttpGetV1
            })
        {
            return Err("observed stateful Angular build required".into());
        }
        let outputs = latent_artifacts::web::web_build_outputs(bundle.layout())
            .map_err(|error| error.message)?;
        if outputs.digest().as_str() != observation.outputs_digest
            || outputs.count() != observation.outputs_count
            || outputs.bytes() != observation.outputs_bytes
        {
            return Err("Angular build output differs from observation".into());
        }
        Ok(Self {
            bundle,
            raw_observation,
            observation,
        })
    }

    pub fn name(&self) -> &str {
        &self.bundle.layout().config().name
    }

    pub fn sign(
        self,
        output: &Path,
        publisher: &LocalSigner,
        builder: &LocalBuilderSigner,
        policy: &SupplyChainPolicy,
        validity: SignatureValidity,
    ) -> Result<Value> {
        let subject = PackageSigningSubject::from_package(
            self.bundle.manifest_bytes(),
            self.bundle.config_bytes(),
            PackageLimits::default(),
        )?;
        let signature = publisher.sign_package(&subject, validity, SignatureLimits::default())?;
        let provenance = builder.sign_web_build(
            &subject,
            &self.observation,
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
        verify_web_package_once(
            policy,
            PackageVerificationRequest {
                tenant: &TenantId(TENANT.into()),
                package: &self.bundle,
                evidence: &evidence,
                unix_seconds: validity.issued_at,
            },
        )
        .map_err(|error| error.message)?;
        let layout = inspect_web_bundle(&self.bundle, PackagingLimits::default().semantics)
            .map_err(|error| error.message)?;
        let destination = output.join(self.name());
        directory(&destination)?;
        write_package_directory(&self.bundle, &destination.join("package"))
            .map_err(|error| error.message)?;
        write_package_evidence(
            layout.package(),
            &evidence,
            &destination.join("evidence"),
            1024 * 1024,
        )
        .map_err(|error| error.message)?;
        write(
            &destination.join("build-observation.json"),
            &self.raw_observation,
        )?;
        Ok(json!({
            "name": self.name(),
            "packageDigest": layout.package().to_string(),
            "manifestDigest": layout.manifest_digest().to_string(),
            "assetsDigest": layout.assets_digest().to_string(),
            "assets": layout.manifest().assets,
            "renderer": layout.manifest().renderer,
        }))
    }
}
