//! Source-bounded publication maintenance replies; logical bytes are not disk blocks.
use super::{invalid_response, json, proto, Failure, Project, Tree, Value};
use proto::PublicationMaintenanceKind as K;
fn fence(v: &Vec<u8>, b: &mut Tree) -> Result<(), Failure> {
    b.sequence(v, 32)?;
    if v.len() == 32 {
        Ok(())
    } else {
        Err(invalid_response())
    }
}
fn id(v: &String, b: &mut Tree) -> Result<(), Failure> {
    b.text(v, 128)?;
    if v.is_empty() {
        Err(invalid_response())
    } else {
        Ok(())
    }
}
fn selected(v: &proto::PublicationMaintenanceSelection, tenant: &str) -> Result<(), Failure> {
    if v.targets
        .iter()
        .any(|t| t.publication.as_ref().is_none_or(|p| p.tenant != tenant))
    {
        Err(invalid_response())
    } else {
        Ok(())
    }
}
impl Project for proto::PublicationMaintenanceTarget {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        self.publication
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(b)?;
        if self.expected_generation == 0 {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"publication":self.publication.map(Project::project),"expectedGeneration":self.expected_generation.to_string()})
    }
}
impl Project for proto::PublicationMaintenanceSelection {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        id(&self.operation_id, b)?;
        fence(&self.catalog_fence, b)?;
        b.sequence(&self.targets, 32)?;
        if self.targets.is_empty() {
            return Err(invalid_response());
        }
        for target in &self.targets {
            target.validate(b)?;
        }
        if self
            .targets
            .windows(2)
            .any(|p| p[0].publication.as_ref().unwrap().id >= p[1].publication.as_ref().unwrap().id)
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"operationId":self.operation_id,"catalogFence":crate::management::retention::hex(&self.catalog_fence),"targets":self.targets.into_iter().map(Project::project).collect::<Vec<_>>()})
    }
}
impl Project for proto::PublicationMaintenanceCommand {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        let kind = K::try_from(self.kind).map_err(|_| invalid_response())?;
        if kind == K::Unspecified {
            return Err(invalid_response());
        }
        self.selection
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(b)?;
        if kind == K::Reclaim {
            fence(&self.reclamation_catalog_fence, b)?;
            if !(1..=1024).contains(&self.maximum_files)
                || !(1..=1_073_741_824).contains(&self.maximum_bytes_hashed)
            {
                return Err(invalid_response());
            }
        } else if !self.reclamation_catalog_fence.is_empty()
            || self.reclamation_catalog_fence.capacity() != 0
            || self.maximum_files != 0
            || self.maximum_bytes_hashed != 0
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"kind":K::try_from(self.kind).unwrap().as_str_name(),"selection":self.selection.map(Project::project),"reclamationCatalogFence":(!self.reclamation_catalog_fence.is_empty()).then(||crate::management::retention::hex(&self.reclamation_catalog_fence)),"maximumFiles":self.maximum_files,"maximumBytesHashed":self.maximum_bytes_hashed.to_string()})
    }
}
impl Project for proto::PublicationReclamationAccounting {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        if !(1..=32).contains(&self.publications)
            || self.publication_files == 0
            || self.publication_files > 1024
            || self.selected_blobs == 0
            || self.selected_blobs > self.publication_files
            || self
                .last_reference_blobs
                .checked_add(self.shared_blobs_retained)
                != Some(self.selected_blobs)
            || self
                .last_reference_blob_bytes
                .checked_add(self.shared_blob_bytes_retained)
                .is_none_or(|v| v > self.publication_file_bytes)
            || self.bytes_hashed > 1_073_741_824
        {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"publications":self.publications,"publicationFiles":self.publication_files,"publicationFileBytes":self.publication_file_bytes.to_string(),"selectedBlobs":self.selected_blobs,"lastReferenceBlobs":self.last_reference_blobs,"lastReferenceBlobBytes":self.last_reference_blob_bytes.to_string(),"sharedBlobsRetained":self.shared_blobs_retained,"sharedBlobBytesRetained":self.shared_blob_bytes_retained.to_string(),"bytesHashed":self.bytes_hashed.to_string(),"physicalDiskBlocksFreed":null})
    }
}
impl Project for proto::PublicationMaintenanceOperationReceipt {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.tenant, 512)?;
        let actor = self.actor.as_ref().ok_or_else(invalid_response)?;
        actor.validate(b)?;
        if actor.subject.is_empty() || actor.subject.len() > 512 {
            return Err(invalid_response());
        }
        let command = self.command.as_ref().ok_or_else(invalid_response)?;
        command.validate(b)?;
        let selection = command.selection.as_ref().unwrap();
        selected(selection, &self.tenant)?;
        match K::try_from(command.kind).unwrap() {
            K::Reclaim => {
                let content = self.reclaimed.as_ref().ok_or_else(invalid_response)?;
                content.validate(b)?;
                if self.revision != 0
                    || content.publications as usize != selection.targets.len()
                    || content.bytes_hashed > command.maximum_bytes_hashed
                {
                    return Err(invalid_response());
                }
            }
            K::Pin | K::Unpin | K::Delete => {
                if self.revision == 0
                    || self.reclaimed.is_some()
                    || ((command.kind == K::Pin as i32 || command.kind == K::Unpin as i32)
                        && self.reference_revision != 0)
                {
                    return Err(invalid_response());
                }
            }
            K::Unspecified => return Err(invalid_response()),
        }
        Ok(())
    }
    fn project(self) -> Value {
        let kind = self.command.as_ref().unwrap().kind;
        json!({"tenant":self.tenant,"actor":self.actor.map(Project::project),"command":self.command.map(Project::project),"revision":self.revision.to_string(),"referenceRevision":self.reference_revision.to_string(),"stage":if kind==K::Reclaim as i32{"namespaces-reclaimed"}else if kind==K::Delete as i32{"visibility-removed"}else{"retention-updated"},"reclaimed":self.reclaimed.map(Project::project)})
    }
}
impl Project for proto::MaintainPublicationsResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        self.receipt
            .as_ref()
            .ok_or_else(invalid_response)?
            .validate(b)?;
        let ack = self.audit_ack.as_ref().ok_or_else(invalid_response)?;
        ack.validate(b)?;
        if ack.status == proto::AuditAckStatus::Disabled as i32 || ack.attempt_sequence.is_none() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"receipt":self.receipt.map(Project::project),"replay":self.replay,"auditAck":self.audit_ack.map(Project::project)})
    }
}
impl Project for proto::GetPublicationMaintenanceOperationResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        use proto::ReleaseOperationLookupDisposition as D;
        b.message::<Self>()?;
        b.text(&self.tenant, 512)?;
        match D::try_from(self.disposition).map_err(|_| invalid_response())? {
            D::Found => {
                let r = self.receipt.as_ref().ok_or_else(invalid_response)?;
                r.validate(b)?;
                if r.tenant != self.tenant {
                    return Err(invalid_response());
                }
            }
            D::Unknown | D::Uncertain => {
                if self.receipt.is_some() {
                    return Err(invalid_response());
                }
            }
            D::Unspecified => return Err(invalid_response()),
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"tenant":self.tenant,"disposition":proto::ReleaseOperationLookupDisposition::try_from(self.disposition).unwrap().as_str_name(),"receipt":self.receipt.map(Project::project),"automaticReplay":false})
    }
}
impl Project for proto::AssessPublicationReclamationResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.tenant, 512)?;
        fence(&self.catalog_fence, b)?;
        let d = self.deletion.as_ref().ok_or_else(invalid_response)?;
        d.validate(b)?;
        selected(d, &self.tenant)?;
        let p = self.potential.as_ref().ok_or_else(invalid_response)?;
        p.validate(b)?;
        if p.publications as usize != d.targets.len() {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"tenant":self.tenant,"deletion":self.deletion.map(Project::project),"catalogFence":crate::management::retention::hex(&self.catalog_fence),"referenceRevision":self.reference_revision.to_string(),"potential":self.potential.map(Project::project),"authorizesLaterDeletion":false})
    }
}
impl Project for proto::GetPublicationRetentionResponse {
    fn validate(&self, b: &mut Tree) -> Result<(), Failure> {
        b.message::<Self>()?;
        b.text(&self.tenant, 512)?;
        fence(&self.catalog_fence, b)?;
        b.sequence(&self.entries, 32)?;
        if self.entries.is_empty() {
            return Err(invalid_response());
        }
        for entry in &self.entries {
            b.message::<proto::PublicationRetentionEntry>()?;
            let target = entry.target.as_ref().ok_or_else(invalid_response)?;
            target.validate(b)?;
            if target.publication.as_ref().unwrap().tenant != self.tenant {
                return Err(invalid_response());
            }
            if let Some(pin) = &entry.pin {
                b.message::<proto::PublicationRetentionPinRecord>()?;
                id(&pin.operation_id, b)?;
                let a = pin.actor.as_ref().ok_or_else(invalid_response)?;
                a.validate(b)?;
                if a.subject.is_empty()
                    || a.subject.len() > 512
                    || pin.pinned_generation == 0
                    || pin.pinned_generation > target.expected_generation
                {
                    return Err(invalid_response());
                }
            }
        }
        if self.entries.windows(2).any(|v| {
            v[0].target
                .as_ref()
                .unwrap()
                .publication
                .as_ref()
                .unwrap()
                .id
                >= v[1]
                    .target
                    .as_ref()
                    .unwrap()
                    .publication
                    .as_ref()
                    .unwrap()
                    .id
        }) {
            return Err(invalid_response());
        }
        Ok(())
    }
    fn project(self) -> Value {
        json!({"tenant":self.tenant,"catalogFence":crate::management::retention::hex(&self.catalog_fence),"entries":self.entries.into_iter().map(|e|json!({"target":e.target.map(Project::project),"pin":e.pin.map(|p|json!({"pinnedGeneration":p.pinned_generation.to_string(),"operationId":p.operation_id,"actor":p.actor.map(Project::project)}))})).collect::<Vec<_>>()})
    }
}
