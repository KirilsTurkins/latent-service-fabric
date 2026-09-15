"""Closed source capture and the actual hydration wrapper's rejection boundary."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from tools.angular_build.inputs import capture, decode, validate
from tools.angular_build.package import check_html, unique_entries
from tools.build_process import run_bounded
from tools.build_snapshot import SnapshotError, canonical

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'examples/angular-application'


def config():
    return json.loads((FIXTURE / 'angular-build.json').read_bytes())


class AngularBuildInputTests(unittest.TestCase):
    def test_identical_installation_aliases_deduplicate_without_hiding_conflicting_attribution(self):
        row = {'kind': 'build-dependency', 'name': 'typescript', 'version': '6.0.3',
               'source': 'urn:lsf:registry:npm/typescript', 'digest': 'a'}
        self.assertEqual(unique_entries([row, dict(row)]), [row])
        with self.assertRaises(SnapshotError):
            unique_entries([row, {**row, 'digest': 'b'}])

    def test_closed_build_schema_accepts_the_real_application_and_rejects_hooks(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((ROOT / 'schemas/angular-build.schema.json').read_bytes())
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(config())
        for field in (*config(), 'scripts'):
            value = config()
            if field == 'scripts': value[field] = {'build': 'unapproved'}
            else: del value[field]
            self.assertFalse(validator.is_valid(value), field)

    def test_profile_rejects_commands_native_modules_cross_area_assets_and_excessive_inputs(self):
        validate(config())
        mutations = [lambda c: c.update(scripts={'build': 'run-an-application-hook'}),
                     lambda c: c.update(profile='node-process-v1'),
                     lambda c: c.update(formatVersion=True),
                     lambda c: c.update(serverEntry='../server.ts'),
                     lambda c: c.update(clientEntry='server/main.ts'),
                     lambda c: c['sources'].append('shared/addon.node'),
                     lambda c: c['sources'].append('shared/../secret.ts'),
                     lambda c: c['sources'].append('SHARED/app.ts'),
                     lambda c: c['assets'][0].update(source='server/private.html'),
                     lambda c: c['assets'][0].update(path='/_lsf/assets/other/offline.html'),
                     lambda c: c.update(routes=c['routes'] * 65),
                     lambda c: c['routes'][0].update(asset='/offline.html'),
                     lambda c: c['routes'][1].update(asset='/missing.html')]
        for mutate in mutations:
            value = config(); mutate(value)
            with self.subTest(value=value), self.assertRaises(SnapshotError):
                validate(value)

    def test_capture_excludes_unlisted_files_and_uses_fixed_destination_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'
            shutil.copytree(FIXTURE, source)
            (source / '.env').write_text('SECRET=not-a-build-input')
            (source / 'package.json').write_text('{"scripts":{"build":"unapproved"}}')
            selected, inventory = capture(source, 'angular-build.json', root / 'captured')
            self.assertEqual(selected, config())
            self.assertFalse((root / 'captured/.env').exists())
            self.assertFalse((root / 'captured/package.json').exists())
            self.assertNotIn(b'SECRET', inventory)
            before = (root / 'captured/shared/app.ts').read_bytes()
            (source / 'shared/app.ts').write_text('later input edit')
            self.assertEqual((root / 'captured/shared/app.ts').read_bytes(), before)
            self.assertEqual(len(json.loads(inventory)), 5)

    def test_capture_rejects_a_selected_link_before_compilers_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'
            shutil.copytree(FIXTURE, source)
            victim = source / 'shared/app.ts'
            victim.unlink()
            outside = root / 'outside.ts'; outside.write_text('outside')
            try:
                victim.symlink_to(outside)
            except OSError:
                if os.name == 'nt':
                    self.skipTest('Windows user cannot create symlinks; Linux gate is required')
                raise
            with self.assertRaises(SnapshotError):
                capture(source, 'angular-build.json', root / 'captured')

    def test_selected_file_limit_duplicate_json_and_prerender_hydration_are_bounded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'input'; shutil.copytree(FIXTURE, source)
            (source / 'shared/app.ts').write_bytes(b'x' * (1024 * 1024 + 1))
            with self.assertRaises(SnapshotError):
                capture(source, 'angular-build.json', root / 'captured')
        with self.assertRaises(SnapshotError):
            decode(b'{"formatVersion":1,"formatVersion":1}')
        check_html(b'<script type="application/json">{"hello":"world"}</script>')
        for html in (b'<script type="application/json">' + canonical('x' * 32769) + b'</script>',
                     b'<script type="application/json">{}', b'x' * 131073,
                     b'<script type="application/json">{broken}</script>'):
            with self.subTest(size=len(html)), self.assertRaises(SnapshotError):
                check_html(html)


class AngularHydrationWrapperTests(unittest.TestCase):
    def test_actual_typescript_preflight_rejects_server_templates_and_outside_reference_directives(self):
        node = shutil.which('node')
        toolchain = Path(os.environ.get('LSF_ANGULAR_TOOLCHAIN', ROOT / 'examples/renderer-profile')).resolve()
        if not node or not (toolchain / 'node_modules/typescript').is_dir():
            self.skipTest('the renderer gate provisions the exact Node/TypeScript toolchain')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'guard.mjs').write_bytes((ROOT / 'tools/angular_build/guard.mjs').read_bytes())
            (root / 'test.mjs').write_text('''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import {checkSource} from './guard.mjs';
const ts=createRequire(path.join(process.argv[2],'package.json'))('typescript');
const names=new Set(['client/main.ts','shared/app.ts','shared/app.html','server/private.html','server/private.ts']);
checkSource(ts,'shared/app.ts','const metadata={templateUrl:"./app.html"}',names);
checkSource(ts,'client/main.ts','import {App} from "../shared/app.js";',names);
for (const source of [
 'const metadata={templateUrl:"../server/private.html"}',
 'const metadata={styleUrls:["../server/private.html"]}',
 'import {secret} from "../server/private.js";',
 '/// <reference path="../../../private.ts" />',
 '/// <reference types="node" />',
 '/// <reference lib="esnext" />',
 'import("./optional.js")', 'import native from "node:fs";',
 'const metadata={templateUrl:runtimePath}', 'setInterval(()=>{},1)',
]) assert.throws(()=>checkSource(ts,'shared/app.ts',source,names),source);
console.log('source separation and reference boundaries passed');
''')
            result = run_bounded([node, str(root / 'test.mjs'), str(toolchain)], root, dict(os.environ), 30, 8192)
            self.assertIn(b'source separation and reference boundaries passed', result.stdout)

    def test_real_wrapper_enforces_aggregate_data_complete_tags_and_closed_attributes(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node required for executable JavaScript wrapper checks')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'package.json').write_text('{"type":"module"}')
            (root / 'application.js').write_bytes((ROOT / 'tools/angular_build/application.js').read_bytes())
            (root / 'assets.js').write_text('export const clientAsset="/client.immutable.js";')
            (root / 'server.js').write_text('export async function render(request){return {html:request.html,status:200,headers:[]}}')
            (root / 'test.mjs').write_text('''
import assert from 'node:assert/strict';
import {render} from './application.js';
const script=data=>'<script type="application/json">'+JSON.stringify(data)+'</script>';
const good=await render({html:'__LSF_CLIENT_ASSET__'+script('Alice <private>')},{});
assert.ok(good.html.startsWith('/client.immutable.js'));
await render({html:script('x'.repeat(32766))},{});
for(const html of [script('x'.repeat(32767)), script('x'.repeat(16383)).repeat(2),
 '<script TYPE=application/json>'+JSON.stringify('x'.repeat(32767))+'</script>',
 '<script type="&#x61;pplication/json">{}</script>',
 '<script type="application/json">{}', '<script type="application/json">{broken}</script>',
 '<script></script>'.repeat(65), 'x'.repeat(131073)]) {
 await assert.rejects(render({html},{}));
}
console.log('hydration wrapper boundaries passed');
''')
            result = run_bounded([node, str(root / 'test.mjs')], root, dict(os.environ), 30, 8192)
            self.assertIn(b'hydration wrapper boundaries passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
