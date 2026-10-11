use super::*;
use crate::namespace::NamespaceQuota;
use latent_core::{StateNamespaceId, TenantId};

const V1: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v1.schema.json");
const V2: &[u8] =
    include_bytes!("../../../../../contracts/state/application-aggregate-v2.schema.json");

fn schema(bytes: &[u8]) -> SchemaId {
    SchemaId::from_definition(bytes).unwrap()
}

fn namespace(schema: &SchemaId) -> NamespaceRecord {
    NamespaceRecord::create(
        TenantId("tenant".into()),
        StateNamespaceId("business".into()),
        schema.as_str().into(),
        NamespaceQuota::default(),
    )
    .unwrap()
}

fn reviewed(package: u8, readers: Vec<SchemaId>, writers: Vec<SchemaId>) -> ReviewedSchema {
    ReviewedSchema::accept_with(
        SchemaDeclaration {
            package_digest: [package; 32],
            readers,
            writers,
        },
        [package; 32],
        [90; 32],
        |_, _, _| Ok(()), // trusted fixture reviewer, no production authority
    )
    .unwrap()
}

#[test]
fn exact_schema_definitions_are_independent_of_package_engine_and_wit_versions() {
    let old = schema(V1);
    let new = schema(V2);
    assert_ne!(old, new);
    let one = reviewed(1, vec![old.clone()], vec![old.clone()]);
    let two = reviewed(2, vec![old.clone()], vec![old.clone()]);
    assert_ne!(one.declaration_digest(), two.declaration_digest());
    require_composition(&namespace(&old), &[one, two]).unwrap();
    assert_eq!(SchemaId::from_definition(b""), Err(NamespaceError::Invalid));
    assert_eq!(
        SchemaId::from_definition(&vec![b'a'; SCHEMA_DEFINITION_BYTES + 1]),
        Err(NamespaceError::Invalid)
    );
    assert_eq!(
        SchemaId::parse("sha256:UNKNOWN"),
        Err(NamespaceError::Invalid)
    );
}

#[test]
fn declaration_cannot_replace_exact_package_and_reviewed_conformance_evidence() {
    let old = schema(V1);
    let declaration = SchemaDeclaration {
        package_digest: [1; 32],
        readers: vec![old.clone()],
        writers: vec![old.clone()],
    };
    assert!(matches!(
        ReviewedSchema::accept_with(declaration.clone(), [2; 32], [9; 32], |_, _, _| panic!(
            "wrong package reached review"
        )),
        Err(NamespaceError::PermissionDenied)
    ));
    assert!(matches!(
        ReviewedSchema::accept_with(declaration.clone(), [1; 32], [0; 32], |_, _, _| panic!(
            "absent proof reached review"
        )),
        Err(NamespaceError::PermissionDenied)
    ));
    assert!(matches!(
        ReviewedSchema::accept_with(declaration.clone(), [1; 32], [9; 32], |_, _, _| Err(
            NamespaceError::PermissionDenied
        )),
        Err(NamespaceError::PermissionDenied)
    ));
    let mut duplicate = declaration.clone();
    duplicate.readers.push(old.clone());
    assert_eq!(duplicate.digest(), Err(NamespaceError::Invalid));
    duplicate.readers = vec![old; SCHEMAS_PER_REVISION + 1];
    assert_eq!(duplicate.digest(), Err(NamespaceError::Capacity));
    let original_digest = declaration.digest().unwrap();
    let mut changed = declaration;
    changed.writers = vec![schema(V2)];
    assert_ne!(changed.digest().unwrap(), original_digest);
}

#[test]
fn compatible_canary_requires_every_reader_to_accept_every_actual_writer() {
    let old = schema(V1);
    let new = schema(V2);
    let v1 = reviewed(1, vec![old.clone()], vec![old.clone()]);
    let compatible_v2 = reviewed(2, vec![old.clone(), new.clone()], vec![old.clone()]);
    require_composition(&namespace(&old), &[v1.clone(), compatible_v2.clone()]).unwrap();
    let v2_writer = reviewed(3, vec![old.clone(), new.clone()], vec![new.clone()]);
    assert_eq!(
        require_composition(&namespace(&old), &[v1.clone(), v2_writer.clone()]),
        Err(NamespaceError::UnsupportedFormat)
    );
    require_composition(&namespace(&new), &[compatible_v2, v2_writer]).unwrap();
    assert_eq!(
        require_composition(&namespace(&new), &[v1]),
        Err(NamespaceError::UnsupportedFormat)
    );
}

#[test]
fn retained_result_rejection_inbox_and_effect_formats_need_separate_installed_decoders() {
    let mut inventory = RetainedInventory::default();
    let mut installed = Vec::new();
    for kind in [
        RetainedKind::EffectEnvelope,
        RetainedKind::EffectPayload,
        RetainedKind::AdapterProfile,
        RetainedKind::SuccessResult,
        RetainedKind::RejectionResult,
        RetainedKind::CommandFingerprint,
        RetainedKind::CommandAttempt,
        RetainedKind::InboxIdentity,
        RetainedKind::OrderingGroup,
        RetainedKind::MigrationCheckpoint,
    ] {
        let format = RetainedFormat {
            kind,
            identity: "original-v1".into(),
        };
        inventory
            .observe(
                format.clone(),
                RetainedCount {
                    rows: 1,
                    bytes: 64,
                    unresolved: 0,
                },
            )
            .unwrap();
        installed.push(format);
    }
    inventory.require_decoders(&installed).unwrap();
    for index in 0..installed.len() {
        let mut removed = installed.clone();
        removed.remove(index);
        assert_eq!(
            inventory.require_decoders(&removed),
            Err(NamespaceError::UnsupportedFormat)
        );
    }
    let mut changed_consumer = installed.clone();
    changed_consumer
        .iter_mut()
        .find(|format| format.kind == RetainedKind::InboxIdentity)
        .unwrap()
        .identity = "new-consumer-v2".into();
    assert_eq!(
        inventory.require_decoders(&changed_consumer),
        Err(NamespaceError::UnsupportedFormat)
    );
    assert_eq!(inventory.total().rows, 10);
}

#[test]
fn unresolved_original_work_blocks_retirement_and_inventory_limits_do_not_trim() {
    let mut inventory = RetainedInventory::default();
    let effect = RetainedFormat {
        kind: RetainedKind::EffectEnvelope,
        identity: "original-publication-effect-v1".into(),
    };
    inventory
        .observe(
            effect.clone(),
            RetainedCount {
                rows: 1,
                bytes: 100,
                unresolved: 1,
            },
        )
        .unwrap();
    assert_eq!(
        inventory.require_retirement_drained(),
        Err(NamespaceError::RecoveryRequired)
    );
    let before = inventory.clone();
    assert_eq!(
        inventory.observe(
            effect,
            RetainedCount {
                rows: RETAINED_ROWS,
                bytes: 1,
                unresolved: 0
            }
        ),
        Err(NamespaceError::Capacity)
    );
    assert_eq!(inventory, before);
    for index in 1..RETAINED_FORMATS {
        inventory
            .observe(
                RetainedFormat {
                    kind: RetainedKind::SuccessResult,
                    identity: format!("result-{index}"),
                },
                RetainedCount {
                    rows: 1,
                    bytes: 1,
                    unresolved: 0,
                },
            )
            .unwrap();
    }
    let before = inventory.clone();
    assert_eq!(
        inventory.observe(
            RetainedFormat {
                kind: RetainedKind::SuccessResult,
                identity: "one-too-many".into()
            },
            RetainedCount {
                rows: 1,
                bytes: 1,
                unresolved: 0
            }
        ),
        Err(NamespaceError::Capacity)
    );
    assert_eq!(inventory, before);
    assert_eq!(inventory.entries().len(), RETAINED_FORMATS);
}
