use super::{
    control::{self, Command},
    output,
    plan::{self, Group, Plan, Target, PREFIX},
};
use serde_json::json;

fn plan(profile: &str, pair: u32) -> Plan {
    Plan {
        schema: format!("{PREFIX}plan.v1"),
        run_id: "session-test".into(),
        profile: profile.into(),
        pair,
        token_file: "token".into(),
    }
}

fn targets(group: Group) -> Vec<Target> {
    (0..group.density)
        .map(|index| Target {
            service: plan::service(index),
            endpoint: format!("http://target-{index}:8080"),
            owner_ref: if group.arm == "lsf" {
                "lsf-owner".into()
            } else {
                format!("native-{index}")
            },
            // Independent native namespaces may truthfully have the same PID.
            app_process_id: 7,
        })
        .collect()
}

#[test]
fn exact_small_populations_and_rotated_position_orders() {
    for pair in 0..7 {
        let plan = plan("full", pair);
        plan.validate().unwrap();
        let groups = plan.groups();
        assert_eq!(groups.len(), 6);
        assert_eq!(groups[0].density, [1, 8, 32][pair as usize % 3]);
        for position in 0..3 {
            assert_eq!(
                groups[2 * position].arm,
                if (pair as usize + position) % 2 == 0 {
                    "lsf"
                } else {
                    "native"
                }
            );
            assert_eq!(
                groups[2 * position].density,
                groups[2 * position + 1].density
            );
        }
        assert_eq!(
            groups
                .iter()
                .flat_map(|group| plan.phases(*group))
                .map(|phase| phase.offers)
                .sum::<u32>(),
            1418
        );
        assert_eq!(
            groups
                .iter()
                .map(|group| plan.phases(*group).len())
                .sum::<usize>(),
            30
        );
        assert_eq!(control::sequence(&plan).len(), 61);
    }
    let smoke = plan("smoke", 0);
    assert_eq!(
        smoke
            .groups()
            .iter()
            .flat_map(|group| smoke.phases(*group))
            .map(|phase| phase.offers)
            .sum::<u32>(),
        300
    );
    assert!(plan("smoke", 1).validate().is_err());
    assert!(plan("full", 7).validate().is_err());
}

#[test]
fn existing_semantic_plans_bind_actual_each_target_pid_and_grants() {
    let plan = plan("full", 3);
    for group in plan.groups() {
        let targets = targets(group);
        plan::targets(group, &targets).unwrap();
        for phase in plan.phases(group) {
            for target in &targets {
                let legacy = plan.invocation(group, phase, target);
                let prepared = legacy.prepare().unwrap();
                assert_eq!(legacy.server_process_id, target.app_process_id);
                assert_eq!(legacy.services, vec![target.service.clone()]);
                assert_eq!(legacy.log_bytes, 16384);
                assert_eq!(legacy.budget_millis, 1000);
                assert_eq!(legacy.response_timeout_millis, 5000);
                assert!(!prepared.expected.is_empty());
            }
        }
    }
}

#[test]
fn targets_reject_crossed_owners_services_zero_pid_and_aliases() {
    let native = Group {
        index: 0,
        arm: "native",
        density: 32,
    };
    let original = targets(native);
    assert!(plan::targets(native, &original).is_ok());
    let mut changed = original.clone();
    changed[7].owner_ref = changed[0].owner_ref.clone();
    assert!(plan::targets(native, &changed).is_err());
    let mut changed = original.clone();
    changed[7].endpoint = changed[0].endpoint.clone();
    assert!(plan::targets(native, &changed).is_err());
    let mut changed = original.clone();
    changed[7].app_process_id = 0;
    assert!(plan::targets(native, &changed).is_err());
    let mut changed = original.clone();
    changed[7].service = plan::service(32);
    assert!(plan::targets(native, &changed).is_err());
    let lsf = Group {
        arm: "lsf",
        ..native
    };
    let mut changed = targets(lsf);
    changed[3].app_process_id = 99;
    assert!(plan::targets(lsf, &changed).is_err());
}

fn command(expected: &control::Expected, ordinal: usize) -> serde_json::Value {
    json!({"schema":format!("{PREFIX}command.v1"),"ordinal":ordinal,"plan_sha256":"sha256:bound",
        "command":expected.command,"group":expected.group,"phase":expected.phase,"barrier":expected.barrier,
        "targets":if expected.command=="begin-group"{Some(Vec::<Target>::new())}else{None}})
}

#[test]
fn every_control_step_requires_exact_nullable_shape_and_association() {
    let plan = plan("smoke", 0);
    let sequence = control::sequence(&plan);
    for (ordinal, expected) in sequence.iter().enumerate() {
        let raw = command(expected, ordinal);
        let parsed: Command = serde_json::from_value(raw.clone()).unwrap();
        parsed
            .validate(expected, ordinal as u32, "sha256:bound")
            .unwrap();
        assert!(parsed
            .validate(expected, ordinal as u32 + 1, "sha256:bound")
            .is_err());
        assert!(parsed
            .validate(expected, ordinal as u32, "sha256:other")
            .is_err());
        for key in ["group", "phase", "barrier", "targets"] {
            let mut changed = raw.clone();
            changed.as_object_mut().unwrap().remove(key);
            assert!(serde_json::from_value::<Command>(changed).is_err());
        }
        let mut extra = raw;
        extra["workload_override"] = json!(1);
        assert!(serde_json::from_value::<Command>(extra).is_err());
    }
}

#[test]
fn three_explicit_barriers_keep_final_inventory_before_channel_drop() {
    let sequence = control::sequence(&plan("full", 0));
    for group in 0..6 {
        let rows: Vec<_> = sequence
            .iter()
            .filter(|row| row.group == Some(group))
            .collect();
        assert_eq!(rows[0].command, "begin-group");
        assert_eq!(rows[1].barrier, Some("ready"));
        assert_eq!(rows[2].phase, Some(0));
        assert_eq!(rows[3].barrier, Some("served"));
        assert_eq!(rows[rows.len() - 2].barrier, Some("final"));
        assert_eq!(rows.last().unwrap().command, "finish-group");
    }
    assert_eq!(
        sequence
            .iter()
            .filter(|row| row.command == "inventory")
            .count(),
        18
    );
}

#[test]
fn output_and_selector_limits_do_not_silently_expand() {
    assert!(output::encode(&"abc", 6).is_ok());
    assert!(output::encode(&"abcd", 6).is_err());
    assert!(output::encode(&vec![0_u8; 100], 16).is_err());
    let mut value = plan("full", 0);
    value.run_id = "invalid_id".into();
    assert!(value.validate().is_err());
    value.run_id = "x".repeat(25);
    assert!(value.validate().is_err());
    let mut raw = serde_json::to_value(plan("full", 0)).unwrap();
    raw["maximum_output_bytes"] = json!(64 * 1024 * 1024);
    assert!(serde_json::from_value::<Plan>(raw).is_err());
}
