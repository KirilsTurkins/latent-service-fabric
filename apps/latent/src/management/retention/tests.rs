use super::*;
use crate::{
    args::{Cli, Command, ReleaseCommand},
    management::phase2::projection::{self, Project},
};
use clap::Parser;
fn id() -> String {
    format!("publication:sha256:{}", "a".repeat(64))
}
fn cli(extra: &[&str]) -> Result<Cli, clap::Error> {
    let mut a = vec!["latent", "release", "retention"];
    a.extend_from_slice(extra);
    Cli::try_parse_from(a)
}
#[test]
fn publication_operator_requires_explicit_identity_fences_and_finite_wait() {
    assert!(cli(&["delete"]).is_err());
    let fence = "a".repeat(64);
    let target = format!("{}=2", id());
    let args = [
        "delete",
        "--operation-id",
        "one",
        "--catalog-fence",
        &fence,
        "--target",
        &target,
    ];
    let c = cli(&args).unwrap();
    c.validate().unwrap();
    let Command::Release(ReleaseCommand::Retention(command)) = c.command else {
        panic!("retention")
    };
    validate_arguments(&command).unwrap();
    let mut invalid = args.to_vec();
    invalid.extend(["--maximum-wait-ms", "30001"]);
    assert!(cli(&invalid).is_err());
    let upper = "A".repeat(64);
    let c = cli(&[
        "delete",
        "--operation-id",
        "one",
        "--catalog-fence",
        &upper,
        "--target",
        &target,
    ])
    .unwrap();
    assert!(c.validate().is_err());
}
#[test]
fn publication_operator_refuses_duplicates_zero_generation_and_noncanonical_numbers() {
    let fence = "a".repeat(64);
    let name = id();
    for generation in ["0", "02", "+2", "18446744073709551616"] {
        let target = format!("{name}={generation}");
        let c = cli(&[
            "pin",
            "--operation-id",
            "one",
            "--catalog-fence",
            &fence,
            "--target",
            &target,
        ])
        .unwrap();
        assert!(c.validate().is_err());
    }
    let c = cli(&["snapshot", "--publication", &name, "--publication", &name]).unwrap();
    assert!(c.validate().is_err());
}
fn selection() -> proto::PublicationMaintenanceSelection {
    proto::PublicationMaintenanceSelection {
        operation_id: "one".into(),
        catalog_fence: vec![1; 32],
        targets: vec![proto::PublicationMaintenanceTarget {
            publication: Some(proto::PublicationRef {
                id: id(),
                tenant: "tenant".into(),
            }),
            expected_generation: u64::MAX,
        }],
    }
}
fn receipt() -> proto::PublicationMaintenanceOperationReceipt {
    proto::PublicationMaintenanceOperationReceipt {
        tenant: "tenant".into(),
        actor: Some(proto::ReleaseActor {
            subject: "operator".into(),
            kind: proto::ReleaseActorKind::Administrator as i32,
        }),
        command: Some(proto::PublicationMaintenanceCommand {
            kind: proto::PublicationMaintenanceKind::Delete as i32,
            selection: Some(selection()),
            ..Default::default()
        }),
        revision: u64::MAX,
        reference_revision: u64::MAX,
        reclaimed: None,
    }
}
#[test]
fn publication_operator_projects_lossless_generations_and_never_claims_delete_refunds() {
    let r = receipt();
    projection::checked(&r, 65536).unwrap();
    let value = r.project();
    assert_eq!(value["revision"], u64::MAX.to_string());
    assert_eq!(value["stage"], "visibility-removed");
    assert!(value["reclaimed"].is_null());
    assert_eq!(
        value["command"]["selection"]["targets"][0]["expectedGeneration"],
        u64::MAX.to_string()
    );
}
#[test]
fn publication_operator_rejects_wrong_scope_fabricated_refunds_and_receipt_on_unknown() {
    let mut r = receipt();
    r.tenant = "foreign".into();
    assert!(projection::checked(&r, 65536).is_err());
    let mut r = receipt();
    r.reclaimed = Some(proto::PublicationReclamationAccounting::default());
    assert!(projection::checked(&r, 65536).is_err());
    let v = proto::GetPublicationMaintenanceOperationResponse {
        tenant: "tenant".into(),
        disposition: proto::ReleaseOperationLookupDisposition::Unknown as i32,
        receipt: Some(receipt()),
    };
    assert!(projection::checked(&v, 65536).is_err());
    let v = proto::MaintainPublicationsResponse {
        receipt: Some(receipt()),
        replay: false,
        audit_ack: Some(proto::AuditAck {
            status: proto::AuditAckStatus::Disabled as i32,
            attempt_sequence: None,
        }),
    };
    assert!(projection::checked(&v, 65536).is_err());
}
#[test]
fn publication_operator_recovery_keeps_both_fences_without_automatic_replay() {
    let operation = MaintenanceOperation::Maintain(proto::MaintainPublicationsRequest {
        command: Some(proto::PublicationMaintenanceCommand {
            kind: proto::PublicationMaintenanceKind::Reclaim as i32,
            selection: Some(selection()),
            reclamation_catalog_fence: vec![2; 32],
            maximum_files: 100,
            maximum_bytes_hashed: 67108864,
        }),
        maximum_wait_millis: 1000,
    });
    let recovery = operation.recovery().unwrap();
    assert_eq!(recovery["originalCatalogFence"], "01".repeat(32));
    assert_eq!(recovery["reclamationCatalogFence"], "02".repeat(32));
    assert_eq!(recovery["automaticReplay"], false);
    assert!(recovery.get("targets").is_none());
}
