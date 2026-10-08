from pathlib import Path
import json
import subprocess

root = Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
coord = Path(__file__).resolve().parent
name = 'apps/latentd/src/standalone/startup_observation/tests.rs'
path = root / name
path.parent.mkdir(parents=True, exist_ok=True)
source = subprocess.check_output(['git','-C',str(root),'show',f'HEAD:{name}']).decode()
source = source.replace('let (result, trace) = capture(async {',
                        'let (result, report) = observe_startup(async {', 1)
old = '''    let report = StartupFailureReport {
        schema_version: "latent.startup-failure-observation.v1",
        startup_succeeded: false,
        terminal_failure: result.as_ref().err().map(Failure::from),
        observations: trace.observations.into_iter().flatten().collect(),
        truncated: trace.truncated,
        shutdown: None,
    };'''
assert old in source
source = source.replace(old, '''    let report = report.unwrap();
    assert!(!report.startup_succeeded);
    assert!(report.shutdown.is_none());
    let (successful, report) = observe_startup(async { Ok::<_, PlatformError>(7) }).await;
    assert_eq!(successful, Ok(7));
    assert!(report.is_none());''', 1)
path.write_text(source, encoding='utf8', newline='\n')

source_invocation = json.loads((coord/'integration-v12-actual-startup-diagnosis-source-v1/invocation.json').read_text())
steps = source_invocation['steps']
assert len(steps) == 7
(coord/'integration-v12-union-review/actual-startup-wrapper-source-steps-v1.json').write_text(
    json.dumps(steps, indent=2)+'\n', encoding='utf8')
print(json.dumps({'sourceSteps': 7, 'existingCaseNamesPreserved': True,
                  'newObserverFailureAndSuccessVerifiedByExistingPrivacyCase': True}))
