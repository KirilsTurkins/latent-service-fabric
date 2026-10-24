"""Numeric observations of exactly two pinned LLVM WinEH function prints.

This is a bounded textual observer, not an LLVM verifier or a size acceptance
test. Unknown formatting is incomplete; original compiler failure is unchanged.
"""
from __future__ import annotations

import hashlib
import re

from tools.rust_capsule_project import digest

FUNCTION = 'meth_dla_Capsule_pools'
PASS = 'Windows exception handling preparation (win-eh-prepare)'
MAX_LINE = 256 * 1024
MAX_SAMPLES = 16 * 1024
KEYS = ('blocks', 'instructions', 'phi', 'phiIncoming', 'alloca', 'load',
        'store', 'volatileLoad', 'volatileStore', 'invoke', 'catchswitch')
NAME = r'(?:[-a-zA-Z$._0-9]+|"(?:[^"\\]|\\[0-9A-Fa-f]{2})+")'
LABEL = re.compile(NAME + r':(?:\s*;.*)?$')
INCOMING = re.compile(r',\s*%' + NAME + r'\s*\]')
INSTRUCTION = re.compile(r'(?:(?:%' + NAME + r') = )?(?:(?:tail|musttail|notail) )?([a-z][a-z0-9]*)\b(.*)')
OPCODES = frozenset(('ret br switch indirectbr invoke callbr resume catchswitch '
    'catchret cleanupret unreachable fneg add fadd sub fsub mul fmul udiv sdiv '
    'fdiv urem srem frem shl lshr ashr and or xor extractelement insertelement '
    'shufflevector extractvalue insertvalue alloca load store fence cmpxchg '
    'atomicrmw getelementptr trunc zext sext fptrunc fpext fptoui fptosi uitofp '
    'sitofp ptrtoint inttoptr bitcast addrspacecast icmp fcmp phi select freeze '
    'call va_arg landingpad catchpad cleanuppad').split())
# The count is of instruction-leading lines. LLVM prints these operands on
# subsequent lines; any other noninstruction row fails closed, rather than
# silently accepting incomplete instruction counts.
CONTINUATION = re.compile(r'(?:to label %.* unwind label %.*|unwind label %.*|'
                          r'catch .*|filter .*|cleanup|\[|\]|.*\] to caller|'
                          r'i[0-9]+ -?[0-9]+, label %.*)')


class Counter:
    """One bounded line buffer; each byte is appended at most once."""

    def __init__(self):
        self.record = {'status': 'incomplete', 'qualification': False,
                       'source': 'pinned-llvm-text-only', 'snapshots': {}, 'samples': []}
        self.phase = None
        self.opened = False
        self.completed = []
        self.samples_bytes = 0
        self.pending = bytearray()
        self.checksum = hashlib.sha256()
        self.stream_bytes = 0
        self.error = None
        self.final = None

    def _line(self, line: bytes) -> None:
        text = line.decode('utf-8').strip()
        if text.startswith('*** IR Dump '):
            expected_phase = 'Before' if not self.completed else 'After'
            if (self.phase is not None or len(self.completed) >= 2
                    or text != f'*** IR Dump {expected_phase} {PASS} ***'):
                raise ValueError('snapshot-order-or-identity')
            self.phase = expected_phase.lower()
            self.record['snapshots'][self.phase] = dict.fromkeys(KEYS, 0)
            return
        if self.phase is None:
            return  # Outside-print warnings contribute only to the hash.
        if not self.opened:
            if not text or text.startswith(';'):
                return
            if (not text.startswith('define ') or not text.endswith('{')
                    or len(re.findall(r'@' + FUNCTION + r'\(', text)) != 1):
                raise ValueError('function-identity')
            self.opened = True
            return
        if text == '}':
            self.completed.append(self.phase)
            self.phase, self.opened = None, False
            return
        if not text or text.startswith(';'):
            return
        count = self.record['snapshots'][self.phase]
        if LABEL.fullmatch(text):
            count['blocks'] += 1
            return
        if CONTINUATION.fullmatch(text):
            return
        match = INSTRUCTION.fullmatch(text)
        if not match:
            raise ValueError('instruction-format')
        opcode, operands = match.groups()
        if opcode not in OPCODES:
            raise ValueError('instruction-opcode')
        if not count['blocks']:
            count['blocks'] = 1
        count['instructions'] += 1
        if opcode in count:
            count[opcode] += 1
        if opcode in {'load', 'store'} and re.match(r'\s*(?:atomic\s+)?volatile\b', operands):
            count['volatile' + opcode.title()] += 1
        if opcode == 'phi':
            incoming = len(INCOMING.findall(operands))
            if not incoming:
                raise ValueError('phi-format')
            count['phiIncoming'] += incoming
        if opcode in {'phi', 'alloca', 'store', 'catchswitch'} and len(self.record['samples']) < 16:
            sample = {'phase': self.phase, 'opcode': opcode,
                      'instruction': count['instructions'], 'lineBytes': len(line),
                      'lineDigest': digest(line)}
            self.samples_bytes += len(str(sample).encode('ascii'))
            if self.samples_bytes > MAX_SAMPLES:
                raise ValueError('sample-limit')
            self.record['samples'].append(sample)

    def feed(self, chunk: bytes) -> bool:
        if self.final is not None:
            raise ValueError('counter-already-finished')
        self.checksum.update(chunk)
        self.stream_bytes += len(chunk)
        if self.error is not None:
            return False
        if len(chunk) > 16 * 1024:
            self.error = 'chunk-limit'
            return False
        offset = 0
        try:
            while offset < len(chunk):
                newline = chunk.find(b'\n', offset)
                end = len(chunk) if newline < 0 else newline + 1
                if len(self.pending) + end - offset > MAX_LINE:
                    raise ValueError('line-limit')  # BYTES, before decoding.
                self.pending.extend(memoryview(chunk)[offset:end])
                offset = end
                if newline >= 0:
                    self._line(bytes(self.pending))
                    self.pending.clear()
        except UnicodeError:
            self.error = 'encoding'
        except ValueError as error:
            self.error = str(error)  # Only this parser's fixed literal codes.
        return self.error is None

    def finish(self, *, stream_complete=True) -> dict:
        if self.final is not None:
            return self.final
        try:
            if not stream_complete:
                raise ValueError('stream-incomplete')
            if self.error is None and self.pending:
                self._line(bytes(self.pending))
                self.pending.clear()
            if self.error is None and (self.phase is not None or self.completed != ['before', 'after']):
                raise ValueError('snapshot-incomplete')
            if self.error is None and any(not row['instructions'] for row in self.record['snapshots'].values()):
                raise ValueError('empty-function')
        except UnicodeError:
            self.error = self.error or 'encoding'
        except ValueError as error:
            self.error = self.error or str(error)
        self.pending.clear()
        self.record.update(streamDigest='sha256:' + self.checksum.hexdigest(),
                           streamBytes=self.stream_bytes, prefixOnly=self.error is not None)
        if self.error is None:
            self.record['delta'] = {key: self.record['snapshots']['after'][key]
                                   - self.record['snapshots']['before'][key] for key in KEYS}
            self.record['status'] = 'observed'
        else:
            self.record['reason'] = self.error
        self.final = self.record
        return self.final


def observe(raw: bytes) -> dict:
    counter = Counter()
    for offset in range(0, len(raw), 16 * 1024):
        counter.feed(raw[offset:offset + 16 * 1024])
    return counter.finish()
