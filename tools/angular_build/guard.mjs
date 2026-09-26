// Conservative authoring profile. This is not a JavaScript sandbox; the final
// component still requires the closed runtime's import and resource checks.
import path from 'node:path';

const packages = new Set(['@angular/common', '@angular/core', '@angular/platform-browser',
  '@angular/platform-server', '@angular/common/http', 'rxjs', 'rxjs/operators']);
const ambient = new Set(['process', 'require', 'eval', 'Function', 'Buffer', 'Deno', 'Bun',
  'WebSocket', 'Worker', 'SharedWorker', 'XMLHttpRequest', 'setInterval']);

export function checkSource(ts, name, text, names) {
  const source = ts.createSourceFile(name, text, ts.ScriptTarget.ES2022, true);
  if (source.parseDiagnostics.length) throw new Error('angular-source-syntax');
  if (source.referencedFiles.length || source.typeReferenceDirectives.length || source.libReferenceDirectives.length) {
    throw new Error('angular-reference-directive');
  }
  const area = name.split('/')[0];
  function local(target) {
    if (!['shared', area].includes(target.split('/')[0])) throw new Error('angular-client-server-separation');
  }
  function reference(specifier) {
    if (typeof specifier !== 'string') throw new Error('angular-nonliteral-import');
    if (!specifier.startsWith('.')) {
      if (!packages.has(specifier)) throw new Error('angular-import-profile');
      return;
    }
    const target = path.posix.normalize(path.posix.join(path.posix.dirname(name), specifier));
    const resolved = target.replace(/\.js$/, '.ts');
    if (!names.has(resolved)) throw new Error('angular-import-outside-capture');
    local(resolved);
  }
  function resource(value) {
    if (!ts.isStringLiteral(value)) throw new Error('angular-nonliteral-resource');
    // Do not normalize an absolute/URL spelling into an apparently local name:
    // Angular, not this scanner, will eventually resolve the resource.
    if (path.posix.isAbsolute(value.text) || path.win32.isAbsolute(value.text) ||
        value.text.includes('\\') || /^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(value.text)) {
      throw new Error('angular-resource-outside-capture');
    }
    const target = path.posix.normalize(path.posix.join(path.posix.dirname(name), value.text));
    if (!names.has(target) || !/\.(html|css)$/.test(target)) throw new Error('angular-resource-outside-capture');
    // ngc inlines templates and styles before the bundler sees its graph.
    // Their source area must therefore be checked before compilation too.
    local(target);
  }
  function visit(node) {
    if (ts.isIdentifier(node) && ambient.has(node.text)) throw new Error('angular-ambient-lifecycle');
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) {
      if (node.moduleSpecifier) {
        if (!ts.isStringLiteral(node.moduleSpecifier)) throw new Error('angular-nonliteral-import');
        reference(node.moduleSpecifier.text);
      }
    }
    if (ts.isImportEqualsDeclaration(node) || (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword)) {
      throw new Error('angular-dynamic-module');
    }
    // External resources use only ordinary, explicitly initialized properties.
    // Angular resolves shorthand identifiers too, but this closed profile does
    // not: reject them rather than let ngc inline unchecked file contents.
    // Reject computed keys conservatively, including unknown keys that might
    // evaluate to a resource name. Read decoded property names, not source text.
    if (ts.isComputedPropertyName(node)) throw new Error('angular-computed-property');
    if (node.name && ts.isObjectLiteralExpression(node.parent) &&
        (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name))) {
      const key = node.name.text;
      if (['templateUrl', 'styleUrl', 'styleUrls'].includes(key)) {
        if (!ts.isPropertyAssignment(node)) throw new Error('angular-nonliteral-resource');
        if (key === 'styleUrls') {
          if (!ts.isArrayLiteralExpression(node.initializer)) throw new Error('angular-nonliteral-resource');
          for (const entry of node.initializer.elements) resource(entry);
        } else {
          resource(node.initializer);
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
}
