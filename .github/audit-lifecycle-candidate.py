"""Temporary exact-source cleanup and immutable blob publication; no ref writes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap
import urllib.request

ROOT = 'crates/latent-audit/src/durable/store/lifecycle'
RUST = ['crates/latent-audit/src/durable/store.rs', 'crates/latent-audit/src/durable/store/io.rs', ROOT + '.rs',
        ROOT + '/model.rs', ROOT + '/storage.rs', ROOT + '/rollover.rs', ROOT + '/transfer.rs',
        'apps/latent/src/args/audit/maintenance.rs', 'apps/latent/src/audit_maintenance.rs',
        'apps/latent/src/audit_maintenance/projection.rs', 'apps/latent/src/audit_maintenance/tests.rs']
DOCS = ['docs/phase-2-audit.md', 'docs/reference/standalone-node.md', 'docs/operations/static-route-sets.md']
ALLOWED = set(RUST + DOCS)


def replace(name, before, after):
    path = Path(name)
    text = path.read_text()
    if after in text:
        return
    if text.count(before) != 1:
        raise SystemExit('candidate-context-mismatch:' + name + ':' + before[:70])
    path.write_text(text.replace(before, after))


def prepare():
    for name in [ROOT + '.rs', 'apps/latent/src/args/audit/maintenance.rs']:
        replace(name, '32768..=262144', '32_768..=262_144')
    name = 'crates/latent-audit/src/durable/store/io.rs'
    replace(name, '        Some("ROLLOVER" | "ROLLOVER.next" | "TRANSFER" | "TRANSFER.next") => Ok(16384),\n        Some("INTENT" | "INTENT.next" | "record.next") => Ok(16384),',
        '        Some("ROLLOVER" | "ROLLOVER.next" | "TRANSFER" | "TRANSFER.next" | "INTENT" | "INTENT.next" | "record.next") => Ok(16384),')
    model = ROOT + '/model.rs'
    for kind in ['Seal', 'Custody']:
        replace(model, 'pub(super) struct ' + kind + ' {', '#[expect(clippy::struct_field_names, reason = "Persisted descriptors name their hash and identity domains explicitly")]\npub(super) struct ' + kind + ' {')
    rollover = ROOT + '/rollover.rs'
    replace(rollover, 'prepare(&source, mode, old_custody, &archive_root)?', 'prepare(&source, &mode, old_custody, &archive_root)?')
    replace(rollover, 'fn prepare(source: &Store, mode: Mode, custody: Custody, root: &io::Root)', 'fn prepare(source: &Store, mode: &Mode, custody: Custody, root: &io::Root)')
    replace(rollover, 'execute(root, storage::existing_root(custody)?, transition, deadline)', 'execute(root, &storage::existing_root(custody)?, &transition, deadline)')
    replace(rollover, 'execute(source.root, archive_root, transition, deadline)', 'execute(source.root, &archive_root, &transition, deadline)')
    replace(rollover, '    custody: io::Root,\n    transition: Transition,', '    custody: &io::Root,\n    transition: &Transition,')
    path = Path(rollover)
    text = path.read_text()
    start = text.index('fn execute(')
    before, body = text[:start], text[start:]
    body = body.replace('validate_active(&root, &transition)', 'validate_active(&root, transition)').replace('storage::read_custody(&custody)', 'storage::read_custody(custody)')
    body = body.replace('storage::inventory(&custody,', 'storage::inventory(custody,').replace('storage::verify_retained(&custody,', 'storage::verify_retained(custody,')
    body = body.replace('publish(root, &custody, &transition, deadline)', 'publish(root, custody, transition, deadline)')
    path.write_text(before + body)
    replace(ROOT + '/storage.rs', 'previous = entry.seal.clone();', 'previous.clone_from(&entry.seal);')
    transfer = ROOT + '/transfer.rs'
    replace(transfer, 'finish(&active, storage::existing_root(custody)?, transfer, deadline)', 'finish(&active, &storage::existing_root(custody)?, &transfer, deadline)')
    replace(transfer, 'finish(&active, custody, transfer, deadline)', 'finish(&active, &custody, &transfer, deadline)')
    replace(transfer, '    custody: io::Root,\n    transfer: Transfer,', '    custody: &io::Root,\n    transfer: &Transfer,')
    path = Path(transfer)
    text = path.read_text()
    start = text.index('fn finish(')
    before, body = text[:start], text[start:]
    body = body.replace('storage::read_custody(&custody)', 'storage::read_custody(custody)').replace('storage::inventory(&custody,', 'storage::inventory(custody,').replace('storage::verify_retained(&custody,', 'storage::verify_retained(custody,')
    path.write_text(before + body)
    path = Path('crates/latent-audit/src/durable/store.rs')
    text = path.read_text()
    if 'fn checked_root_names(' not in text:
        start = text.index('        let allowed = [')
        end = text.index('        let records = root.path.join("records");', start)
        block = textwrap.dedent(text[start:end])
        helper = '\nfn checked_root_names(root: &io::Root) -> Result<Vec<String>> {\n' + textwrap.indent(block, '    ') + '    Ok(names)\n}\n'
        text = text[:start] + '        let names = checked_root_names(&root)?;\n' + text[end:]
        text += helper
        path.write_text(text)
    projection = 'apps/latent/src/audit_maintenance/projection.rs'
    for method, typename in [('status', 'AuditJournalStatus'), ('coverage', 'AuditArchiveCoverage'), ('custody', 'AuditCustodyStatus'), ('rollover', 'AuditRolloverReceipt'), ('transfer', 'AuditTransferReceipt')]:
        replace(projection, 'fn ' + method + '(value: ' + typename + ')', 'fn ' + method + '(value: &' + typename + ')')
    replace(projection, 'value.archives.into_iter().map(coverage)', 'value.archives.iter().map(coverage)')
    replace(projection, 'coverage(value.archive)', 'coverage(&value.archive)')
    command = 'apps/latent/src/audit_maintenance.rs'
    for method in ['status', 'custody', 'rollover', 'transfer']:
        replace(command, '.map(projection::' + method + ')', '.map(|value| projection::' + method + '(&value))')
    replace(command, 'projection::coverage(coverage)', 'projection::coverage(&coverage)')
    path = Path('apps/latent/src/audit_maintenance/tests.rs')
    text = path.read_text()
    if 'fn verify_archive_pages(' not in text:
        start = text.index('    let archive = archives.join(first_epoch);')
        end = text.index('    let custody = run(', start)
        block = text[start:end]
        replacement = '    verify_archive_pages(&archives, first_epoch, &second_epoch);\n    let archive = archives.join(first_epoch);\n'
        text = text[:start] + replacement + text[end:]
        helper = '\nfn verify_archive_pages(archives: &Path, first_epoch: &str, second_epoch: &str) {\n' + block.replace('archives.join(&second_epoch)', 'archives.join(second_epoch)').replace('        &second_epoch,', '        second_epoch,') + '}\n'
        text += helper
        path.write_text(text)
    replace('docs/phase-2-audit.md', '''Retention rejects new records when full. There is no hidden pruning, overwrite,
rotation or remote exporter. Operators must provision finite capacity; reducing
limits cannot discard existing history to make it fit.''', '''Retention rejects new records when full. There is no hidden pruning, overwrite,
automatic rotation or remote exporter. The supported [stopped-node lifecycle](operations/audit-journal-lifecycle.md)
seals and verifies an epoch before releasing its active capacity, and bounds local
custody to four archives. Explicit verified transfer is required before that
custody can grow again. Global sequences continue across linked epochs; version-1
journals upgrade only through the exclusive maintenance transition. Reducing
limits never discards existing history to make it fit.''')
    additions = {
        'docs/reference/standalone-node.md': '''\n## Audit-journal maintenance\n\nFor the durable `dataDirectory/audit` owner, use the explicit Linux\n[stopped-node lifecycle](../operations/audit-journal-lifecycle.md). It preserves\nacknowledged bytes, global sequences and predecessor links while bounding local\narchive custody. Stop the node and its restart supervision; invoke the native\nCLI as the same effective UID with `--local-operator`. RPC credentials do not\nauthorize this offline path. A pending critical attempt or incomplete transition\nblocks a new maintenance plan. Retain original operation identities for recovery.\n\nThe node must restart with durable audit still enabled. Neither rollover nor an\narchive receipt extends signed evidence freshness, changes a retained mutation\noutcome, or grants replay authority. See the guide for full-capacity recovery,\nverified transfer, upgrade behavior and the remaining qualification boundary.\n''',
        'docs/operations/static-route-sets.md': '''\n## Audit capacity and stopped-node recovery\n\nPlan renewal before durable audit capacity becomes critical. Evidence renewal\nplus separate GET and HEAD mutations require at least six critical audit records;\ndiagnostics, competitors and byte/queue/metadata reservations require additional\nheadroom. The [audit-journal lifecycle guide](audit-journal-lifecycle.md) provides\nthe bounded advisory calculator and explicit stopped-node rollover, verification\nand transfer commands. A read-only snapshot is not a future reservation.\n\nRetain the original route journal across maintenance. A confirmed GET and a known\nrejected HEAD remain different facts; a pending HEAD with no matching retained\nreceipt remains uncertain. Audit maintenance does not authorize replay or change\nthose dispositions. Inspect the original operation, current authorization,\nevidence eligibility and route generations before an explicit continuation or\nnew plan. A fully rejected mutation must not be relabelled as committed, and a\nlost response must not be relabelled as rejected. Stopped-node maintenance incurs\ndowntime and does not disable evidence-expiry denial.\n''',
    }
    for name, addition in additions.items():
        path = Path(name)
        text = path.read_text()
        if addition.strip() not in text:
            path.write_text(text.rstrip() + '\n' + addition)
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
