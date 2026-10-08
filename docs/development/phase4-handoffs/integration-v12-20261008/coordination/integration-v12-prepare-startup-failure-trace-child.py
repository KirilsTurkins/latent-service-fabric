"""Preserve the actual startup result while capturing finite daemon diagnostics."""
from pathlib import Path
import json
import subprocess

root = Path(r'C:\Users\turkins\Desktop\lf-p4-current-java-bd4-union-v12')
coord = Path(__file__).resolve().parent
parent = '504f932350b3527531c3fe09d83f04e95737b6d1'
def git(*args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()
assert git('rev-parse', 'HEAD') == parent and not git('status', '--porcelain')
git('switch', '-c', 'fix/phase4-observe-actual-daemon-startup-v12')
paths = ('apps/latentd/src/standalone/startup_observation.rs',
         'apps/latentd/src/command/serve.rs')
for name in paths:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    original = subprocess.check_output(['git', '-C', str(root), 'show', f'HEAD:{name}'])
    if path.exists():
        assert path.read_bytes().replace(b'\r\n', b'\n') == original.replace(b'\r\n', b'\n')
    path.write_bytes(original.replace(b'\r\n', b'\n'))

path = root / paths[0]
source = path.read_text(encoding='utf8')
marker = 'impl StandaloneNode {\n'
assert source.count(marker) == 1
source = source.replace(marker, '''pub(super) async fn observe_startup<T>(
    future: impl Future<Output = Result<T, PlatformError>>,
) -> (Result<T, PlatformError>, Option<StartupFailureReport>) {
    let (result, trace) = capture(future).await;
    let report = result.as_ref().err().map(|error| StartupFailureReport {
        schema_version: "latent.startup-failure-observation.v1",
        startup_succeeded: false,
        terminal_failure: Some(Failure::from(error)),
        observations: trace.observations.into_iter().flatten().collect(),
        truncated: trace.truncated,
        shutdown: None,
    });
    (result, report)
}

''' + marker)
path.write_text(source, encoding='utf8', newline='\n')

path = root / paths[1]
source = path.read_text(encoding='utf8')
old = '''    let node = StandaloneNode::start(settings, control, threads)
        .await
        .map_err(|error| Failure::new("startup", error.code))?;'''
assert source.count(old) == 1
new = '''    let (startup, observation) = crate::standalone::observe_startup(
        StandaloneNode::start(settings, control, threads),
    )
    .await;
    if let Some(observation) = observation {
        // Closed producer-owned codes only; retain the original startup error
        // and cleanup result even if writing the bounded diagnostic fails.
        if let Ok(encoded) = serde_json::to_vec(&observation) {
            if encoded.len() <= 16 * 1024 {
                use std::io::Write;
                let _ = std::io::stderr().lock().write_all(&encoded);
                let _ = std::io::stderr().lock().write_all(b"\\n");
            }
        }
    }
    let node = startup.map_err(|error| Failure::new("startup", error.code))?;'''
source = source.replace(old, new)
path.write_text(source, encoding='utf8', newline='\n')

name = 'apps/latentd/src/standalone.rs'
path = root / name
original = subprocess.check_output(['git', '-C', str(root), 'show', f'HEAD:{name}']).decode()
path.parent.mkdir(parents=True, exist_ok=True)
assert 'pub use startup_observation::StartupFailureReport;' in original
path.write_text(original.replace('pub use startup_observation::StartupFailureReport;',
    'pub use startup_observation::StartupFailureReport;\npub(crate) use startup_observation::observe_startup;'),
    encoding='utf8', newline='\n')

steps = json.loads((coord/'integration-v12-union-review/pr828-current-lookup-native-steps.json').read_text())
steps[0] += ['-p', 'latent-wire', '-p', 'latent-packaging', '-p', 'latent-policy']
steps += json.loads((coord/'integration-v12-union-review/current-java-strict-final-native-steps.json').read_text())[:2]
(coord/'integration-v12-union-review/pr828-current-java-native-steps-v2.json').write_text(
    json.dumps(steps, indent=2)+'\n', encoding='utf8')
print(json.dumps({'parent': parent, 'paths': [*paths, name], 'httpNativeSteps': len(steps),
                  'runtimeBudgetsChanged': False, 'businessRetriesAdded': False}))
