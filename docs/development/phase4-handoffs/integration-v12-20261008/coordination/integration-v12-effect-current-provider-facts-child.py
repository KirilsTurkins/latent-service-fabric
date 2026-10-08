from pathlib import Path

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
path=root/'crates/latent-wire/src/phase4/state_management/effect_read.rs'
source=path.read_text()
old='''        provider_receipt: latest.and_then(|r| r.provider_receipt.clone()),
        failure_code: latest.map(|r| r.reason.clone()),
        occurred_at_unix_millis: latest
            .map_or(authority.committed_at_millis(), |r| r.observed_at_millis),'''
assert source.count(old)==1
new='''        provider_receipt: management
            .and_then(|stamp| stamp.provider_receipt().map(str::to_owned))
            .or_else(|| latest.and_then(|receipt| receipt.provider_receipt.clone())),
        failure_code: if management
            .is_some_and(|stamp| stamp.fact() == EffectManagementFact::ProviderConfirmed)
        {
            None
        } else {
            latest.map(|receipt| receipt.reason.clone())
        },
        occurred_at_unix_millis: management.map_or_else(
            || latest.map_or(authority.committed_at_millis(), |receipt| receipt.observed_at_millis),
            latent_effects::dispatch::EffectManagementStamp::observed_at_millis,
        ),'''
source=source.replace(old,new)
path.write_text(source,encoding='utf8',newline='\n')
path=root/'crates/latent-wire/src/phase4/state_management/tests/effects.rs'
source=path.read_text()
marker='''    drop(response);
    drop(ordinary);
    effect.finish().await;'''
assert source.count(marker)==1
new='''    let actual_receipt_id = receipt.receipt_id.clone();
    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            effect.request("confirmed-effect-status").effect.unwrap().into(),
        )
        .await
        .unwrap();
    let contract::Response::GetEffect(value) = &response.response else {
        panic!("actual provider-confirmed status required");
    };
    let status = value.effect.as_ref().unwrap();
    assert_eq!(status.disposition,
        latent_rpc::transaction::v1::EffectDisposition::ProviderAcknowledged as i32);
    assert_eq!(status.provider_receipt.as_deref(), Some("controlled-positive-provider-receipt"));
    assert!(status.failure_code.is_none());
    assert_eq!(status.management_operation_receipt_id.as_deref(), Some(actual_receipt_id.as_str()));
    assert_eq!(effect.provider.as_ref().unwrap().sends.load(Ordering::SeqCst), 1);
    assert_eq!(effect.provider.as_ref().unwrap().lookups.load(Ordering::SeqCst), 1);
    drop(response);
    drop(ordinary);
    effect.finish().await;'''
source=source.replace(marker,new)
path.write_text(source,encoding='utf8',newline='\n')
