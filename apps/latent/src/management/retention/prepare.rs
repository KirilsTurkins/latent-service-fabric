use super::{invalid, proto, MaintenanceOperation};
use crate::{
    args::retention::{Kind, RetentionCommand, Selection, Wait, Work},
    config::ResolvedConfig,
    error::Failure,
    operation::Operation,
};
use proto::PublicationMaintenanceKind as K;
fn id(value: &str) -> Result<(), Failure> {
    if value.is_empty() || value.len() > 128 || value.chars().any(char::is_control) {
        Err(invalid())
    } else {
        Ok(())
    }
}
fn fence(value: &str) -> Result<Vec<u8>, Failure> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(invalid());
    }
    value
        .as_bytes()
        .chunks_exact(2)
        .map(|p| {
            u8::from_str_radix(std::str::from_utf8(p).map_err(|_| invalid())?, 16)
                .map_err(|_| invalid())
        })
        .collect()
}
fn publication(value: &str, tenant: &str) -> Result<proto::PublicationRef, Failure> {
    value
        .parse::<latent_core::PublicationId>()
        .map_err(|_| invalid())?;
    Ok(proto::PublicationRef {
        id: value.into(),
        tenant: tenant.into(),
    })
}
fn targets(
    values: &[String],
    tenant: &str,
) -> Result<Vec<proto::PublicationMaintenanceTarget>, Failure> {
    if values.is_empty() || values.len() > 32 {
        return Err(invalid());
    }
    let mut targets = Vec::with_capacity(values.len());
    for value in values {
        let (name, generation) = value.split_once('=').ok_or_else(invalid)?;
        let n = generation.parse::<u64>().map_err(|_| invalid())?;
        if n == 0 || n.to_string() != generation {
            return Err(invalid());
        }
        targets.push(proto::PublicationMaintenanceTarget {
            publication: Some(publication(name, tenant)?),
            expected_generation: n,
        });
    }
    targets.sort_by(|a, b| {
        a.publication
            .as_ref()
            .unwrap()
            .id
            .cmp(&b.publication.as_ref().unwrap().id)
    });
    if targets
        .windows(2)
        .any(|v| v[0].publication == v[1].publication)
    {
        return Err(invalid());
    }
    Ok(targets)
}
fn selection(
    v: &Selection,
    tenant: &str,
) -> Result<proto::PublicationMaintenanceSelection, Failure> {
    id(&v.operation_id)?;
    Ok(proto::PublicationMaintenanceSelection {
        operation_id: v.operation_id.clone(),
        catalog_fence: fence(&v.catalog_fence)?,
        targets: targets(&v.target, tenant)?,
    })
}
fn wait(v: &Wait) -> Result<u64, Failure> {
    if (1..=30000).contains(&v.maximum_wait_ms) {
        Ok(v.maximum_wait_ms)
    } else {
        Err(invalid())
    }
}
fn work(v: &Work) -> Result<(), Failure> {
    if (1..=1024).contains(&v.maximum_files)
        && (1..=1_073_741_824).contains(&v.maximum_bytes_hashed)
    {
        Ok(())
    } else {
        Err(invalid())
    }
}
fn build(command: &RetentionCommand, tenant: &str) -> Result<MaintenanceOperation, Failure> {
    if tenant.is_empty()
        || tenant.len() > 512
        || tenant.chars().any(|c| c.is_whitespace() || c.is_control())
    {
        return Err(invalid());
    }
    Ok(match command {
        RetentionCommand::Snapshot(v) => {
            if v.publication.is_empty() || v.publication.len() > 32 {
                return Err(invalid());
            }
            let mut publications = v
                .publication
                .iter()
                .map(|p| publication(p, tenant))
                .collect::<Result<Vec<_>, _>>()?;
            publications.sort_by(|a, b| a.id.cmp(&b.id));
            if publications.windows(2).any(|p| p[0].id == p[1].id) {
                return Err(invalid());
            }
            MaintenanceOperation::Snapshot(proto::GetPublicationRetentionRequest {
                publications,
                maximum_wait_millis: wait(&v.wait)?,
            })
        }
        RetentionCommand::Pin(v) | RetentionCommand::Unpin(v) | RetentionCommand::Delete(v) => {
            let kind = match command {
                RetentionCommand::Pin(_) => K::Pin,
                RetentionCommand::Unpin(_) => K::Unpin,
                _ => K::Delete,
            };
            MaintenanceOperation::Maintain(proto::MaintainPublicationsRequest {
                command: Some(proto::PublicationMaintenanceCommand {
                    kind: kind as i32,
                    selection: Some(selection(&v.selection, tenant)?),
                    ..Default::default()
                }),
                maximum_wait_millis: wait(&v.wait)?,
            })
        }
        RetentionCommand::Assess(v) => {
            work(&v.work)?;
            MaintenanceOperation::Assess(proto::AssessPublicationReclamationRequest {
                deletion: Some(selection(&v.deletion, tenant)?),
                maximum_files: v.work.maximum_files,
                maximum_bytes_hashed: v.work.maximum_bytes_hashed,
                maximum_wait_millis: wait(&v.wait)?,
            })
        }
        RetentionCommand::Reclaim(v) => {
            work(&v.work)?;
            MaintenanceOperation::Maintain(proto::MaintainPublicationsRequest {
                command: Some(proto::PublicationMaintenanceCommand {
                    kind: K::Reclaim as i32,
                    selection: Some(selection(&v.deletion, tenant)?),
                    reclamation_catalog_fence: fence(&v.reclamation_fence)?,
                    maximum_files: v.work.maximum_files,
                    maximum_bytes_hashed: v.work.maximum_bytes_hashed,
                }),
                maximum_wait_millis: wait(&v.wait)?,
            })
        }
        RetentionCommand::Operation(v) => {
            id(&v.operation_id)?;
            MaintenanceOperation::Lookup(proto::GetPublicationMaintenanceOperationRequest {
                kind: match v.kind {
                    Kind::Pin => K::Pin,
                    Kind::Unpin => K::Unpin,
                    Kind::Delete => K::Delete,
                    Kind::Reclaim => K::Reclaim,
                } as i32,
                operation_id: v.operation_id.clone(),
            })
        }
    })
}
pub fn validate_arguments(command: &RetentionCommand) -> Result<(), Failure> {
    build(command, "validation-only").map(|_| ())
}
pub fn prepare(command: &RetentionCommand, config: &ResolvedConfig) -> Result<Operation, Failure> {
    Ok(Operation::PublicationMaintenance(Box::new(build(
        command,
        &config.tenant,
    )?)))
}
