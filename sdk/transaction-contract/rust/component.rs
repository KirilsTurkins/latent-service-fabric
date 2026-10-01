//! Compile-definition probe; execution and transactional authority are separate.
#![cfg(target_arch = "wasm32")]

wit_bindgen::generate!({
    path: ["../../wit/platform/clock", "../../wit/platform/random",
           "../../wit/platform/state", "../../wit/platform/intents",
           "../../sdk/transaction-contract/wit"],
    world: "tests:transaction-contract/service@1.0.0",
    generate_all,
});

use latent::intents::staging;
use latent::state::key_value as state;

struct Capsule;
impl exports::tests::transaction_contract::api::Guest for Capsule {
    async fn run(mode: u32) -> u64 {
        if mode == 0 {
            let view = state::acquire_query().expect("admitted query");
            let info = state::query_info(&view).expect("query identity");
            let value = state::get_query(&view, b"k".to_vec())
                .await
                .expect("query get");
            let page = state::scan_query(&view, vec![], 1, None)
                .await
                .expect("query page");
            let description = state::describe_page(&page).expect("page bounds");
            let item = state::page_next(&page).await.expect("page entry");
            return u64::from(description.entry_count)
                + u64::from(item.is_some())
                + u64::from(value.is_some())
                + u64::try_from(info.version.len()).expect("bounded version");
        }
        let transaction = state::acquire_command().expect("admitted command");
        let info = state::info(&transaction).expect("command identity");
        let existing = state::get(&transaction, b"k".to_vec())
            .await
            .expect("command get");
        let value = state::Value {
            bytes: vec![],
            media_type: "application/octet-stream".into(),
            metadata: vec![("present".into(), "".into())],
        };
        state::put(&transaction, b"k".to_vec(), value.clone())
            .await
            .expect("staged value");
        state::delete(&transaction, b"k".to_vec())
            .await
            .expect("staged deletion");
        let page = state::scan(&transaction, vec![], 1, None)
            .await
            .expect("command page");
        let description = state::describe_page(&page).expect("page bounds");
        let item = state::page_next(&page).await.expect("page entry");
        let intent = staging::Intent {
            binding: "approved-mail".into(),
            operation: "send".into(),
            payload: value,
            expires_at_unix_millis: Some(u64::MAX),
        };
        let staged = staging::stage(&transaction, intent)
            .await
            .expect("staged intent");
        u64::from(staged.sequence)
            + u64::from(description.entry_count)
            + u64::from(existing.is_some())
            + u64::from(item.is_some())
            + u64::try_from(info.command_id.len()).expect("bounded identity")
    }
}
export!(Capsule);
