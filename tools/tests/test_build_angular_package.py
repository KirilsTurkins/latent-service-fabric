"""Closed source capture and the actual hydration wrapper's rejection boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from tools.angular_build.inputs import capture, decode, validate
from tools.angular_build.package import check_html, unique_entries
from tools.build_process import BuildProcessError, run_bounded
from tools.build_snapshot import SnapshotError, canonical

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'examples/angular-application'


def config():
    return json.loads((FIXTURE / 'angular-build.json').read_bytes())


def hydration_cases():
    """One acceptance corpus for the actual runtime wrapper and supplied HTML."""
    def script(attributes, data):
        return '<script ' + attributes + '>' + data + '</script>'
    exact = json.dumps('x' * 32766)
    over = json.dumps({'value': 'x' * 40000}, separators=(',', ':'))
    assert len(exact.encode()) == 32768 and len(over.encode()) == 40012
    cases = []
    attributes = ['type="application/json"', 'TYPE=APPLICATION/JSON',
                  "type=' \tAPPLICATION/JSON\r\n\f '",
                  'id="ng-state" type="text/plain"', 'id="custom-app-state" type="text/javascript"',
                  'ID=ng-state', 'id="ng-state" type=""']
    attributes += ['type="' + space + 'application/json' + space + '"' for space in ' \t\n\r\f']
    for index, attrs in enumerate(attributes):
        cases.extend([
            {'name': f'exact-{index}', 'html': script(attrs, exact), 'accept': True},
            {'name': f'overflow-{index}', 'html': script(attrs, over), 'accept': False, 'reason': 'limit'},
            {'name': f'malformed-{index}', 'html': script(attrs, '{broken}'), 'accept': False},
        ])
    half = json.dumps('x' * 16382)
    aggregate = script('type=" application/json "', half) + script('id=another-state type=text/plain', half)
    cases.extend([
        {'name': 'aggregate-exact', 'html': aggregate, 'accept': True},
        {'name': 'aggregate-overflow', 'html': aggregate + script('id=third-state', '{}'),
         'accept': False, 'reason': 'limit'},
        {'name': 'utf8-exact', 'html': script('id=unicode-state', json.dumps('é' * 16383, ensure_ascii=False)), 'accept': True},
        {'name': 'utf8-overflow', 'html': script('id=unicode-state', json.dumps('é' * 16384, ensure_ascii=False)),
         'accept': False, 'reason': 'limit'},
        {'name': 'ordinary-script', 'html': script('type="text/plain"', 'not JSON'), 'accept': True},
        {'name': 'attribute-name-lookalikes', 'html': script('data-type="application/json" data-id="ng-state"', 'not JSON'), 'accept': True},
        {'name': 'quoted-attribute-lookalike', 'html': script('title="type=application/json id=ng-state >"', 'not JSON'), 'accept': True},
        {'name': 'duplicate-type', 'html': script('type="text/plain" TYPE="application/json"', '{}'), 'accept': False},
        {'name': 'duplicate-id', 'html': script('id="other" ID="ng-state"', '{}'), 'accept': False},
        {'name': 'encoded-type', 'html': script('type="&#x61;pplication/json"', '{}'), 'accept': False},
        {'name': 'encoded-state-id', 'html': script('id="ng&#45;state" type=text/plain', '{}'), 'accept': False},
        {'name': 'incomplete-state', 'html': '<script id=ng-state>{}', 'accept': False},
        {'name': 'incomplete-other-script', 'html': '<script type=text/plain>text', 'accept': False},
        {'name': 'malformed-attributes', 'html': script('id="ng-state"type="application/json"', '{}'), 'accept': False},
        {'name': 'script-count-exact', 'html': script('', '') * 64, 'accept': True},
        {'name': 'script-count-overflow', 'html': script('', '') * 65, 'accept': False},
        {'name': 'html-overflow', 'html': 'x' * 131073, 'accept': False},
    ])
    return cases


class AngularBuildInputTests(unittest.TestCase):
    def test_supplied_html_matches_runtime_transfer_recognition_and_recovers(self):
        recovery = b'<script id="recovered-state" type="text/plain">{"name":"Bob"}</script>'
        for case in hydration_cases():
            with self.subTest(case=case['name']):
                data = case['html'].encode('utf-8')
                if case['accept']:
                    check_html(data)
                else:
                    reason = 'hydration byte limit' if case.get('reason') == 'limit' else ''
                    with self.assertRaisesRegex(SnapshotError, reason):
                        check_html(data)
                check_html(recovery)

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
            (root / 'test.mjs').write_text(r'''
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import path from 'node:path';
import {checkSource} from './guard.mjs';
const ts=createRequire(path.join(process.argv[2],'package.json'))('typescript');
const names=new Set(['client/main.ts','shared/app.ts','shared/app.html','shared/app.css','shared/tmp/outside.html','server/private.html','server/private.css','server/private.ts']);
checkSource(ts,'shared/app.ts','const metadata={templateUrl:"./app.html"}',names);
checkSource(ts,'client/main.ts','import {App} from "../shared/app.js";',names);
checkSource(ts,'shared/app.ts','const metadata={styleUrl:"./app.css",styleUrls:["./app.css"]}',names);
// Unrelated shorthand is still allowed; resource identifiers may be declared.
checkSource(ts,'shared/app.ts','const value=1,templateUrl="unused"; const metadata={value}',names);
for (const key of ['templateUrl','styleUrl','styleUrls']) {
 for (const target of ['../server/private.html','/tmp/outside.html','./app.html']) {
  const initializer=JSON.stringify(key==='styleUrls'?[target]:target);
  const source=`import {Component} from '@angular/core'; const ${key}=${initializer}; @Component({${key}}) class App {}`;
  assert.throws(()=>checkSource(ts,'shared/app.ts',source,names), /angular-nonliteral-resource/, source);
 }
}
for (const source of [
 'const metadata={"template\\u0055rl":"../server/private.html"}',
 'const metadata={["templateUrl"]:"../server/private.html"}',
 'const key="templateUrl"; const metadata={[key]:"../server/private.html"}',
 'const metadata={get templateUrl(){return "../server/private.html"}}',
 'const metadata={templateUrl:"/tmp/outside.html"}',
 'const metadata={templateUrl:"C:/tmp/outside.html"}',
 'const metadata={templateUrl:"file:../shared/app.html"}',
]) assert.throws(()=>checkSource(ts,'shared/app.ts',source,names), source);
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

    def test_production_adapter_rejects_shorthand_resources_before_package_output(self):
        from tools.angular_build import build
        node = shutil.which('node')
        toolchain = Path(os.environ.get('LSF_ANGULAR_TOOLCHAIN', ROOT / 'examples/renderer-profile')).resolve()
        if not node or not (toolchain / 'node_modules/typescript').is_dir():
            self.skipTest('the renderer gate provisions the exact Node/TypeScript toolchain')
        script = ROOT / 'tools/angular_build/bundle.mjs'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Prove the exact production configure command works, so a wrong
            # runtime or missing compiler cannot masquerade as resource rejection.
            selected, _ = capture(FIXTURE, 'angular-build.json', root / 'good')
            run_bounded([node, str(script), str(toolchain), str(root / 'good'), str(root / 'good-bundle'), 'configure'],
                        root / 'good', dict(os.environ), 30, 8192)
            self.assertTrue((root / 'good-bundle/tsconfig.json').is_file())
            for area in ('shared', 'client'):
                for key in ('templateUrl', 'styleUrl', 'styleUrls'):
                    for location in ('server', 'outside'):
                        with self.subTest(area=area, key=key, location=location):
                            case = root / f'{area}-{key}-{location}'
                            case.mkdir()
                            source = case / 'input'
                            shutil.copytree(FIXTURE, source)
                            value = config()
                            for suffix in ('html', 'css'):
                                name = 'server/private.' + suffix
                                marker = 'LSF_SERVER_RESOURCE_MUST_NOT_REACH_BROWSER'
                                resource = '<p>' + marker + '</p>' if suffix == 'html' else '.private{--secret:"' + marker + '"}'
                                (source / name).write_text(resource, encoding='utf-8')
                                value['sources'].append(name)
                            suffix = 'html' if key == 'templateUrl' else 'css'
                            outside = case / ('outside.' + suffix)
                            marker = 'LSF_UNCAPTURED_RESOURCE_MUST_NOT_BE_READ'
                            resource = '<p>' + marker + '</p>' if suffix == 'html' else '.outside{--secret:"' + marker + '"}'
                            outside.write_text(resource, encoding='utf-8')
                            target = '../server/private.' + suffix if location == 'server' else outside.as_posix()
                            initializer = json.dumps([target] if key == 'styleUrls' else target)
                            name = 'shared/app.ts' if area == 'shared' else 'client/main.ts'
                            inline = '' if key == 'templateUrl' else 'template: "<p>public</p>", '
                            (source / name).write_text(
                                "import {Component} from '@angular/core';\n"
                                f'const {key} = {initializer};\n'
                                '@Component({selector:"lsf-demo", standalone:true, ' + inline + key + '})\n'
                                'export class App {}\n', encoding='utf-8')
                            (source / 'angular-build.json').write_bytes(canonical(value))
                            selected, inventory = capture(source, 'angular-build.json', case / 'captured')
                            self.assertIn(b'LSF_SERVER_RESOURCE', (case / 'captured/server/private.html').read_bytes())
                            self.assertNotIn(b'outside.' + suffix.encode(), inventory)
                            self.assertTrue(outside.is_file())
                            self.assertFalse((case / 'captured' / outside.name).exists())
                            calls = []
                            def call(command, cwd, **options):
                                calls.append(command)
                                # Exercise assemble -> compile_application -> the
                                # real bounded configure process. ngc, esbuild,
                                # componentization and packaging must not start.
                                self.assertEqual(command[1], str(script))
                                self.assertEqual(command[-1], 'configure')
                                self.assertTrue(options['node'])
                                return run_bounded(command, cwd, dict(os.environ), 30, 8192).stdout
                            tools = SimpleNamespace(paths={'node': node}, toolchain=toolchain, call=call)
                            with self.assertRaisesRegex(BuildProcessError, '^command-exit$'):
                                build.assemble(selected, case / 'captured', case / 'work', case / 'result', tools, inventory)
                            self.assertEqual(len(calls), 1)
                            self.assertFalse((case / 'result').exists())
                            self.assertEqual([p for p in (case / 'work').rglob('*') if p.is_file()], [])

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
            (root / 'cases.json').write_text(json.dumps(hydration_cases()), encoding='utf-8')
            (root / 'test.mjs').write_text('''
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
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
for (const row of JSON.parse(await readFile(new URL('./cases.json', import.meta.url), 'utf8'))) {
 if (row.accept) {
  assert.equal((await render({html:row.html},{})).html, row.html, row.name);
 } else {
  await assert.rejects(render({html:row.html},{}), row.reason==='limit'?/angular-hydration-limit/:undefined, row.name);
 }
 // Reuse this exact loaded wrapper after every rejection; counters are per render.
 const recovered='<script id="recovered-state" type="text/plain">{"name":"Bob"}</script>';
 assert.equal((await render({html:recovered},{})).html, recovered, row.name);
}
console.log('hydration wrapper boundaries passed');
''')
            result = run_bounded([node, str(root / 'test.mjs')], root, dict(os.environ), 30, 8192)
            self.assertIn(b'hydration wrapper boundaries passed', result.stdout)


if __name__ == '__main__':
    unittest.main()
