from pathlib import Path
import subprocess

root=Path(r'C:\Users\turkins\Desktop\lf-p4-current-public-effect-union-v12')
name='crates/latent-effects/src/dispatch_store/effect_management/tests.rs'
path=root/name
path.parent.mkdir(parents=True,exist_ok=True)
source=subprocess.check_output(['git','-C',str(root),'show',f'HEAD:{name}']).decode()
marker='''    assert_eq!(receipt.completed_at_millis(), 106);
    let record = fixture.record();'''
assert source.count(marker)==1
source=source.replace(marker,'''    assert_eq!(receipt.completed_at_millis(), 106);
    assert_eq!(
        EffectManagementCatalog::receipt_for_effect(
            &fixture.store().snapshot().unwrap(), &fixture.record(),
        ).unwrap(),
        Some(receipt.clone()),
    );
    let record = fixture.record();''',1)
marker='''fn administrative_terminal_disposition_keeps_uncertain_facts_and_payload_holds() {
    let fixture = Fixture::new(StoreLimits::default());'''
assert source.count(marker)==1
source=source.replace(marker,marker+'''
    assert!(EffectManagementCatalog::receipt_for_effect(
        &fixture.store().snapshot().unwrap(), &fixture.record(),
    ).unwrap().is_none());''',1)
marker='''    assert_eq!(receipt.provider_receipt(), None);
    assert_eq!(fixture.record().disposition(), Disposition::DeadLettered);'''
assert source.count(marker)==1
source=source.replace(marker,'''    assert_eq!(receipt.provider_receipt(), None);
    assert_eq!(
        EffectManagementCatalog::receipt_for_effect(
            &fixture.store().snapshot().unwrap(), &fixture.record(),
        ).unwrap(),
        Some(receipt.clone()),
    );
    assert_eq!(fixture.record().disposition(), Disposition::DeadLettered);''',1)
path.write_text(source,encoding='utf8',newline='\n')
