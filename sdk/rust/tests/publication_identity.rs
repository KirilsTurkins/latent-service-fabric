use latent_core::{
    ActivationId, BudgetConsumption, ReleaseDigest, RevisionId, RouteGeneration, TenantId,
};
use latent_sdk::{InvocationReceipt, PublicationIdentity, PublicationRef};

#[test]
fn scoped_coexistence_publication_presence_and_full_width_receipts() {
    let component = ReleaseDigest(format!("sha256:{}", "a".repeat(64)));
    let publications: Vec<_> = (0..4)
        .map(|index| PublicationIdentity {
            publication: PublicationRef {
                id: format!("publication:sha256:{index:064x}").parse().unwrap(),
                tenant: TenantId(if index < 2 { "tenant-a" } else { "tenant-b" }.into()),
            },
            component_digest: component.clone(),
            package_digest: format!("sha256:{:064x}", index % 2).parse().unwrap(),
        })
        .collect();
    assert_eq!(
        publications[0].component_digest,
        publications[3].component_digest
    );
    assert_eq!(
        publications[0].package_digest,
        publications[2].package_digest
    );
    assert_ne!(publications[0].publication, publications[2].publication);
    assert_ne!(
        publications[0].package_digest,
        publications[1].package_digest
    );
    assert!("".parse::<latent_core::PublicationId>().is_err());
    let mut receipt = InvocationReceipt {
        activation_id: ActivationId("known".into()),
        revision_id: RevisionId("revision".into()),
        release_digest: component.clone(),
        publication_id: None,
        route_generation: RouteGeneration(u64::MAX),
        consumption: BudgetConsumption {
            cpu_fuel: u64::MAX,
            ..BudgetConsumption::default()
        },
    };
    assert!(receipt.publication_id.is_none());
    receipt.publication_id = Some(publications[1].publication.id.clone());
    assert_eq!(receipt.release_digest, component);
    assert_eq!(receipt.consumption.cpu_fuel, u64::MAX);
    assert_eq!(receipt.route_generation.0, u64::MAX);
}
