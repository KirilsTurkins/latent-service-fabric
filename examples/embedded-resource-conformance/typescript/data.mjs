import text from './text.txt';
import bytes from './binary.bin';
import emptyText from './empty.txt';
import emptyBytes from './empty.bin';

export function read(mode) {
  if (mode === 'text') {
    if (text !== 'Gr\u00fc\u00dfe\0\u96ea\n') throw new Error('resource-text-changed');
    return 'resource|text=' + text;
  }
  if (mode === 'binary') {
    if (!(bytes instanceof Uint8Array) || bytes.length !== 6 ||
        bytes.some((v,i) => v !== [0,255,128,65,13,10][i])) throw new Error('resource-binary-changed');
    return 'resource|binary=00ff80410d0a';
  }
  if (mode === 'empty') {
    if (emptyText !== '' || !(emptyBytes instanceof Uint8Array) || emptyBytes.length !== 0)
      throw new Error('empty-resource-changed');
    return 'resource|empty=0+0';
  }
  if (mode === 'copies') {
    const first = bytes.slice(), second = bytes.slice();
    first[0] = 42;
    if (second[0] !== 0 || bytes[0] !== 0) throw new Error('resource-copy-shared');
    return 'resource|copies=independent';
  }
  if (mode === 'trap') {
    bytes[0] = 42;
    throw new Error('requested-resource-trap-after-local-mutation');
  }
  throw new Error('unknown-fixed-resource-case');
}
