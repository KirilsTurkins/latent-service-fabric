from pathlib import Path
import json
root=Path('.'); w=root/'website'
p=w/'lib/package-manager-security.mjs'
s=p.read_text().replace("ipAddressVersion = '10.5.1'", "ipAddressVersion = '10.7.2'").replace('sha512-EXujUp9jyOI/chPgtqk6uy7fDq8AeCB/WlfEuPg9LN0fN9lzKAKfuDYi60SMhHwgUiEhZvVYsbGZN+RUU1INiA==','sha512-7H/2gFSIitxc0hG3nOI1glS8QLo/EHBFFLk8vEUjXY/xu0AdL8jZ9U1IzO2PUm0d2D/ofQcAifb0g6OBkt8U7w==')
s=s.replace("const ipAddress =", "export const braceExpansionVersion = '5.0.12';\nexport const braceExpansionIntegrity = 'sha512-YovQ3rzhaLMIrDjNDMkNS01tea93qhEhG5xy8f6+R0l+dw3Ki+5sCoIoI942iuLZTHWogWktgwVDhU09iNEimQ==';\nconst ipAddress =")
s=s.replace("previousVersion: '10.5.0'", "previousVersions: ['10.5.0', '10.5.1']").replace("previousVersion: '6.28.0'", "previousVersions: ['6.28.0']")
s=s.replace("const read =", "const braceExpansion = Object.freeze({name: 'brace-expansion', version: braceExpansionVersion, integrity: braceExpansionIntegrity, previousVersions: ['5.0.9']});\nconst read =")
s=s.replace('[selected.previousVersion, selected.version]', '[...selected.previousVersions, selected.version]')
s=s.replace('export function assertNat64Classification', "export function replaceBundledBraceExpansion(websiteRoot) {\n  replaceBundledDependency(websiteRoot, braceExpansion);\n}\n\nexport function assertNat64Classification")
s=s.replace("  const cases = assertNat64Classification(socksRequire('ip-address').Address6);", """  const {Address4, Address6} = socksRequire('ip-address');
  const cases = assertNat64Classification(Address6);
  // GHSA-j6r3-76f7-8jcv: a subnet of the other family never contains the address.
  assert.equal(new Address4('127.0.0.1').isInSubnet(new Address6('::/0')), false);
  assert.equal(new Address6('::1').isInSubnet(new Address4('0.0.0.0/0')), false);
  // GHSA-h3mg-xc3c-68pw: reject length before running the address parser.
  assert.throws(() => new Address4('1'.repeat(4096)), {name: 'AddressError', message: /at most 15 characters/});
  assert.throws(() => new Address6(':'.repeat(4096)), {name: 'AddressError', message: /at most 45 characters/});""")
s += """
export function verifyBundledBraceExpansion(websiteRoot) {
  const {root, files, bundleLocation} = inputs(websiteRoot, braceExpansion);
  const target = directory(root, bundleLocation);
  assert.deepEqual(inventory(target), files, 'npm must contain the complete reviewed brace-expansion replacement');
  const npmRequire = createRequire(path.join(root, 'node_modules/npm/package.json'));
  const minimatchRequire = createRequire(npmRequire.resolve('minimatch'));
  assert.equal(fs.realpathSync(minimatchRequire.resolve('brace-expansion')), fs.realpathSync(path.join(target, 'dist/commonjs/index.js')),
    'The real npm minimatch dependency must load the patched bundled copy');
  const {expand} = minimatchRequire('brace-expansion');
  assert.deepEqual(expand('file-{a,b}-{1..2}.txt'), ['file-a-1.txt', 'file-a-2.txt', 'file-b-1.txt', 'file-b-2.txt']);
  assert.deepEqual(expand('{{{{a,b}}}}', {maxDepth: 2}), ['{{{{a,b}}}}']);
  assert.deepEqual(expand('{a}}},z}', {maxRewrites: 1}), ['{a}}},z}']);
  return {braceExpansion: braceExpansionVersion};
}
"""
p.write_text(s)
for name in ['patch-package-manager.mjs','check-package-manager.mjs']:
 p=w/'scripts'/name;s=p.read_text()
 if name.startswith('patch'):
  s=s.replace('replaceBundledIpAddress, replaceBundledUndici','replaceBundledIpAddress, replaceBundledUndici, replaceBundledBraceExpansion').replace('replaceBundledUndici(root);','replaceBundledUndici(root);\nreplaceBundledBraceExpansion(root);')
  s=s.replace('executes the NAT64 regression','executes the security regressions')
 else:
  s=s.replace('verifyBundledIpAddress, verifyBundledUndici','verifyBundledIpAddress, verifyBundledUndici, verifyBundledBraceExpansion').replace('...verifyBundledUndici(root)}','...verifyBundledUndici(root), ...verifyBundledBraceExpansion(root)}')
 p.write_text(s)
p=w/'toolchain/package.json';m=json.loads(p.read_text());m['dependencies']={'brace-expansion':'5.0.12',**m['dependencies']};p.write_text(json.dumps(m,indent=2)+'\n')
p=w/'toolchain/package-lock.json';l=json.loads(p.read_text());lp=l['packages']
bl={
 'node_modules/balanced-match': {'version':'4.0.4','resolved':'https://registry.npmjs.org/balanced-match/-/balanced-match-4.0.4.tgz','integrity':'sha512-BLrgEcRTwX2o6gGxGOCNyMvGSp35YofuYzw9h1IMTRmKqttAZZVU67bdb9Pr2vUHA8+j3i2tJfjO6C6+4myGTA==','license':'MIT','engines':{'node':'18 || 20 || >=22'}},
 'node_modules/brace-expansion': {'version':'5.0.12','resolved':'https://registry.npmjs.org/brace-expansion/-/brace-expansion-5.0.12.tgz','integrity':'sha512-YovQ3rzhaLMIrDjNDMkNS01tea93qhEhG5xy8f6+R0l+dw3Ki+5sCoIoI942iuLZTHWogWktgwVDhU09iNEimQ==','license':'MIT','dependencies':{'balanced-match':'^4.0.2'},'engines':{'node':'20 || >=22'}}
}
lp['']['dependencies']=m['dependencies']
for name in ['balanced-match','brace-expansion']:lp['node_modules/'+name]=bl['node_modules/'+name]
for name in ['ip-address','undici','brace-expansion']:lp['node_modules/npm/node_modules/'+name]=dict(lp['node_modules/'+name])
l['packages']=dict(sorted(lp.items()));p.write_text(json.dumps(l,indent=2)+'\n')
p=w/'tests/package-manager-security.test.mjs';s=p.read_text();s += """
test('an already patched 10.5.1 installation upgrades to the current reviewed version', t => {
  const {root, target} = fixture(t);
  fs.writeFileSync(path.join(target, 'package.json'), JSON.stringify({name: 'ip-address', version: '10.5.1'}));
  replaceBundledIpAddress(root);
  assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, ipAddressVersion);
});

test('Dependabot cannot restore stale bundled metadata for a separately pinned replacement', t => {
  const {root, target} = fixture(t);
  const file = path.join(root, 'toolchain/package-lock.json');
  const lock = JSON.parse(fs.readFileSync(file));
  for (const location of ['node_modules/ip-address', 'node_modules/npm/node_modules/ip-address']) {
    for (const [field, value] of [['inBundle', true], ['version', '10.5.1']]) {
      const changed = structuredClone(lock);
      changed.packages[location][field] = value;
      fs.writeFileSync(file, JSON.stringify(changed));
      assert.throws(() => replaceBundledIpAddress(root));
      assert.equal(JSON.parse(fs.readFileSync(path.join(target, 'package.json'))).version, '10.5.0');
    }
  }
});
""";p.write_text(s)
p=w/'README.md';s=p.read_text().replace('10.5.1','10.7.2').replace('Even npm\n11.20.0 retains that version. A normal npm override or a lockfile-only edit','A normal\nnpm override or a lockfile-only edit')
s=s.replace('## Additional security-baseline repair',"""The same bootstrap replaces npm's bundled `brace-expansion` 5.0.9 with the
complete, separately SHA-512-pinned 5.0.12 package. Its `balanced-match`
dependency is locked for both the standalone source and npm's bundled graph.
The verifier checks the package actually resolved by npm's `minimatch`,
normal expansion, nesting limits and rewrite limits. A bounded child-process
regression covers chained comma parsing, nested groups and rewrite-heavy input.
This addresses GHSA-6j4f-fj2g-mc7p, GHSA-qhr7-859c-m2p7 and GHSA-q2hr-2g5m-vwhr
without suppressing advisory findings. Retain all separately pinned replacement
records, including Undici, when regenerating the toolchain lock.

The `ip-address` regression also checks cross-family subnet rejection and
pre-parser address length bounds for GHSA-j6r3-76f7-8jcv and GHSA-h3mg-xc3c-68pw.

## Additional security-baseline repair""")
p.write_text(s)
p=root/'docs/development/website.md';s=p.read_text().replace('10.5.1','10.7.2').replace('locked toolchain. Replace its vulnerable bundled `ip-address` before invoking it:', 'locked toolchain. Replace its vulnerable bundled dependencies before invoking it:').replace('classification before the selected npm runs. See the','classification before the selected npm runs. The same step replaces bundled\nUndici with 6.28.1 and `brace-expansion` with 5.0.12, and checks their real module\nresolution and security controls. See the');p.write_text(s)
