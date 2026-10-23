"""Temporary exact-source candidate builder; never creates a commit or moves a ref."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

ROOT = 'crates/latent-audit/src/durable/store/lifecycle'
RUST = ['crates/latent-audit/src/durable.rs', 'crates/latent-audit/src/durable/store.rs',
        'crates/latent-audit/src/durable/store/io.rs', 'crates/latent-audit/src/durable/store/query.rs',
        ROOT + '.rs', *[ROOT + '/' + name + '.rs' for name in ['model', 'storage', 'rollover', 'transfer', 'tests', 'inspect']],
        'apps/latent/src/lib.rs', 'apps/latent/src/args/audit.rs', 'apps/latent/src/args/audit/maintenance.rs',
        'apps/latent/src/args/validation.rs', 'apps/latent/src/command.rs',
        'apps/latent/src/management/phase2/prepare.rs', 'apps/latent/src/audit_maintenance.rs',
        'apps/latent/src/audit_maintenance/projection.rs', 'apps/latent/src/audit_maintenance/tests.rs']
ALLOWED = set(RUST) | {'tools/ci/suites.json', 'apps/latent/Cargo.toml', 'Cargo.lock'}


def replace(name, before, after):
    path = Path(name)
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise SystemExit('candidate-context-mismatch:' + name + ':' + before[:70])
    path.write_text(text.replace(before, after))


def prepare():
    replace(ROOT + '.rs', 'mod model;', 'mod inspect;\npub use inspect::{AuditCustodyStatus, AuditJournalStatus};\nmod model;')
    replace('crates/latent-audit/src/durable.rs', 'pub use model::*;', 'pub use model::*;\npub use store::lifecycle::{AuditCustodyStatus, AuditJournalStatus};')
    replace('apps/latent/src/lib.rs', 'mod args;', 'mod args;\nmod audit_maintenance;')
    replace('apps/latent/src/args/audit.rs', 'use clap::{Args, Subcommand, ValueEnum};', 'pub mod maintenance;\nuse clap::{Args, Subcommand, ValueEnum};')
    replace('apps/latent/src/args/audit.rs', '    Query(QueryArgs),\n}', '''    Query(QueryArgs),
    /// Exclusive stopped-node maintenance, authorized by private-filesystem ownership.
    #[command(subcommand)]
    Maintenance(maintenance::MaintenanceCommand),
    /// Verify or query one operator-held sealed epoch without contacting a node.
    #[command(subcommand)]
    Archive(maintenance::ArchiveCommand),
}
impl AuditCommand {
    pub const fn is_local(&self) -> bool { !matches!(self, Self::Query(_)) }
    pub const fn name(&self) -> &'static str {
        match self {
            Self::Query(_) => "audit query",
            Self::Maintenance(command) => command.name(),
            Self::Archive(command) => command.name(),
        }
    }
}''')
    replace('apps/latent/src/args/validation.rs', '            Command::Audit(super::audit::AuditCommand::Query(args)) => {', '''            Command::Audit(super::audit::AuditCommand::Maintenance(command)) => command.validate(self),
            Command::Audit(super::audit::AuditCommand::Archive(command)) => command.validate(self),
            Command::Audit(super::audit::AuditCommand::Query(args)) => {''')
    replace('apps/latent/src/management/phase2/prepare.rs', '    let AuditCommand::Query(args) = command;', '    let AuditCommand::Query(args) = command else { return Err(invalid_input()); };')
    replace('apps/latent/src/command.rs', '            Command::Package(command) => crate::package::execute(cli, command),', '''            Command::Audit(command) if command.is_local() => crate::audit_maintenance::execute(cli, command),
            Command::Package(command) => crate::package::execute(cli, command),''')
    replace('apps/latent/src/command.rs', 'Command::Audit(_) => "audit query",', 'Command::Audit(command) => command.name(),')
    replace('apps/latent/Cargo.toml', 'latent-artifacts = { path = "../../crates/latent-artifacts" }', 'latent-artifacts = { path = "../../crates/latent-artifacts" }\nlatent-audit = { path = "../../crates/latent-audit" }')
    path = Path('Cargo.lock')
    text = path.read_text()
    blocks = text.split('[[package]]')
    selected = [index for index, block in enumerate(blocks) if block.startswith('\nname = "latent"\n')]
    if len(selected) != 1:
        raise SystemExit('ambiguous-lock-package')
    index = selected[0]
    if '\n "latent-audit",\n' not in blocks[index]:
        assert blocks[index].count('\n "latent-artifacts",\n') == 1
        blocks[index] = blocks[index].replace('\n "latent-artifacts",\n', '\n "latent-artifacts",\n "latent-audit",\n')
        path.write_text('[[package]]'.join(blocks))
    tests = 'apps/latent/src/audit_maintenance/tests.rs'
    replace(tests, 'let root = directory.0.join("active"), archives = directory.0.join("archives"), destination = directory.0.join("off-node-custody");', 'let root = directory.0.join("active"); let archives = directory.0.join("archives"); let destination = directory.0.join("off-node-custody");')
    replace(tests, 'let missing = directory.0.join("missing"), archives = directory.0.join("archives");', 'let missing = directory.0.join("missing"); let archives = directory.0.join("archives");')
    replace(tests, 'let digest = format!', 'let digest: latent_core::ArtifactBlobDigest = format!')
    for name in [ROOT + '.rs', ROOT + '/transfer.rs']:
        path = Path(name)
        text = path.read_text()
        text = re.sub(r'\s*#\[expect\(\s*clippy::too_many_arguments,\s*reason = "[^"]*"\s*\)\]\n', '\n', text)
        path.write_text(text)
    replace(ROOT + '.rs', 'Duration::from_secs(120)', 'Duration::from_mins(2)')
    path = Path(ROOT + '/tests.rs')
    path.write_text(path.read_text().replace('_directory', 'directory').replace('filter: Default::default(),', 'filter: crate::AuditFilter::default(),').replace('Deadline(Instant::now() - TIMEOUT)', 'Deadline(Instant::now().checked_sub(TIMEOUT).unwrap())'))
    path = Path('tools/ci/suites.json')
    data = json.loads(path.read_text())
    rows = [row for row in data['suites'] if row.get('package') == 'latent' and row.get('kind') == 'lib']
    if len(rows) != 1:
        raise SystemExit('ambiguous-cli-suite-owner')
    cases = {'audit_maintenance::tests::' + name for name in [
        'native_operator_workflow_rolls_multiple_epochs_queries_and_transfers_exact_history',
        'offline_grammar_rejects_rpc_credentials_implicit_scope_and_unbounded_selectors',
        'missing_and_unsafe_roots_are_never_initialized_and_errors_preserve_uncertainty']}
    row = rows[0]
    added = cases - set(row['expectedCases'])
    row['expectedCases'] = sorted(set(row['expectedCases']) | cases)
    row['minimumCases'] += len(added)
    path.write_text(json.dumps(data, indent=2) + '\n')
    subprocess.run(['rustup', 'run', '1.97.1', 'rustfmt', '--edition', '2021', '--config', 'skip_children=true', *RUST], check=True)


def publish():
    changed = set(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines())
    if not changed <= ALLOWED:
        raise SystemExit('unexpected-candidate-change:' + repr(sorted(changed - ALLOWED)))
    receipt = {'source': os.environ['GITHUB_SHA'], 'files': {}}
    for name in sorted(changed):
        raw = Path(name).read_bytes()
        if len(raw) > 2 * 1024 * 1024:
            raise SystemExit('candidate-byte-bound')
        body = json.dumps({'content': base64.b64encode(raw).decode(), 'encoding': 'base64'}).encode()
        request = urllib.request.Request('https://api.github.com/repos/KirilsTurkins/latent-service-fabric/git/blobs', data=body,
            headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(request, timeout=30) as response:
            receipt['files'][name] = json.load(response)['sha']
    Path(os.environ['RUNNER_TEMP'], 'audit-candidates.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('AUDIT_CANDIDATES=' + json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['publish']:
        publish()
    else:
        raise SystemExit('explicit-candidate-operation-required')
