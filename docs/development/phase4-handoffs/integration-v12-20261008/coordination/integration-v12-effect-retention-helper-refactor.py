from pathlib import Path

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
path=root/'crates/latent-wire/src/phase4/state_management/effect_read.rs'
source=path.read_text()
start=source.index('    let payload_available = match view.get(')
end=source.index('    let management = record.management();',start)
source=source[:start]+'''    let payload_available = payload_available(view, &record)?;
    let management_operation_receipt_id = management_receipt_id(view, &record)?;
'''+source[end:]
marker='fn valid_link(\n'
assert source.count(marker)==1
helpers='''fn payload_available(view: &ReadView, record: &EffectRecord) -> Result<bool, StoreError> {
    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
    match view.get(&latent_effects::dispatch_store::effect_payload_key(&authority.link().effect)?)? {
        Some(bytes) => {
            latent_effects::payload::PayloadRecord::decode(&bytes)
                .map_err(|_| StoreError::Corrupt)?
                .verify(&authority)
                .map_err(|_| StoreError::Corrupt)?;
            Ok(true)
        }
        None if record.disposition().terminal() => Ok(false),
        None => Err(StoreError::Corrupt),
    }
}

fn management_receipt_id(view: &ReadView, record: &EffectRecord) -> Result<Option<String>, StoreError> {
    let receipt =
        latent_effects::dispatch_store::effect_management::EffectManagementCatalog::receipt_for_effect(
            view, record,
        )?;
    receipt.as_ref().map(|receipt| {
        receipt.digest().map(|digest| format!("effect-management:sha256:{}", super::response::hex(&digest)))
    }).transpose().map_err(|_| StoreError::Corrupt)
}

'''
source=source.replace(marker,helpers+marker)
path.write_text(source,encoding='utf8',newline='\n')
