#!/usr/bin/env python3
"""Pinned documentation-only edits and bounded, non-mutating example checks."""
from pathlib import Path
import json
import re
import subprocess
import sys
import tempfile

ROOT = Path.cwd()
HEAD = '62f075e2512bcdbbf51669d122656e5744547210'
GUIDE = 'docs/operations/static-evidence-renewal.md'
CHANGED = [GUIDE, 'docs/operations/audit-journal-lifecycle.md',
    'docs/operations/static-route-sets.md', 'docs/operations/static-release-workflow.md',
    'docs/phase-2-audit.md', 'docs/reference/operator-cli.md',
    'docs/reference/standalone-node.md', 'docs/how-to/deliver-a-website.md',
    'website/lib/navigation.mjs']

def replace(name, old, new):
    path = ROOT / name
    text = path.read_text()
    assert text.count(old) == 1, (name, 'anchor-count', text.count(old))
    path.write_text(text.replace(old, new), newline='\n')

def edit(guide):
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == HEAD
    assert not subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip()
    assert not (ROOT / GUIDE).exists()
    (ROOT / GUIDE).write_bytes(Path(guide).read_bytes())
    replace('docs/phase-2-audit.md',
        'Retention rejects new records when full. There is no hidden pruning, overwrite,\nrotation or remote exporter. Operators must provision finite capacity; reducing\nlimits cannot discard existing history to make it fit.',
        'Retention rejects new records when the active epoch is full. There is no\nautomatic pruning, overwrite, rotation or remote exporter. Current development\nadds an explicit [stopped-node audit-journal lifecycle](operations/audit-journal-lifecycle.md):\nthe filesystem owner seals an epoch, preserves its original bytes in finite\nlocal custody, and opens a linked successor without resetting global sequences.\nLocal custody is limited to four epochs and 1 GiB of record bytes; explicit\nverified transfer of the oldest archive releases local capacity only after its\ndurable external copy is verified. These commands are not in the released\nalpha.4/alpha.5 binaries. Reducing configured limits never discards history.\n\nThe table below bounds the active epoch, not total archived history. Rollover\nrequires the whole node and its restart supervision to be stopped, exclusive\neffective-UID ownership, and sufficient filesystem space. It needs no ordinary\naudit-record reservation, but neither renews publication evidence nor permits\nreplay of an unknown operation. Follow the\n[static-site renewal runbook](operations/static-evidence-renewal.md) for headroom\nchecks, evidence renewal, GET/HEAD reconciliation and interruption recovery.')
    replace('docs/phase-2-audit.md', '| Retained records | 4,096 | 16,384 |',
        '| Active-epoch retained records | 4,096 | 16,384 |')
    replace('docs/phase-2-audit.md', '| Retained record bytes | 64 MiB | 256 MiB |',
        '| Active-epoch retained record bytes | 64 MiB | 256 MiB |')
    replace('docs/phase-2-audit.md',
        'pagination sequence. Filters select event kind, actor and an inclusive time range',
        'pagination sequence. A cursor from before rollover cannot continue silently\ninto the successor epoch; query the explicitly selected sealed archive for that\nhistory. A new active epoch can have a retained floor greater than one.\nFilters select event kind, actor and an inclusive time range')
    replace('docs/operations/audit-journal-lifecycle.md',
        '# Stopped-node audit-journal lifecycle\n',
        '# Stopped-node audit-journal lifecycle\n\n**Version boundary:** this guide describes the current-development lifecycle\ncommands, not the released alpha.4/alpha.5 binaries. Use a reviewed matching\nnode and CLI that include them. For the complete live renewal and maintenance\nsequence, use [renew static-site evidence](static-evidence-renewal.md).\n')
    replace('docs/operations/audit-journal-lifecycle.md',
        'For an explicitly retained usage snapshot, the bounded\n`tools/static-release/audit-headroom.mjs` calculator also accepts the actual audit\nconfiguration and produces JSON or human-readable output:\n\n```sh\nnode tools/static-release/audit-headroom.mjs \\\n  --usage /private/operator/audit-usage.json \\\n  --audit-config /private/operator/audit-config.json \\\n  --route-pairs 1 --diagnostic-records 2 --competing-operations 1 \\\n  --warning-percent 80 --cadence-minutes 10 --output human\n```\n\nBoth input files must be private ordinary files. The configuration file contains\nthe node\'s audit object, for example `{"mode":"durable","records":4096}`. Usage\nis either the native CLI result containing `data.nodeUsage`, or that node-scoped\nusage object itself. The calculator refuses missing/unavailable counters rather\nthan treating them as zero. It does not establish snapshot freshness, filesystem\nfree space or future admission, and does not create a reservation.',
        'For a retained observation, capture authenticated inventory while the node is\nrunning, before entering the stopped-owner workflow. Use a new output filename\nin an already private operator directory:\n\n```sh\numask 077\nlatent --config /srv/latent-operator/operator.json --profile operator \\\n  --output json node get example-node > /srv/latent-operator/audit-inventory-001.json\nnode tools/static-release/audit-headroom.mjs \\\n  --inventory /srv/latent-operator/audit-inventory-001.json --node example-node \\\n  --route-pairs 1 --diagnostic-records 2 --competing-operations 1 \\\n  --warning-percent 80 --cadence-minutes 10 --output human\n```\n\nThe private ordinary input file must contain the successful native CLI node\ninventory envelope. The calculator reads the single fixed `audit-journal` row\nwith profile `audit-capacity-v1`, including the actual configured ceilings and\navailable counters. Missing, duplicate or unavailable rows are not zero usage.\nThis retained sample does not establish current freshness, filesystem free space\nor future admission, and it creates no reservation.\n\nThe alternative `--usage FILE --audit-config FILE` form requires a successful\n`latent.cli.result.v1` envelope with `outcomeKnown: true` and `data.nodeUsage`,\nplus the actual audit configuration object. A bare usage object is not accepted.\nDo not mix that form with `--inventory`/`--node`, or invent counters for an older\nnode. Prefer the inventory form above for this development implementation.')
    replace('docs/operations/audit-journal-lifecycle.md',
        'One renewal plus GET and HEAD mutations needs at least six critical records.',
        'One renewal plus two actual GET and HEAD mutations needs at least six critical\nrecords. Renewing an unchanged publication does not itself require rewriting\nmatching routes; the maintained route helper observes those without mutation.')
    replace('docs/operations/audit-journal-lifecycle.md',
        'umask 077\nJOURNAL=/srv/latent-data/audit\nARCHIVES=/srv/latent-audit-archives\nOPS=/srv/latent-operator\ninstall -d -m 700 "$OPS"',
        'set -e\nset -C\numask 077\nJOURNAL=/srv/latent-data/audit\nARCHIVES=/srv/latent-audit-archives\nOPS=/srv/latent-operator/maintenance-001\nmkdir -m 700 "$OPS"')
    replace('docs/operations/audit-journal-lifecycle.md',
        'Do not stop only a CLI while leaving the node running.',
        'Do not stop only a CLI while leaving the node running. The parent of `OPS`\nmust already be private and owned by the service UID. Use a new maintenance\ndirectory for a new operation: the example refuses an existing directory and\noutput file. Do not rerun setup after interruption or replace retained selectors.')
    replace('docs/operations/audit-journal-lifecycle.md',
        'those same inputs; do not generate another identity as a retry mechanism.',
        'those same inputs; do not generate another identity as a retry mechanism.\nRestore `EPOCH` from `rollover.epoch` and `OPERATION` from `rollover.operation`,\nkeep the original journal/archive paths, and save each recovery response in a\nnew file. The stopped `status` envelope exposes `data.journalId`; retain it for\nlater custody inspection. The rollover result uses `data.receipt.epoch`,\n`data.receipt.nextSequence` and `data.receipt.archiveSeal`, with\n`data.durability: confirmed`. Verify the old epoch, not the new empty one.')
    replace('docs/operations/audit-journal-lifecycle.md',
        'selectors for recovery. This command durably copies and verifies the destination,',
        'selectors for recovery. Epochs and operation IDs are 32 lowercase hexadecimal\ncharacters; the expected seal is the 64-character lowercase hexadecimal\n`sealDigest` from custody inspection, without a `sha256:` prefix. This command\ndurably copies and verifies the destination,')
    replace('docs/operations/static-route-sets.md',
        'after interruption. You need Node.js 22 or newer, the released `latent` binary,\nan operator profile for your tenant, and an already published static site.',
        'after interruption. You need Node.js 22 or newer, a matching `latent` binary\nand helper checkout, an operator profile for your tenant, and an already\npublished static site. Audit-aware preflight below requires the current-development\nnode inventory and helper; it is not available in the released alpha.4/alpha.5\nbinaries. Missing observations must not be treated as spare capacity. Follow\n[renew static-site evidence](static-evidence-renewal.md) for the complete renewal,\nstopped-node maintenance and recovery sequence.')
    replace('docs/operations/static-route-sets.md',
        'tool manages GET/HEAD; it does **not** issue or atomically combine evidence renewal.',
        'tool manages GET/HEAD; it does **not** issue or atomically combine evidence renewal.\nRenewal of the same package retains its publication ID, so already matching\nGET/HEAD manifests do not need a write solely because evidence was renewed.\nThe helper observes those routes without dispatch and still checks current\neligibility. Its conservative preflight budgets the full renewal/route cycle.')
    replace('docs/operations/static-release-workflow.md',
        '## Renew evidence and recover\n',
        '## Renew evidence and recover\n\nFor the current-development audit-aware procedure, follow\n[renew static-site evidence without losing audit history](static-evidence-renewal.md).\nIt adds live capacity preflight, stopped-node rollover and partial GET/HEAD\nrecovery to the renewal commands below. Those maintenance and inventory features\nare not in the released alpha.4/alpha.5 binaries; use matching tools and node.\nEvidence renewal and audit rollover solve different problems: rollover preserves\nhistory and frees active-epoch capacity, but does not extend evidence validity.\n')
    replace('docs/operations/static-release-workflow.md',
        'authority. Resolve generation conflicts from fresh state. After a node restart,\nhonor its persisted restart clock floor and verify readiness before mutations.',
        'authority. Retain the original request, response and independent audit\nacknowledgement. A lost response, unknown receipt or unconfirmed durability is not\na known rejection: stop automatic writes and look up the original operation\nbefore considering another decision. Resolve a confirmed generation conflict\nfrom fresh state without changing an old operation\'s preconditions. After a\nnode restart, honor its persisted restart clock floor and verify readiness\nbefore mutations. Renewal does not require rewriting unchanged GET/HEAD routes;\nthe route-set helper checks them without sending redundant apply requests.')
    replace('docs/reference/operator-cli.md',
        'connect once and send one generated gRPC request. Local paths never name the\nnode\'s catalogs, and the CLI does not execute components locally.',
        'connect once and send one generated gRPC request. In RPC commands, local paths\nnever name the node\'s catalogs. The explicit local audit-maintenance commands\nbelow instead require stopped-owner filesystem access. The CLI does not execute\ncomponents locally.')
    replace('docs/reference/operator-cli.md',
        '## Credentials and limits\n',
        '## Local audit maintenance and archive commands\n\nThese **current-development** Linux commands are not in the released alpha.4 or\nalpha.5 CLI. They operate through effective-UID ownership of private filesystem\npaths, not through tenant RPC credentials. Stop the whole node and its restart\nsupervisor before journal maintenance. Every invocation requires\n`--local-operator` and accepts `--deadline-seconds 1..120` (default 60). The\ndeadline is cooperative; a blocked physical I/O owner is not reported as released.\n\n| Command, in addition to `--local-operator` | Behavior |\n| --- | --- |\n| `audit maintenance status --journal DIR` | Reads verified stopped-epoch identity, sequence, retained counts and pending attempts; does not reserve future capacity. |\n| `audit maintenance rollover --journal DIR --archives DIR --expected-epoch EPOCH --operation-id OP` | Seals an epoch and opens its linked successor, or resumes the original interrupted operation. |\n| `audit maintenance custody --archives DIR --journal-id ID` | Verifies the finite local archive suffix and labels external history availability separately. |\n| `audit maintenance transfer --journal DIR --archives DIR --destination DIR --epoch EPOCH --expected-seal HEX --operation-id OP` | Copies and durably verifies the oldest local archive before releasing its local capacity. |\n| `audit archive verify --archive DIR --epoch EPOCH` | Verifies one selected sealed epoch, not all historical observation coverage. |\n| `audit archive query --archive DIR --epoch EPOCH --scope tenant --tenant TENANT` | Reads one bounded offline tenant-scope page as the filesystem owner. For node scope use `--scope node` and omit `--tenant`. |\n\nMaintenance rejects `--tenant`. Archive verification also rejects it; archive\nquery requires it only for tenant scope. These commands reject `--config`,\n`--profile`, `--endpoint`, `--connect-timeout-ms`, `--rpc-timeout-ms` and\n`--phase4`; they do not connect to a node. Offline scope filters grant no RPC\nauthority. Live `audit query` retains its existing authenticated authorization.\n\nJournal/epoch/maintenance-operation identities use 32 lowercase hexadecimal\ncharacters. `--expected-seal` is exactly 64 lowercase hexadecimal characters,\nwithout a `sha256:` prefix. Retain original identities and paths before mutation;\nresume interrupted maintenance with those same selectors, never a new retry ID.\nArchive query additionally accepts `--actor`, `--from-unix-millis`,\n`--to-unix-millis`, `--page-token`, `--page-size 1..128` (default 128), and\n`--maximum-bytes 32768..262144` (default 65536). Tokens stay within one epoch and\nscope; there is no automatic pagination or cursor restart.\n\nFollow the [audit-journal lifecycle](../operations/audit-journal-lifecycle.md)\nfor exclusive ownership, finite custody, version-2 mode markers and interruption\nrecovery. The [static-site renewal runbook](../operations/static-evidence-renewal.md)\nconnects maintenance to live evidence renewal without conflating their authority.\n\n## Credentials and limits\n')
    replace('docs/reference/standalone-node.md',
        'downgrade. Audit configuration is unsupported on other node platforms.',
        'downgrade. Audit configuration is unsupported on other node platforms.\n\nCurrent development exposes one fixed `audit-journal` inventory topology row\nwith profile `audit-capacity-v1`, configured ceilings and sampled owner counters.\nConfigured capacity is not a live-worker measurement: unavailable live counts\nremain unknown. Use the [renewal capacity preflight](../operations/static-route-sets.md#preflight-audit-capacity-before-renewal)\nrather than treating missing observations as zero.\n\nThe [explicit stopped-node lifecycle](../operations/audit-journal-lifecycle.md)\nseals a full epoch without an ordinary record reservation and preserves its\nhistory in finite custody. It requires the actual owning service UID, exclusive\naccess and real filesystem space; it never moves a live journal or disables\naudit. These inventory/maintenance features are not in released alpha.4/alpha.5.\nThe configured record and record-byte ceilings bound the active epoch, not all\narchived history. See the [static evidence renewal runbook](../operations/static-evidence-renewal.md)\nfor scheduling, recovery and the separate publication-freshness checks.')
    replace('docs/how-to/deliver-a-website.md',
        'route-set journal. Renew expiring evidence before it prevents serving. Plan\n[publication capacity]',
        'route-set journal. Renew expiring evidence before it prevents serving. For\ncurrent-development nodes, follow the [evidence renewal and audit maintenance\nrunbook](../operations/static-evidence-renewal.md): check audit headroom, retain\nthe original renewal operation, reconcile GET/HEAD, and use stopped-node rollover\nwhen required. Its new preflight and maintenance commands require a matching\nnode/CLI/helper; they are not part of the released alpha.5 walkthrough above.\nRollover does not extend evidence freshness, and renewing unchanged content does\nnot require rewriting already matching routes. Plan\n[publication capacity]')
    replace('website/lib/navigation.mjs',
        "'how-to/static-site-and-api', 'operations/static-release-workflow', 'operations/static-route-sets',",
        "'how-to/static-site-and-api', 'operations/static-release-workflow', 'operations/static-evidence-renewal',\n      'operations/static-route-sets', 'operations/audit-journal-lifecycle',")
    names = subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()
    untracked = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], text=True).splitlines()
    assert set(names + untracked) == set(CHANGED), (names, untracked)
    subprocess.run(['git', 'diff', '--check'], check=True)
    print('Prepared nine documentation/navigation files; no runtime or historical release edits.')

def unfence(text):
    return re.sub(r'^```[^\n]*\n.*?^```\s*$', '', text, flags=re.M | re.S)

def verify():
    names = subprocess.check_output(['git', 'diff', '--name-only', HEAD, 'HEAD'], text=True).splitlines()
    assert set(names) == set(CHANGED), names
    assert not any(name.startswith('website/versioned_') for name in names)
    total_links = total_shell = 0
    for name in CHANGED:
        if not name.endswith('.md'): continue
        path = ROOT / name
        text = path.read_text()
        assert text.startswith('# ') and text.endswith('\n')
        assert not re.search(r'^(<<<<<<< |=======|>>>>>>> )', text, re.M)
        assert len(re.findall(r'^```', text, re.M)) % 2 == 0
        for target in re.findall(r'\[[^\]]+\]\(([^\s)]+)\)', unfence(text)):
            if re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target) or target.startswith('/'): continue
            selected, _, anchor = target.partition('#')
            dest = (path.parent / selected).resolve() if selected else path.resolve()
            assert dest.is_relative_to(ROOT) and dest.exists(), (name, target)
            total_links += 1
            if name == GUIDE and anchor and dest.suffix == '.md':
                headings = re.findall(r'^#{1,6}\s+(.+?)\s*$', unfence(dest.read_text()), re.M)
                slugs = {re.sub(r'[^\w\- ]', '', h.lower()).replace(' ', '-') for h in headings}
                assert anchor in slugs, (name, target, 'missing-anchor')
        if name in (GUIDE, 'docs/operations/audit-journal-lifecycle.md'):
            for code in re.findall(r'^```(?:bash|sh)\n(.*?)^```', text, re.M | re.S):
                subprocess.run(['bash', '-n'], input=code, text=True, check=True)
                total_shell += 1
    guide = (ROOT / GUIDE).read_text()
    embedded = re.search(r"<<'PY'\n(.*?)\nPY\n", guide, re.S).group(1)
    compile(embedded, '<renewal-intent-example>', 'exec')
    publication = 'publication:sha256:' + '1' * 64
    package = 'sha256:' + '2' * 64
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        index = root / 'index.json'; index.write_text('{}\n')
        observation = {'schemaVersion': 'latent.cli.result.v1', 'category': 'success',
                       'outcomeKnown': True, 'data': {'record': {'publication': {'id': publication}, 'generation': '7'}}}
        (root / 'publication-before.json').write_text(json.dumps(observation))
        args = [sys.executable, '-c', embedded, str(root), '/private/operator.json', 'operator',
                'example-node', publication, package, str(index)]
        subprocess.run(args, check=True)
        note = root / 'renewal-intent.json'
        original = note.read_bytes()
        value = json.loads(original)
        assert value['expectedGeneration'] == '7' and value['publication'] == publication
        assert value['packageDigest'] == package and re.fullmatch(r'renew-[0-9a-f]{32}', value['operationId'])
        assert subprocess.run(args, capture_output=True).returncode != 0 and note.read_bytes() == original
        note.unlink()
        for changes in ({'category': 'platform-failure'}, {'outcomeKnown': False},
                        {'data': {'record': {'publication': {'id': publication}, 'generation': '0'}}},
                        {'data': {'record': {'publication': {'id': publication}, 'generation': str(2**64-1)}}},
                        {'data': {'record': {'publication': {'id': 'publication:sha256:' + '3'*64}, 'generation': '7'}}}):
            bad = dict(observation); bad.update(changes)
            (root / 'publication-before.json').write_text(json.dumps(bad))
            assert subprocess.run(args, capture_output=True).returncode != 0
            assert not note.exists()
    subprocess.run(['git', 'diff', '--check', HEAD, 'HEAD'], check=True)
    print(f'DOCS_VERIFIED files={len(CHANGED)} relative_links={total_links} shell_blocks={total_shell} intent_controls=7')
    print('Only synthetic local recovery-note examples executed; no live renewal/maintenance or signing performed.')

if __name__ == '__main__':
    if sys.argv[1] == 'edit': edit(sys.argv[2])
    elif sys.argv[1] == 'verify': verify()
    else: raise SystemExit('unknown mode')
