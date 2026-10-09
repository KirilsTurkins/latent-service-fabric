use super::*;
use latent_core::BudgetProfile;

fn configured() -> (TempDir, NodeConfig) {
    let (directory, mut config) = config();
    config.state = Some(serde_json::from_value(super::super::state::tests::input()).unwrap());
    config.budget_profile = serde_json::from_str(r#"{"mode":"phase4","maximumStateReadBytes":4096,"maximumStateWriteBytes":2048,"maximumEffectCount":2,"maximumOutboundRequests":3}"#).unwrap();
    config.supply_chain = super::super::SupplyChainConfig::Enforced {
        policy_file: directory.path().join("policy.json"),
        clock_lease_seconds: 5,
    };
    config.audit = Some(serde_json::from_str(r#"{"mode":"durable"}"#).unwrap());
    config.capability_policies = Some(serde_json::from_str(r#"{"formatVersion":1}"#).unwrap());
    (directory, config)
}

#[test]
fn phase4_requires_the_state_owner_and_all_current_authority_owners_together() {
    let (_directory, mut config) = configured();
    assert!(super::super::state::derive_optional(&config)
        .unwrap()
        .is_some());
    config.budget_profile = super::super::BudgetConfig::Phase1 {};
    assert!(super::super::state::derive_optional(&config).is_err());
    config.state = None;
    assert!(super::super::state::derive_optional(&config)
        .unwrap()
        .is_none());
    config.budget_profile = serde_json::from_str(r#"{"mode":"phase4","maximumStateReadBytes":0,"maximumStateWriteBytes":0,"maximumEffectCount":0}"#).unwrap();
    assert!(super::super::state::derive_optional(&config).is_err());
    for missing in ["supply", "audit", "policy"] {
        let (_directory, mut config) = configured();
        match missing {
            "supply" => config.supply_chain = super::super::SupplyChainConfig::TrustedLocal,
            "audit" => config.audit = None,
            "policy" => config.capability_policies = None,
            _ => unreachable!(),
        }
        assert!(
            super::super::state::derive_optional(&config).is_err(),
            "{missing}"
        );
    }
}

#[test]
fn explicit_phase4_counters_reach_wire_accounting_without_inventing_immediate_grants() {
    let (_directory, config) = configured();
    let mut budget = super::super::policy::budget(&config, 64 * super::super::MIB as u64);
    config.budget_profile.apply(&mut budget);
    assert_eq!(config.budget_profile.profile(), BudgetProfile::Phase4);
    assert_eq!(
        (
            budget.state_read_bytes,
            budget.state_write_bytes,
            budget.effect_count
        ),
        (4096, 2048, 2)
    );
    // Stateless installations may coexist, while the actual transaction
    // manifest/admission still requires its immediate counters to be zero.
    assert_eq!(budget.outbound_requests, 3);
    let capacity = super::super::validation::validate(&config).unwrap();
    let wire = super::super::runtime::invocation(&config, &capacity).unwrap();
    assert_eq!(
        (
            wire.max_state_read_bytes,
            wire.max_state_write_bytes,
            wire.max_effect_count
        ),
        (4096, 2048, 2)
    );
    assert_eq!(wire.budget_profile, BudgetProfile::Phase4);
    let runtime = super::super::runtime::wasmtime(&config, &capacity).unwrap();
    assert!(runtime.transactional_state);
    assert!(latent_manifest::ManifestValidationProfile::phase4(
        config.budget_profile.profile(),
        latent_core::PHASE4_HOST_ABI_V1,
        &latent_manifest::phase4_host_abi_digest()
    )
    .unwrap()
    .transactional());
}

#[test]
fn omitted_present_null_and_unsupported_phase4_counters_cannot_enable_state() {
    for input in [
        r#"{"mode":"phase4"}"#,
        r#"{"mode":"phase4","maximumStateReadBytes":1,"maximumStateWriteBytes":1}"#,
        r#"{"mode":"phase4","maximumStateReadBytes":1,"maximumStateWriteBytes":1,"maximumEffectCount":null}"#,
        r#"{"mode":"phase4","maximumStateReadBytes":1,"maximumStateWriteBytes":1,"maximumEffects":1}"#,
    ] {
        assert!(serde_json::from_str::<super::super::BudgetConfig>(input).is_err());
    }
    for (name, value) in [
        ("maximumStateReadBytes", 1_073_741_825),
        ("maximumStateWriteBytes", u64::MAX),
        ("maximumEffectCount", 129),
    ] {
        let mut wire = serde_json::json!({"mode":"phase4","maximumStateReadBytes":4096,"maximumStateWriteBytes":2048,"maximumEffectCount":2});
        wire[name] = value.into();
        let budget: super::super::BudgetConfig = serde_json::from_value(wire).unwrap();
        assert!(budget.limits().is_err(), "{name}");
    }
    let mut wire: serde_json::Value = serde_json::from_str(&document()).unwrap();
    wire["state"] = serde_json::Value::Null;
    assert!(input::decode(&serde_json::to_vec(&wire).unwrap()).is_err());
}

#[test]
fn checked_settings_refuse_mixed_state_budget_runtime_and_current_authority_owners() {
    for mismatch in ["budget", "runtime", "state", "authority"] {
        let (_directory, config) = config();
        let mut settings = config.derive().unwrap();
        match mismatch {
            "budget" => settings.budget_profile = BudgetProfile::Phase4,
            "runtime" => settings.wasmtime.transactional_state = true,
            "state" | "authority" => {
                settings.state = Some(
                    super::super::state::derive(
                        &serde_json::from_value(super::super::state::tests::input()).unwrap(),
                        &settings.data_directory,
                    )
                    .unwrap(),
                );
                if mismatch == "authority" {
                    settings.budget_profile = BudgetProfile::Phase4;
                    settings.wasmtime.transactional_state = true;
                    settings.manifest_profile = latent_manifest::ManifestValidationProfile::phase4(
                        BudgetProfile::Phase4,
                        latent_core::PHASE4_HOST_ABI_V1,
                        &latent_manifest::phase4_host_abi_digest(),
                    )
                    .unwrap();
                }
            }
            _ => unreachable!(),
        }
        assert!(settings.check_config().is_err(), "{mismatch}");
        assert!(settings.persist_execution_profile().is_err(), "{mismatch}");
    }
}
