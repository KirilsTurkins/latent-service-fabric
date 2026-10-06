//! Actual process loss at the existing writer fence or after confirmed flush.
//! The parent reaps the original owner before reopening the selected engine.
//! These schedules do not claim an injected within-flush or power-loss failure.
use super::*;
use latent_test_process::process::{OwnedProcess, ProcessLimits};
use std::{
    io::Write,
    path::Path,
    process::Command,
    time::{Duration, Instant},
};

const READY: &[u8] = b"COMPLETE_ENVELOPE_PROCESS_BOUNDARY";
const CHILD_CASE: &str = "atomic::tests::process::owned_envelope_child";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Scenario {
    Admission,
    Success,
    StateOnly,
    IntentOnly,
    Rejection,
    Abort,
    Retry,
}

impl Scenario {
    const ALL: [Self; 7] = [
        Self::Admission,
        Self::Success,
        Self::StateOnly,
        Self::IntentOnly,
        Self::Rejection,
        Self::Abort,
        Self::Retry,
    ];

    fn name(self) -> &'static str {
        match self {
            Self::Admission => "admission",
            Self::Success => "success",
            Self::StateOnly => "state-only",
            Self::IntentOnly => "intent-only",
            Self::Rejection => "rejection",
            Self::Abort => "abort",
            Self::Retry => "retry",
        }
    }

    fn parse(name: &str) -> Self {
        Self::ALL
            .into_iter()
            .find(|scenario| scenario.name() == name)
            .expect("closed process schedule")
    }

    fn request(self) -> AdmissionInput {
        let mut request = input("process-boundary");
        if !matches!(self, Self::Admission | Self::Retry) {
            request.inbox = Some(InboxIdentity {
                provider: "input".into(),
                binding: "source".into(),
                message: "original-process-message".into(),
                payload_digest: Identity::derive(b"input", &[b"original-process-message"]),
            });
        }
        request
    }
}

fn boundary() -> ! {
    println!("{}", std::str::from_utf8(READY).unwrap());
    std::io::stdout().flush().unwrap();
    loop {
        // No elapsed time advances the transaction. Only the parent terminates
        // this positively observed original process owner.
        std::thread::park();
    }
}

fn retired(owner: AdmittedCommand) -> super::super::RetiredAttempt {
    let witness = owner.retirement();
    drop(owner);
    witness.proven_noncommit().unwrap()
}

fn envelope(
    scenario: Scenario,
    view: &latent_state::embedded::ReadView,
    owner: AdmittedCommand,
    effects: &EffectAuthorityOwner,
) -> CompleteEnvelope {
    match scenario {
        Scenario::Success | Scenario::StateOnly | Scenario::IntentOnly => {
            let state = (scenario != Scenario::IntentOnly).then(|| stage(view));
            let intents = if scenario == Scenario::StateOnly {
                vec![]
            } else {
                vec![intent()]
            };
            CompleteEnvelope::success(
                view,
                owner,
                state,
                intents,
                value(b"original process result"),
                effects,
                time(101),
            )
            .unwrap()
        }
        Scenario::Rejection => {
            // Real staged business bytes are discarded before terminal metadata;
            // rejection cannot make their state or external intent dispatchable.
            drop(stage(view));
            drop(intent());
            CompleteEnvelope::rejection(
                view,
                owner,
                "inventory-unavailable".into(),
                value(b"original process rejection"),
                time(101),
            )
            .unwrap()
        }
        Scenario::Abort => {
            CompleteEnvelope::technical_abort(view, retired(owner), "conflict".into(), time(101))
                .unwrap()
        }
        Scenario::Admission | Scenario::Retry => panic!("claim-only schedules have no envelope"),
    }
}

fn publish_envelope(
    envelope: CompleteEnvelope,
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
    before_flush: bool,
) -> CommandRecord {
    match envelope.publish(store, |authorities| {
        let guard = effects.commit_fence(
            authorities,
            EffectTime {
                unix_millis: 101,
                continuity_proven: true,
            },
        )?;
        permission(CommandAccess::FinalDisposition, None)?;
        if before_flush {
            boundary();
        }
        drop(guard);
        Ok(())
    }) {
        PreparedDisposition::Confirmed { command, .. } => command,
        _ => panic!("the child must positively observe its original disposition"),
    }
}

fn publish_admission(
    prepared: PreparedAdmission,
    store: &EmbeddedStore,
    before_flush: bool,
) -> AdmittedCommand {
    prepared
        .publish(store, || {
            permission(CommandAccess::FinalClaim, None)?;
            if before_flush {
                boundary();
            }
            Ok(())
        })
        .unwrap()
}

fn fresh_admission(store: &EmbeddedStore, request: AdmissionInput) -> PreparedAdmission {
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) =
        PreparedAdmission::prepare(&view, request, time(100), permission).unwrap()
    else {
        panic!("one original fresh command")
    };
    prepared
}

fn retry_admission(
    store: &EmbeddedStore,
    effects: &EffectAuthorityOwner,
    request: &AdmissionInput,
) -> PreparedAdmission {
    let owner = claim(store, request.clone());
    let view = store.snapshot().unwrap();
    let abort = envelope(Scenario::Abort, &view, owner, effects);
    let aborted = publish_envelope(abort, store, effects, false);
    drop(view);
    let view = store.snapshot().unwrap();
    let AdmissionDecision::New(prepared) = PreparedAdmission::retry(
        &view,
        request,
        &RetryRequest {
            request_id: "original-retry-request".into(),
            expected_abort: aborted.abort_proof().unwrap(),
        },
        time(102),
        permission,
    )
    .unwrap() else {
        panic!("explicit retry requires one linked new attempt")
    };
    prepared
}

#[test]
fn owned_envelope_child() {
    let Ok(root) = std::env::var("LSF_ENVELOPE_CHILD_ROOT") else {
        // Only the owned parent campaign supplies the child protocol. This
        // fixture entry point is not itself durability qualification.
        return;
    };
    let scenario = Scenario::parse(&std::env::var("LSF_ENVELOPE_CHILD_SCENARIO").unwrap());
    let before_flush = std::env::var("LSF_ENVELOPE_CHILD_BEFORE").unwrap() == "true";
    let store = open(&Path::new(&root).join("state.redb"));
    let effects = seed(&store);
    let request = scenario.request();
    if matches!(scenario, Scenario::Admission | Scenario::Retry) {
        let prepared = if scenario == Scenario::Retry {
            retry_admission(&store, &effects, &request)
        } else {
            fresh_admission(&store, request)
        };
        let owner = publish_admission(prepared, &store, before_flush);
        assert_eq!(owner.record().outcome(), Outcome::Pending);
        boundary();
    }
    let owner = claim(&store, request);
    let view = store.snapshot().unwrap();
    let complete = envelope(scenario, &view, owner, &effects);
    let command = publish_envelope(complete, &store, &effects, before_flush);
    assert!(matches!(
        command.outcome(),
        Outcome::Committed | Outcome::Rejected | Outcome::Aborted
    ));
    // No result is sent back to the caller; termination loses that reply after
    // positive Immediate-durability completion on the same selected engine.
    boundary();
}

fn no_business_rows(view: &latent_state::embedded::ReadView) {
    for family in [Family::State, Family::Outbox, Family::PayloadReference] {
        assert!(view
            .scan_after(family, b"", None, 128, 1024 * 1024)
            .unwrap()
            .rows
            .is_empty());
    }
}

fn assert_namespace_generation(
    view: &latent_state::embedded::ReadView,
    scenario: Scenario,
    before_flush: bool,
) {
    let namespace = NamespaceRecord::decode(&view.get(&namespace_key()).unwrap().unwrap()).unwrap();
    let generation = match scenario {
        Scenario::Admission => {
            if before_flush {
                1
            } else {
                2
            }
        }
        Scenario::Retry => {
            if before_flush {
                3
            } else {
                4
            }
        }
        _ => {
            if before_flush {
                2
            } else {
                3
            }
        }
    };
    assert_eq!(namespace.version.incarnation, 1);
    assert_eq!(namespace.version.generation, generation);
    let retained_results = if scenario == Scenario::Admission && before_flush {
        0
    } else if scenario == Scenario::Retry && !before_flush {
        2
    } else {
        1
    };
    assert_eq!(namespace.pins.retained_results, retained_results);
    let effect_committed =
        !before_flush && matches!(scenario, Scenario::Success | Scenario::IntentOnly);
    assert_eq!(
        namespace.pins.unresolved_effects,
        u64::from(effect_committed)
    );
}

fn assert_committed_business(
    scenario: Scenario,
    view: &latent_state::embedded::ReadView,
    command: &CommandRecord,
) {
    let states = view
        .scan_after(Family::State, b"", None, 128, 1024 * 1024)
        .unwrap()
        .rows;
    assert_eq!(states.len(), usize::from(scenario != Scenario::IntentOnly));
    let expected_effects = usize::from(scenario != Scenario::StateOnly);
    assert_eq!(command.effect_ids().len(), expected_effects);
    let outbox = view
        .scan_after(Family::Outbox, b"", None, 128, 1024 * 1024)
        .unwrap()
        .rows;
    assert_eq!(outbox.len(), expected_effects);
    for effect in command.effect_ids() {
        let bytes = view
            .get(&latent_effects::dispatch_store::effect_row_key(&effect.hex()).unwrap())
            .unwrap()
            .unwrap();
        let record = latent_effects::dispatch::EffectRecord::decode(&bytes).unwrap();
        let authority = record.authority().unwrap();
        assert_eq!(authority.link().command, command.id.hex());
        assert_eq!(authority.link().commit, command.disposition_id().hex());
        assert_eq!(authority.link().attempt, command.attempt());
        assert!(view
            .get(&latent_effects::dispatch_store::effect_payload_key(&effect.hex()).unwrap())
            .unwrap()
            .is_some());
    }
}

fn assert_recovery(root: &Path, scenario: Scenario, before_flush: bool) {
    let store = open(&root.join("state.redb"));
    let view = store.snapshot().unwrap();
    let request = scenario.request();
    assert_namespace_generation(&view, scenario, before_flush);
    if scenario == Scenario::Admission && before_flush {
        assert!(matches!(
            inspect(&view, &request.key, time(103), permission),
            Err(AtomicError::NotFound)
        ));
        no_business_rows(&view);
        return;
    }
    let (command, result) = inspect(&view, &request.key, time(103), permission).unwrap();
    assert_eq!(command.key, request.key);
    assert_eq!(command.source, request.source);
    assert_eq!(command.result_read_policy, request.result_read_policy);
    if scenario == Scenario::Retry {
        assert_eq!(command.attempt(), if before_flush { 1 } else { 2 });
        assert_eq!(
            command.outcome(),
            if before_flush {
                Outcome::Aborted
            } else {
                Outcome::Pending
            }
        );
        let original = CommandRecord::decode(
            &view
                .get(&record::attempt_row_key(command.id, 1))
                .unwrap()
                .unwrap(),
        )
        .unwrap();
        assert_eq!(original.outcome(), Outcome::Aborted);
        assert!(original.abort_proof().is_some());
        no_business_rows(&view);
    } else if scenario == Scenario::Admission || before_flush {
        assert_eq!(command.outcome(), Outcome::Pending);
        assert!(result.is_none());
        no_business_rows(&view);
    } else {
        let result = result.unwrap();
        match scenario {
            Scenario::Success | Scenario::StateOnly | Scenario::IntentOnly => {
                assert_eq!(command.outcome(), Outcome::Committed);
                assert_eq!(result.value(), Some(&value(b"original process result")));
                assert_committed_business(scenario, &view, &command);
            }
            Scenario::Rejection => {
                assert_eq!(command.outcome(), Outcome::Rejected);
                assert_eq!(result.code(), Some("inventory-unavailable"));
                assert_eq!(result.value(), Some(&value(b"original process rejection")));
                no_business_rows(&view);
            }
            Scenario::Abort => {
                assert_eq!(command.outcome(), Outcome::Aborted);
                assert!(command.abort_proof().is_some());
                no_business_rows(&view);
            }
            Scenario::Admission | Scenario::Retry => unreachable!(),
        }
    }
    if let Some(inbox) = request.inbox {
        let present = view
            .get(&inbox.row_key(&request.key).unwrap())
            .unwrap()
            .is_some();
        assert_eq!(present, !before_flush && scenario != Scenario::Abort);
    }
}

#[tokio::test]
async fn original_process_loss_at_native_acceptance_and_after_flush_keeps_complete_envelopes() {
    for scenario in Scenario::ALL {
        for before_flush in [true, false] {
            let root = tempfile::tempdir().unwrap();
            let mut command = Command::new(std::env::current_exe().unwrap());
            command
                .args(["--exact", CHILD_CASE, "--nocapture"])
                .env("LSF_ENVELOPE_CHILD_ROOT", root.path())
                .env("LSF_ENVELOPE_CHILD_SCENARIO", scenario.name())
                .env("LSF_ENVELOPE_CHILD_BEFORE", before_flush.to_string());
            let child = OwnedProcess::spawn(command, ProcessLimits::default()).unwrap();
            let cutoff = Instant::now() + Duration::from_secs(4);
            let mut observed = false;
            while Instant::now() < cutoff {
                if let Ok(stdout) = child.stdout_snapshot() {
                    if stdout.windows(READY.len()).any(|bytes| bytes == READY) {
                        observed = true;
                        break;
                    }
                } else {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(5)).await;
            }
            let retired = child.terminate().await.unwrap();
            assert!(observed, "original child did not reach {scenario:?}/{before_flush} boundary; original process has been reaped");
            assert!(
                !retired.status.success(),
                "original process must be terminated and reaped"
            );
            assert_recovery(root.path(), scenario, before_flush);
        }
    }
}
