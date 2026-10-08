from pathlib import Path
import json
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
parent='9b5723db3e4b82ee13df3695c42bff8877143223'
def git(*args):
    return subprocess.check_output(['git','-C',str(root),*args],text=True).strip()
assert git('rev-parse','HEAD')==parent and not git('status','--porcelain')
git('switch','-c','feat/phase4-effect-actual-retention-receipt-v12')

name='crates/latent-effects/src/dispatch_store/effect_management/validation.rs'
path=root/name
path.parent.mkdir(parents=True,exist_ok=True)
source=subprocess.check_output(['git','-C',str(root),'show',f'HEAD:{name}']).decode()
marker='''    pub(crate) fn validate_effect(
'''
assert source.count(marker)==1
addition='''    /// Read the actual latest management receipt after its durable target,
    /// plan, reservation and dispatcher-stamp links have been verified.
    pub fn receipt_for_effect(
        view: &ReadView,
        record: &EffectRecord,
    ) -> Result<Option<EffectManagementReceipt>, StoreError> {
        Self::validate_effect(view, record)?;
        let Some(stamp) = record.management() else {
            return Ok(None);
        };
        let operation =
            crate::effect_identity::parse(stamp.operation_digest()).map_err(storage_error)?;
        let key = codec::row(RECEIPT_PREFIX, &operation);
        let bytes = view.get(&key)?.ok_or(StoreError::Corrupt)?;
        validate_receipt(view, &key, &bytes)?;
        EffectManagementReceipt::decode(&bytes)
            .map(Some)
            .map_err(codec::storage)
    }

'''
source=source.replace(marker,addition+marker)
path.write_text(source,encoding='utf8',newline='\n')

name='crates/latent-wire/src/phase4/state_management/effect_read.rs'
path=root/name
source=path.read_text()
marker='''    let management = record.management();
'''
assert source.count(marker)==1
addition='''    let payload_available = match view
        .get(&latent_effects::dispatch_store::effect_payload_key(&request.effect_id)?)?
    {
        Some(bytes) => {
            latent_effects::payload::PayloadRecord::decode(&bytes)
                .map_err(|_| StoreError::Corrupt)?
                .verify(&authority)
                .map_err(|_| StoreError::Corrupt)?;
            true
        }
        None if record.disposition().terminal() => false,
        None => return Err(StoreError::Corrupt),
    };
    let management_receipt =
        latent_effects::dispatch_store::effect_management::EffectManagementCatalog::receipt_for_effect(
            view, &record,
        )?;
    let management_operation_receipt_id = management_receipt
        .as_ref()
        .map(|receipt| {
            receipt.digest().map(|digest| format!(
                "effect-management:sha256:{}",
                super::response::hex(&digest),
            ))
        })
        .transpose()
        .map_err(|_| StoreError::Corrupt)?;
'''
source=source.replace(marker,addition+marker)
source=source.replace('''            ..Default::default()
        }),
        management_operation_receipt_id: None,''',
'''            payload_available,
        }),
        management_operation_receipt_id,''',1)
path.write_text(source,encoding='utf8',newline='\n')

name='crates/latent-wire/src/phase4/state_management/tests/effects.rs'
path=root/name
source=path.read_text()
source=source.replace('''    assert!(status.provider_receipt.is_none());''',
'''    assert!(status.provider_receipt.is_none());
    assert!(status.retention.as_ref().unwrap().payload_available);
    assert!(status.management_operation_receipt_id.is_none());''',1)
marker='''    drop(response);
    // Native time expires the plan.'''
assert source.count(marker)==1
addition='''    drop(response);
    let response = effect
        .fixture
        .backend
        .execute_state(
            operator("alice"),
            effect.request("terminal-status").effect.unwrap().into(),
        )
        .await
        .unwrap();
    let contract::Response::GetEffect(value) = &response.response else {
        panic!("actual terminal effect status required");
    };
    let status = value.effect.as_ref().unwrap();
    assert_eq!(
        status.disposition,
        latent_rpc::transaction::v1::EffectDisposition::AdministrativelyTerminated as i32,
    );
    assert_eq!(status.management_operation_receipt_id.as_deref(), Some(receipt.receipt_id.as_str()));
    assert!(status.provider_receipt.is_none());
    assert!(status.retention.as_ref().unwrap().payload_available);
    drop(response);
    // Native time expires the plan.'''
source=source.replace(marker,addition,1)
path.write_text(source,encoding='utf8',newline='\n')
print(json.dumps({'parent':parent,'changedPaths':3,'existingCaseNamesAndAllOriginalAssertionsPreserved':True,
                  'payloadBytesExposed':False,'managementProviderFactsManufactured':False}))
