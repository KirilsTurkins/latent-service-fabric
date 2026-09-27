// Build-time transformation of owned source output, before package identities
// and approval exist. Never rewrites bytes at the HTTP boundary.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {lstat, mkdir, readFile, readdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {parse, serialize} from 'parse5';

const [input, output, selectedMount] = process.argv.slice(2);
assert.ok(input && output && ['/', '/docs'].includes(selectedMount));
const source = path.resolve(input), destination = path.resolve(output);
assert.ok(source !== destination && !destination.startsWith(source + path.sep));
const mount = selectedMount === '/' ? '' : selectedMount;
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
// A full SHA-256 identity in a portable segment shorter than 64 characters.
const filenameHash = bytes => createHash('sha256').update(bytes).digest('base64url');
const report = {schemaVersion: 'latent.framework.transformation.v1', mount,
  nativeRuntimeQualified: false, pages: [], sourceFiles: 0, sourceBytes: 0};
const generated = new Map();
await mkdir(destination);

async function walk(relative = '') {
  for (const entry of (await readdir(path.join(source, relative), {withFileTypes: true})).sort((a, b) => a.name.localeCompare(b.name))) {
    assert.match(entry.name, /^[A-Za-z0-9_.-]+$/, 'configure portable chunk names before packaging');
    assert.ok(entry.name.length <= 64, 'configure chunk names within the package segment limit');
    assert.ok(!entry.isSymbolicLink(), 'linked build output is unsupported');
    const name = path.posix.join(relative, entry.name);
    if (entry.isDirectory()) { await mkdir(path.join(destination, name)); await walk(name); continue; }
    assert.ok(entry.isFile());
    const info = await lstat(path.join(source, name));
    assert.ok(info.size <= 8 * 1024 * 1024);
    let bytes = await readFile(path.join(source, name));
    report.sourceFiles++; report.sourceBytes += bytes.length;
    assert.ok(report.sourceFiles <= 252 && report.sourceBytes <= 16 * 1024 * 1024);
    // The generator's deployment marker has no browser meaning. Record its
    // deliberate exclusion; every other regular output must remain present.
    if (name === '.nojekyll') { report.excluded = ['.nojekyll']; continue; }
    assert.ok(!name.split('/').some(part => part.startsWith('.')), 'review hidden output before capture');
    if (name.endsWith('.html')) {
      const document = parse(bytes.toString('utf8'));
      const page = {path: name, original: 'sha256:' + hash(bytes), scripts: [], symbolStyle: false};
      let head;
      function visit(node) {
        if (node.tagName === 'head') head = node;
        assert.notEqual(node.tagName, 'base', `${name}: configure generator baseUrl; base elements are forbidden`);
        for (const attr of node.attrs ?? []) {
          assert.ok(!attr.name.startsWith('on'), `${name}: externalize event handler ${attr.name}`);
        }
        const style = node.attrs?.find(attr => attr.name === 'style');
        if (style) {
          assert.ok(node.tagName === 'svg' && style.value === 'display: none;', `${name}: unsupported inline style; move it to an owned stylesheet`);
          node.attrs = node.attrs.filter(attr => attr !== style);
          let classes = node.attrs.find(attr => attr.name === 'class');
          if (!classes) { classes = {name: 'class', value: ''}; node.attrs.push(classes); }
          classes.value += ' lsf-generator-symbols'; page.symbolStyle = true;
        }
        assert.notEqual(node.tagName, 'style', `${name}: externalize static style elements in the application build`);
        if (node.tagName === 'script' && !node.attrs.some(attr => attr.name === 'src')) {
          assert.ok(node.attrs.every(attr => attr.name === 'data-rh'), `${name}: review non-classic inline script before externalizing`);
          const script = node.childNodes.map(child => child.value ?? '').join('');
          assert.ok(Buffer.byteLength(script) > 0 && Buffer.byteLength(script) <= 65536);
          const file = 'assets/lsf-bootstrap-' + filenameHash(script) + '.js';
          generated.set(file, script); page.scripts.push(file);
          node.attrs.push({name: 'src', value: mount + '/' + file});
          node.childNodes = [];
        }
        for (const child of node.childNodes ?? []) visit(child);
      }
      visit(document); assert.ok(head);
      if (page.symbolStyle) {
        const css = '.lsf-generator-symbols{display:none}\n';
        const file = 'assets/lsf-symbols-' + filenameHash(css) + '.css'; generated.set(file, css);
        head.childNodes.push({nodeName: 'link', tagName: 'link', attrs: [
          {name: 'rel', value: 'stylesheet'}, {name: 'href', value: mount + '/' + file}],
          namespaceURI: 'http://www.w3.org/1999/xhtml', childNodes: [], parentNode: head});
      }
      bytes = Buffer.from(serialize(document));
      page.transformed = 'sha256:' + hash(bytes); report.pages.push(page);
    }
    await writeFile(path.join(destination, name), bytes, {flag: 'wx'});
  }
}
await walk();
for (const [name, bytes] of generated) {
  await mkdir(path.dirname(path.join(destination, name)), {recursive: true});
  await writeFile(path.join(destination, name), bytes, {flag: 'wx'});
}
assert.ok(report.sourceFiles + generated.size <= 252);
await writeFile(output + '-transformation.json', JSON.stringify(report), {flag: 'wx'});
console.log(JSON.stringify({pages: report.pages.length, externalizedFiles: generated.size,
  sourceFiles: report.sourceFiles, sourceBytes: report.sourceBytes, mount}));
