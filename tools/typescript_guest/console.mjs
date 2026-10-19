// Synchronous standard console over the declared typed LOG capability.
export function installConsole(log, snapshotActive, target = globalThis) {
  function primitive(value) {
    if (value !== null && !['string', 'number', 'boolean', 'undefined'].includes(typeof value)) {
      throw new TypeError('lsf-console-strict-v1:unsupported-value');
    }
    const text = String(value);
    if (text.length > 256) throw new RangeError('console-message-limit');
    return text;
  }
  function format(args) {
    if (args.length > 16) throw new RangeError('console-argument-limit');
    const values = args.map(primitive);
    let text = '', next = 1;
    if (values.length > 1 && typeof args[0] === 'string') {
      text = values[0].replace(/%[%sdifoOc]/g, token => {
        if (token === '%%') return '%';
        if (next >= values.length) return token;
        if (!['%s', '%d', '%i', '%f'].includes(token)) {
          throw new TypeError('lsf-console-strict-v1:unsupported-format');
        }
        const value = values[next++];
        return token === '%s' ? value : token === '%f' ? String(Number.parseFloat(value)) : String(Number.parseInt(value, 10));
      });
    } else if (values.length) text = values[0];
    for (; next < values.length; next++) text += ' ' + values[next];
    // Canonical WIT strings are UTF-8. Replace isolated UTF-16 surrogates as
    // the standard scalar-value conversion does, before charging the bound.
    let result = '', bytes = 0;
    for (let char of text) {
      const code = char.codePointAt(0);
      if (code >= 0xd800 && code <= 0xdfff) char = '\ufffd';
      bytes += code <= 0x7f ? 1 : code <= 0x7ff ? 2 : code <= 0xffff ? 3 : 4;
      if (bytes > 256) throw new RangeError('console-message-limit');
      result += char;
    }
    return result;
  }
  const console = Object.create({});
  for (const [name, level] of Object.entries({log: 'info', info: 'info', debug: 'debug', warn: 'warn', error: 'error'})) {
    Object.defineProperty(console, name, {enumerable: true, writable: true, configurable: true, value(...args) {
      if (snapshotActive()) throw new TypeError('console-during-build-snapshot-denied');
      if (!args.length) return;
      const message = format(args);
      // No caller identity/fields, local retry, worker, pending buffer or flush
      // acknowledgement. The host owns correlation, validation and LogBytes.
      if (log.write(level, message, []) !== true) throw new Error('console-log-not-accepted');
    }});
  }
  for (const name of ['assert', 'clear', 'count', 'countReset', 'dir', 'dirxml', 'group',
    'groupCollapsed', 'groupEnd', 'table', 'time', 'timeEnd', 'timeLog', 'trace']) {
    Object.defineProperty(console, name, {writable: true, configurable: true,
      value() {throw new TypeError('lsf-console-strict-v1:unsupported:' + name);}});
  }
  Object.defineProperty(target, 'console', {value: console, configurable: true, writable: true});
}
