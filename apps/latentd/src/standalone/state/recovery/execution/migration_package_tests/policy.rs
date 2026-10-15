use super::fixture::*;
use latent_capabilities::namespace::{CallerScope, RecoverySelection, STATE_CONTRACT};
use latent_policy::capability::{MutationRequest, RecordKind};

pub(super) fn install(
    fixture: &PolicyStore,
    principal: &InvocationPrincipal,
    publication: &str,
    profile: &str,
    digest: &str,
    cutoff: Instant,
) {
    let caller = CallerScope::derive(principal, &RecoverySelection::OriginalCaller).unwrap();
    let policy = json!({"formatVersion":1,"tenant":"examples","rules":[{
        "id":"native","effect":"allow","principals":[{"kind":"administrator","subject":"operator"}],
        "services":["examples/transaction-java-aggregate"],"publications":[publication],
        "capability":STATE_CONTRACT,"operations":["namespace-snapshot","namespace-schema-migrate",
            "namespace-inspect-restore","namespace-restore"],
        "resources":{"kind":"state","scopes":[{"namespace":"transactional-aggregate","incarnation":1,
            "entity":null,"recoveryKind":"original-caller","recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},
        "ceiling":{"operations":1,"inputBytes":67108864,"outputBytes":67108864,"wallTimeMillis":30000}}]});
    let binding = json!({"formatVersion":1,"tenant":"examples","capability":STATE_CONTRACT,
        "providerProfile":profile,"configurationDigest":digest,"configurationEpoch":1,
        "restriction":{"operations":[]}});
    for (id, kind, document) in [
        ("native", RecordKind::Policy, policy),
        (
            "transaction-java-aggregate",
            RecordKind::ProviderBinding,
            binding,
        ),
    ] {
        let bytes = serde_json::to_vec(&document).unwrap();
        fixture
            .mutate(
                MutationRequest {
                    tenant: "examples",
                    actor: "operator",
                    id,
                    kind,
                    operation_id: id,
                    expected_revision: 0,
                    document: Some(&bytes),
                },
                cutoff,
                |_| Ok(()),
            )
            .unwrap();
    }
}

pub(super) fn revoke(fixture: &Fixture) {
    let revision = fixture
        .policy
        .outcome("examples", "native", fixture.cutoff())
        .unwrap()
        .value()
        .as_ref()
        .unwrap()
        .revision;
    fixture
        .policy
        .mutate(
            MutationRequest {
                tenant: "examples",
                actor: "operator",
                id: "native",
                kind: RecordKind::Policy,
                operation_id: "withdraw-native",
                expected_revision: revision,
                document: None,
            },
            fixture.cutoff(),
            |_| Ok(()),
        )
        .unwrap();
}
