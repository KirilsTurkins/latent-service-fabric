// lsf-example-begin: capsule
#![cfg_attr(not(target_arch = "wasm32"), allow(dead_code))]
#[cfg(target_arch = "wasm32")]
wit_bindgen::generate!({
    path: "wit", world: "service",
    with: {
        "latent:state/key-value@0.2.0": latent_guest::bindings::state,
        "latent:intents/staging@0.1.0": latent_guest::bindings::intents,
    },
});
#[cfg(target_arch = "wasm32")]
use exports::examples::transactional_aggregate::api::{Aggregate, BusinessError, Guest, ScanResult, UpdateRequest};
#[cfg(target_arch = "wasm32")]
use latent_guest::{intents::Intent, state::{Command, Query, Value, VersionedValue}};

#[cfg(target_arch = "wasm32")]
const KEY: &[u8] = b"aggregate/count";
#[cfg(target_arch = "wasm32")]
const MEDIA: &str = "application/vnd.lsf.aggregate-v1";
#[cfg(target_arch = "wasm32")]
fn count(value: Option<&VersionedValue>) -> Result<u64, BusinessError> {
    match value {
        None => Ok(0),
        Some(value) if value.value.media_type == MEDIA && value.value.metadata.is_empty() =>
            value.value.bytes.as_slice().try_into().map(u64::from_le_bytes).map_err(|_| BusinessError::MalformedState),
        Some(_) => Err(BusinessError::MalformedState),
    }
}
#[cfg(target_arch = "wasm32")]
struct Capsule;
#[cfg(target_arch = "wasm32")]
impl Guest for Capsule {
    async fn update(request: UpdateRequest) -> Result<Aggregate, BusinessError> {
        let mut command = Command::acquire().expect("admitted command");
        let old = command.get(KEY.to_vec()).await.expect("state read");
        let count = count(old.as_ref())?.checked_add(u64::from(request.delta)).ok_or(BusinessError::Overflow)?;
        let payload = Value { bytes: count.to_le_bytes().to_vec(), media_type: MEDIA.into(), metadata: vec![] };
        command.put(KEY.to_vec(), payload.clone()).await.expect("stage state");
        Intent::new("approved-event".into(), "event".into(), payload).stage(&mut command).await.expect("stage event");
        // A business rejection follows staging so the host must discard both.
        if request.reject { return Err(BusinessError::Rejected); }
        let staged = command.get(KEY.to_vec()).await.expect("staged read").expect("staged value");
        Ok(Aggregate { count, version: staged.version })
    }
    async fn query() -> Result<Aggregate, BusinessError> {
        let mut query = Query::acquire().expect("admitted fresh query");
        let value = query.get(KEY.to_vec()).await.expect("fresh state read");
        let version = query.info().expect("view identity").version;
        Ok(Aggregate { count: count(value.as_ref())?, version })
    }
    async fn scan(prefix: Vec<u8>, limit: u32, cursor: Option<Vec<u8>>) -> Result<ScanResult, BusinessError> {
        let mut query = Query::acquire().expect("admitted fresh query");
        let mut page = query.scan(prefix, limit, cursor).await.expect("bounded scan");
        let info = page.info().expect("page identity");
        let mut count = 0;
        while page.next().await.expect("bounded entry").is_some() { count += 1; }
        assert_eq!(count, info.entry_count);
        Ok(ScanResult { count, encoded_bytes: info.encoded_bytes, view_version: info.view.version, next_cursor: info.next_cursor })
    }
}
#[cfg(target_arch = "wasm32")]
export!(Capsule);
// lsf-example-end: capsule
