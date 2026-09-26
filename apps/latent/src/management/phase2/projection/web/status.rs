use super::{actor, digest, invalid_response, json, proto, text, Failure, Project, Tree, Value};

impl Project for proto::WebLifecycleRecord {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        use proto::{ReleaseLifecycleReason as Reason, ReleaseLifecycleState as State};

        tree.message::<Self>()?;
        let reference = self.publication.as_ref().ok_or_else(invalid_response)?;
        reference.validate(tree)?;
        for value in [
            &self.package_digest,
            &self.web_manifest_digest,
            &self.assets_digest,
        ] {
            digest(value, tree)?;
        }
        let package = self
            .package_digest
            .parse()
            .map_err(|_| invalid_response())?;
        if crate::management::web::publication(&package, &reference.tenant)? != *reference
            || self.generation == 0
        {
            return Err(invalid_response());
        }
        actor(self.actor.as_ref(), tree)?;
        text(&self.operation_id, 128, tree)?;
        if let Some(value) = &self.evidence_revision_digest {
            digest(value, tree)?;
        }
        match (State::try_from(self.state), Reason::try_from(self.reason)) {
            (Ok(State::Admitted), Ok(Reason::Admitted)) if self.generation == 1 => {}
            (Ok(State::Admitted), Ok(Reason::EvidenceRenewed))
            | (
                Ok(State::Revoked),
                Ok(Reason::OperatorRevocation | Reason::SecurityIncident | Reason::CorruptContent),
            )
            | (
                Ok(State::Retired),
                Ok(Reason::OperatorRetirement | Reason::Superseded | Reason::EndOfSupport),
            ) if self.generation > 1 => {}
            _ => return Err(invalid_response()),
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({
            "publication": self.publication.map(Project::project),
            "packageDigest": self.package_digest,
            "webManifestDigest": self.web_manifest_digest,
            "assetsDigest": self.assets_digest,
            "state": proto::ReleaseLifecycleState::try_from(self.state).expect("validated state").as_str_name(),
            "generation": self.generation.to_string(),
            "actor": self.actor.map(Project::project),
            "reason": proto::ReleaseLifecycleReason::try_from(self.reason).expect("validated reason").as_str_name(),
            "operationId": self.operation_id,
            "evidenceRevisionDigest": self.evidence_revision_digest,
        })
    }
}

impl Project for proto::WebRendererDescriptor {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        use latent_artifacts::web::{
            renderer_profile_digest, WebRendererProfile, MAX_WEB_RENDERER_BYTES,
        };

        tree.message::<Self>()?;
        digest(&self.component_digest, tree)?;
        digest(&self.profile_digest, tree)?;
        let profile = match proto::WebRendererProfile::try_from(self.profile) {
            Ok(proto::WebRendererProfile::WasmWebBufferedV1) => {
                WebRendererProfile::WasmWebBufferedV1
            }
            Ok(proto::WebRendererProfile::AngularSsrComponentV1) => {
                WebRendererProfile::AngularSsrComponentV1
            }
            _ => return Err(invalid_response()),
        };
        if self.profile_digest != renderer_profile_digest(profile).to_string()
            || self.component_bytes == 0
            || self.component_bytes > MAX_WEB_RENDERER_BYTES
        {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({
            "componentDigest": self.component_digest,
            "profile": proto::WebRendererProfile::try_from(self.profile).expect("validated profile").as_str_name(),
            "profileDigest": self.profile_digest,
            "componentBytes": self.component_bytes.to_string(),
        })
    }
}

impl Project for proto::GetWebPublicationResponse {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        use proto::{ReleaseEligibilityReason as Reason, ReleaseLiveEligibility as Live};

        tree.message::<Self>()?;
        let record = self.record.as_ref().ok_or_else(invalid_response)?;
        record.validate(tree)?;
        if let Some(renderer) = &self.renderer {
            renderer.validate(tree)?;
        }
        let valid = match (
            Live::try_from(self.eligibility),
            Reason::try_from(self.eligibility_reason),
        ) {
            (Ok(Live::Denied), Ok(Reason::Revoked)) => {
                record.state == proto::ReleaseLifecycleState::Revoked as i32
            }
            (Ok(Live::Denied), Ok(Reason::Retired)) => {
                record.state == proto::ReleaseLifecycleState::Retired as i32
            }
            (Ok(Live::Eligible), Ok(Reason::Verified))
            | (Ok(Live::Denied), Ok(Reason::PolicyDenied | Reason::RuntimeIncompatible))
            | (Ok(Live::Unknown), Ok(Reason::AuthorityUnavailable)) => {
                record.state == proto::ReleaseLifecycleState::Admitted as i32
            }
            _ => false,
        };
        if !valid {
            return Err(invalid_response());
        }
        Ok(())
    }

    fn project(self) -> Value {
        json!({
            "record": self.record.map(Project::project),
            "eligibility": proto::ReleaseLiveEligibility::try_from(self.eligibility).expect("validated eligibility").as_str_name(),
            "eligibilityReason": proto::ReleaseEligibilityReason::try_from(self.eligibility_reason).expect("validated reason").as_str_name(),
            "renderer": self.renderer.map(Project::project),
        })
    }
}
