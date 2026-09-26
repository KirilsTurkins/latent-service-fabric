import fs from 'node:fs';
import {requireValue} from './io.mjs';

// Deliberately small draft-07 subset used by these checked-in schemas. This
// avoids loading a second dependency graph for a read-only extractor. Unknown
// schema keywords fail closed; the same JSON is usable by standard validators.
const keywords = new Set(['$schema', 'title', 'description', 'type', 'properties', 'required',
  'additionalProperties', 'items', 'minItems', 'maxItems', 'uniqueItems', 'minLength',
  'maxLength', 'pattern', 'enum', 'const', 'anyOf', 'minimum', 'maximum']);
export function validate(schema, value, at = '$', depth = 0) {
  requireValue(depth < 16, 'Example schema nesting limit');
  for (const key of Object.keys(schema)) requireValue(keywords.has(key), `Unsupported example schema keyword: ${key}`);
  if (schema.anyOf) {
    requireValue(schema.anyOf.some(option => { try { validate(option, value, at, depth + 1); return true; } catch { return false; } }), `Invalid example metadata at ${at}`);
    return value;
  }
  if ('const' in schema) requireValue(value === schema.const, `Invalid constant at ${at}`);
  if (schema.enum) requireValue(schema.enum.includes(value), `Unknown example value at ${at}`);
  const type = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value;
  if (schema.type) requireValue(type === schema.type, `Invalid example metadata type at ${at}`);
  if (type === 'object') {
    for (const key of schema.required ?? []) requireValue(Object.hasOwn(value, key), `Missing example metadata at ${at}.${key}`);
    for (const [key, child] of Object.entries(value)) {
      requireValue(Object.hasOwn(schema.properties ?? {}, key), `Unknown example metadata at ${at}.${key}`);
      validate(schema.properties[key], child, `${at}.${key}`, depth + 1);
    }
  } else if (type === 'array') {
    requireValue(value.length >= (schema.minItems ?? 0) && value.length <= (schema.maxItems ?? 512), `Example array limit at ${at}`);
    if (schema.uniqueItems) requireValue(new Set(value.map(item => JSON.stringify(item))).size === value.length, `Duplicate example metadata at ${at}`);
    for (const [index, child] of value.entries()) validate(schema.items, child, `${at}[${index}]`, depth + 1);
  } else if (type === 'string') {
    const length = [...value].length;
    requireValue(length >= (schema.minLength ?? 0) && length <= (schema.maxLength ?? 1024), `Example string limit at ${at}`);
    if (schema.pattern) requireValue(new RegExp(schema.pattern).test(value), `Invalid example metadata at ${at}`);
  } else if (type === 'number') {
    requireValue(Number.isSafeInteger(value) && value >= (schema.minimum ?? 0) && value <= (schema.maximum ?? Number.MAX_SAFE_INTEGER), `Invalid example number at ${at}`);
  }
  return value;
}
export function readSchema(name) {
  requireValue(['registry', 'scenario', 'evidence'].includes(name), 'Unknown example schema');
  return JSON.parse(fs.readFileSync(new URL(`./${name}.schema.json`, import.meta.url), 'utf8'));
}
export function parseMetadata(input, schema) {
  let value;
  try { value = JSON.parse(input); } catch { throw new Error('Malformed example JSON'); }
  // Native JSON parsing is authoritative for syntax; this bounded token walk
  // rejects duplicate object keys, including differently escaped spellings.
  const stack = [];
  for (const token of input.match(/"(?:\\.|[^"\\])*"|[{}\[\]:,]/g) ?? []) {
    if (token === '{' || token === '[') {
      requireValue(stack.length < 16, 'Example JSON nesting limit');
      stack.push({object: token === '{', keys: new Set(), key: true});
    } else if (token === '}' || token === ']') stack.pop();
    else if (token === ',') { if (stack.at(-1)?.object) stack.at(-1).key = true; }
    else if (token.startsWith('"') && stack.at(-1)?.object && stack.at(-1).key) {
      const current = stack.at(-1), key = JSON.parse(token);
      requireValue(!current.keys.has(key), 'Duplicate example JSON key');
      current.keys.add(key); current.key = false;
    }
  }
  return validate(schema, value);
}
