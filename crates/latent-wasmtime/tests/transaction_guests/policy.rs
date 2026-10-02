use latent_artifacts::{DirectoryArtifactRepository, ReleaseUseEligibility};
use latent_capabilities::namespace::{
    CallerScope, RecoverySelection, INTENT_CONTRACT, STATE_CONTRACT,
};
use latent_manifest::TransactionBinding;
use latent_node::transaction_runtime::PolicyCallBinding;
use latent_policy::capability::{
    GrantRestriction, MutationRequest, PolicyStore, PolicyStoreLimits, RecordKind,
};
use serde_json::json;
use std::{
    path::Path,
    time::{Duration, Instant},
};

const OPERATIONS: [&str; 16] = [
    "acquire-command",
    "acquire-query",
    "info",
    "query-info",
    "get",
    "get-query",
    "scan",
    "scan-query",
    "put",
    "delete",
    "inspect-effect",
    "describe-page",
    "page-next",
    "commit",
    "read-result",
    "cancel-command",
];

pub fn create(
    root: &Path,
    catalog: &DirectoryArtifactRepository,
    publication: &ReleaseUseEligibility,
    declaration: &TransactionBinding,
) -> (PolicyStore, PolicyCallBinding, PolicyCallBinding) {
    let policy = PolicyStore::open(
        &root.join("policy"),
        PolicyStoreLimits::default(),
        catalog.lifecycle_authority(),
    )
    .unwrap();
    let tenant = publication.tenant().unwrap();
    let caller = CallerScope::derive(
        &super::fixture::principal(tenant),
        &RecoverySelection::OriginalCaller,
    )
    .unwrap();
    for (capability, id, binding, operations) in [
        (
            STATE_CONTRACT,
            "state",
            declaration.binding.as_str(),
            OPERATIONS.as_slice(),
        ),
        (
            INTENT_CONTRACT,
            "intents",
            "intent-policy-binding",
            ["stage"].as_slice(),
        ),
    ] {
        let document = json!({"formatVersion":1,"tenant":tenant.0.as_str(),"rules":[{
            "id":"alice","effect":"allow","principals":[{"kind":"user","subject":"alice"}],
            "services":[declaration.capsule],"publications":[publication.publication().as_str()],
            "capability":capability,"operations":operations,
            "resources":{"kind":"state","scopes":[{"namespace":declaration.namespace,"incarnation":1,"entity":null,"recoveryKind":caller.kind,"recoveryScope":caller.scope,"resultPolicy":"visibility-v1"}]},
            "ceiling":{"operations":256,"inputBytes":2_097_152,"outputBytes":2_097_152,"wallTimeMillis":30_000}
        }]});
        let provider = json!({"formatVersion":1,"tenant":tenant.0.as_str(),"capability":capability,"providerProfile":"native-guest-v1","configurationDigest":digest(),"configurationEpoch":1,"restriction":{"operations":[]}});
        for (kind, name, value) in [
            (RecordKind::Policy, id, document),
            (RecordKind::ProviderBinding, binding, provider),
        ] {
            policy
                .mutate(
                    MutationRequest {
                        tenant: tenant.0.as_str(),
                        actor: "operator",
                        kind,
                        id: name,
                        operation_id: name,
                        expected_revision: 0,
                        document: Some(&serde_json::to_vec(&value).unwrap()),
                    },
                    Instant::now() + Duration::from_secs(10),
                    |_| Ok(()),
                )
                .unwrap();
        }
    }
    (
        policy,
        call_binding("state", &declaration.binding, STATE_CONTRACT, &OPERATIONS),
        call_binding(
            "intents",
            "intent-policy-binding",
            INTENT_CONTRACT,
            &["stage"],
        ),
    )
}

fn digest() -> String {
    format!("sha256:{}", "2".repeat(64))
}
fn call_binding(
    policy: &str,
    binding: &str,
    capability: &str,
    operations: &[&str],
) -> PolicyCallBinding {
    PolicyCallBinding {
        policies: vec![policy.into()],
        binding: binding.into(),
        profile: "native-guest-v1".into(),
        configuration_digest: digest(),
        configuration_epoch: 1,
        operations: operations.iter().map(|value| (*value).into()).collect(),
        deployment: GrantRestriction::parse(br#"{"operations":[]}"#, capability).unwrap(),
        provider_configuration: GrantRestriction::parse(br#"{"operations":[]}"#, capability)
            .unwrap(),
    }
}
