from pathlib import Path

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
path=root/'crates/latent-wire/src/phase4/state_management/effect_read.rs'
source=path.read_text()
start=source.index('    let payload_available = payload_available(view, &record)?;')
end=source.index('    if let Err(error) = keeper.current(&read, &mut || {}) {',start)
block=source[start:end]
assert block.endswith('    };\n')
block=block.replace('payload_available(view, &record)?','payload_available(view, record)?')
block=block.replace('management_receipt_id(view, &record)?','management_receipt_id(view, record)?')
block=block.replace('effect_id: request.effect_id.clone(),','effect_id: effect_id.into(),')
block=block.replace('effect_record_version(&raw)','effect_record_version(raw)')
source=source[:start]+'    let effect = effect_status(view, &command, &record, &raw, &request.effect_id)?;\n'+source[end:]
marker='fn payload_available('
helper='''fn effect_status(
    view: &ReadView,
    command: &CommandRecord,
    record: &EffectRecord,
    raw: &[u8],
    effect_id: &str,
) -> Result<t::EffectReceipt, StoreError> {
    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
'''+block+'    Ok(effect)\n}\n\n'
assert source.count(marker)==1
source=source.replace(marker,helper+marker)
source=source.replace('''    let authority = record.authority().map_err(|_| StoreError::Corrupt)?;
    if !valid_link''','''    if !valid_link''',1)
path.write_text(source,encoding='utf8',newline='\n')
