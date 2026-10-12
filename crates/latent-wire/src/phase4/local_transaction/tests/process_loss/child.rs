use super::*;
use std::{io::Write, os::unix::fs::OpenOptionsExt};

pub(super) async fn run(kind: &str) {
    assert!(matches!(kind, "pending" | "committed" | "rejected"));
    let f = Fixture::new(kind == "pending").await;
    let response = if kind == "pending" {
        let adapter = f.adapter();
        let owner = tokio::spawn(async move {
            adapter
                .invoke_command(context("alice").request(command("process-loss", 1, false)))
                .await
        });
        tokio::time::timeout(Duration::from_secs(5), f.backend.imports.entered.notified())
            .await
            .unwrap();
        assert!(!owner.is_finished());
        // Dropping the transport waiter is insufficient to simulate process
        // loss. Keep the actual Store live and let process::exit sever it.
        Some(owner)
    } else {
        let response = invoke(&f, "process-loss", 1, kind == "rejected").await;
        if kind == "committed" {
            assert_eq!(aggregate(&success(&response).payload), 1);
            assert_eq!(success(&response).effect_ids.len(), 1);
        } else {
            assert_eq!(
                response.command.as_ref().unwrap().outcome,
                t::CommandOutcome::Rejected as i32
            );
            assert!(matches!(
                response.invocation.as_ref().unwrap().result,
                Some(i::invoke_response::Result::DeclaredError(_))
            ));
        }
        drop(response); // the terminal reply is lost before the owned process dies
        None
    };
    let inventory = inventory::read(&f.store).await;
    let record = latent_commit::atomic::CommandRecord::decode(&inventory.commands[0]).unwrap();
    assert_eq!(record.attempt(), 1);
    assert_eq!(
        record.outcome(),
        match kind {
            "pending" => latent_commit::atomic::Outcome::Pending,
            "committed" => latent_commit::atomic::Outcome::Committed,
            "rejected" => latent_commit::atomic::Outcome::Rejected,
            _ => unreachable!(),
        }
    );
    for bytes in &inventory.results {
        latent_commit::atomic::DurableResult::decode(bytes)
            .unwrap()
            .verify(&record)
            .unwrap();
    }
    assert_eq!(record.effect_ids().len(), usize::from(kind == "committed"));
    assert_eq!(inventory.results.len(), usize::from(kind != "pending"));
    assert_eq!(
        inventory.pending_results.len(),
        usize::from(kind == "pending")
    );
    assert_eq!(inventory.state.len(), usize::from(kind == "committed"));
    assert_eq!(inventory.effects.len(), usize::from(kind == "committed"));
    assert_eq!(
        inventory.effects,
        record
            .effect_ids()
            .iter()
            .map(|identity| identity.hex())
            .collect::<Vec<_>>()
    );
    let runtime = f.backend.real.resource_snapshot();
    assert_eq!(f.executions(), 1);
    assert_eq!(runtime.stores_created, 1);
    assert_eq!(runtime.live_stores, u64::from(kind == "pending"));
    let probe = inventory::Probe {
        pid: std::process::id(),
        kind: kind.into(),
        root: f.persisted_root().into(),
        executions: f.executions(),
        stores_created: runtime.stores_created,
        live_stores: runtime.live_stores,
        inventory,
    };
    let bytes = serde_json::to_vec(&probe).unwrap();
    assert!(bytes.len() <= 64 * 1024);
    let path = PathBuf::from(std::env::var_os(CHILD_PROBE).unwrap());
    assert_eq!(path.parent().unwrap(), f.persisted_root().parent().unwrap());
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)
        .unwrap();
    file.write_all(&bytes).unwrap();
    file.sync_all().unwrap();
    assert_eq!(response.is_some(), kind == "pending");
    // Neither Rust Drop nor fixture/store/dispatcher/manager clean shutdown runs.
    std::process::exit(LOST_PROCESS_EXIT);
}
