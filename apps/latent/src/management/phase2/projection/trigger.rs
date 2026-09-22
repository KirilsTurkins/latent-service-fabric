use super::{invalid_response, json, proto, Failure, Project, Tree, Value};
use crate::management::canonical_digest;

impl Project for proto::TriggerOperationReceipt {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        for value in [&self.tenant, &self.operation_id, &self.trigger_id] {
            tree.text(value, 128)?;
            if value.is_empty() {
                return Err(invalid_response());
            }
        }
        for value in [
            &self.request_digest,
            &self.manifest_digest,
            &self.receipt_digest,
        ] {
            tree.text(value, 71)?;
            if !canonical_digest(value) {
                return Err(invalid_response());
            }
        }
        let actor = self.actor.as_ref().ok_or_else(invalid_response)?;
        actor.validate(tree)?;
        let (publication, application) = match self.format_version {
            1 if self.target.is_none() => (
                self.publication.as_ref().ok_or_else(invalid_response)?,
                Some((
                    &self.component_digest,
                    &self.deployment_id,
                    self.deployment_generation,
                    &self.revision,
                )),
            ),
            2 if self.publication.is_none()
                && self.component_digest.is_empty()
                && self.deployment_id.is_empty()
                && self.deployment_generation == 0
                && self.revision.is_empty() =>
            {
                let target = self.target.as_ref().ok_or_else(invalid_response)?;
                target.validate(tree)?;
                (
                    target.publication.as_ref().ok_or_else(invalid_response)?,
                    (target.kind == proto::TriggerReceiptTargetKind::Application as i32).then_some(
                        (
                            &target.component_digest,
                            &target.deployment_id,
                            target.deployment_generation,
                            &target.revision,
                        ),
                    ),
                )
            }
            _ => return Err(invalid_response()),
        };
        publication.validate(tree)?;
        // Charge even forbidden legacy fields before projecting a v2 response.
        tree.text(&self.component_digest, 71)?;
        tree.text(&self.deployment_id, 128)?;
        tree.text(&self.revision, 128)?;
        if publication.tenant != self.tenant
            || self.expected_state_version.checked_add(1) != Some(self.state_version)
            || self.route_generation == 0
            || self.route_generation > self.state_version
        {
            return Err(invalid_response());
        }
        if let Some((component, deployment, generation, revision)) = application {
            if !canonical_digest(component)
                || deployment.is_empty()
                || generation == 0
                || generation > self.route_generation
                || !revision
                    .strip_prefix("revision-v1:")
                    .is_some_and(canonical_digest)
            {
                return Err(invalid_response());
            }
        }
        match proto::TriggerOperationAction::try_from(self.action) {
            Ok(proto::TriggerOperationAction::Apply)
                if self.object_generation == self.state_version
                    && self.expected_generation < self.object_generation => {}
            Ok(proto::TriggerOperationAction::Delete)
                if self.object_generation == self.expected_generation
                    && self.object_generation > 0
                    && self.object_generation < self.state_version => {}
            _ => return Err(invalid_response()),
        }
        Ok(())
    }

    fn project(self) -> Value {
        let mut value = json!({"formatVersion":self.format_version,"tenant":self.tenant,
            "actor":self.actor.map(Project::project),"operationId":self.operation_id,
            "action":proto::TriggerOperationAction::try_from(self.action).expect("validated action").as_str_name(),
            "triggerId":self.trigger_id,"requestDigest":self.request_digest,
            "expectedStateVersion":self.expected_state_version.to_string(),
            "expectedGeneration":self.expected_generation.to_string(),
            "objectGeneration":self.object_generation.to_string(),"stateVersion":self.state_version.to_string(),
            "routeGeneration":self.route_generation.to_string(),"manifestDigest":self.manifest_digest,
            "completedAtUnixMillis":self.completed_at_unix_millis.to_string(),
            "receiptDigest":self.receipt_digest});
        if let Some(target) = self.target {
            value["target"] = target.project();
        } else {
            value["publication"] = self.publication.map_or(Value::Null, Project::project);
            value["componentDigest"] = json!(self.component_digest);
            value["deploymentId"] = json!(self.deployment_id);
            value["deploymentGeneration"] = json!(self.deployment_generation.to_string());
            value["revision"] = json!(self.revision);
        }
        value
    }
}

impl Project for proto::TriggerReceiptTarget {
    fn validate(&self, tree: &mut Tree) -> Result<(), Failure> {
        tree.message::<Self>()?;
        self.publication
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(tree)?;
        for value in [
            &self.component_digest,
            &self.web_manifest_digest,
            &self.assets_digest,
        ] {
            tree.text(value, 71)?;
        }
        tree.text(&self.deployment_id, 128)?;
        tree.text(&self.revision, 128)?;
        match proto::TriggerReceiptTargetKind::try_from(self.kind) {
            Ok(proto::TriggerReceiptTargetKind::Application)
                if canonical_digest(&self.component_digest)
                    && !self.deployment_id.is_empty()
                    && self.deployment_generation > 0
                    && self
                        .revision
                        .strip_prefix("revision-v1:")
                        .is_some_and(canonical_digest)
                    && self.web_manifest_digest.is_empty()
                    && self.assets_digest.is_empty()
                    && self.web_generation == 0 =>
            {
                Ok(())
            }
            Ok(proto::TriggerReceiptTargetKind::StaticWeb)
                if self.component_digest.is_empty()
                    && self.deployment_id.is_empty()
                    && self.deployment_generation == 0
                    && self.revision.is_empty()
                    && canonical_digest(&self.web_manifest_digest)
                    && canonical_digest(&self.assets_digest)
                    && self.web_generation > 0 =>
            {
                Ok(())
            }
            _ => Err(invalid_response()),
        }
    }

    fn project(self) -> Value {
        let mut value = json!({"publication":self.publication.map(Project::project)});
        if self.kind == proto::TriggerReceiptTargetKind::Application as i32 {
            value["kind"] = json!("application");
            value["componentDigest"] = json!(self.component_digest);
            value["deploymentId"] = json!(self.deployment_id);
            value["deploymentGeneration"] = json!(self.deployment_generation.to_string());
            value["revision"] = json!(self.revision);
        } else {
            value["kind"] = json!("static-web");
            value["webManifestDigest"] = json!(self.web_manifest_digest);
            value["assetsDigest"] = json!(self.assets_digest);
            value["webGeneration"] = json!(self.web_generation.to_string());
        }
        value
    }
}
