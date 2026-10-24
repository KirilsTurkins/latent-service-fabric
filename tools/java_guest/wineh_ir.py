"""Numeric observations of exactly two pinned LLVM WinEH function prints.

This is a bounded textual observer, not an LLVM verifier or a size acceptance
test. Unknown formatting is incomplete; original compiler failure is unchanged.
"""
from __future__ import annotations

import io
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


def observe(raw: bytes) -> dict:
    result = {'status': 'incomplete', 'qualification': False,
              'source': 'pinned-llvm-text-only', 'streamDigest': digest(raw),
              'streamBytes': len(raw), 'snapshots': {}, 'samples': []}
    phase = None
    opened = False
    completed = []
    samples_bytes = 0
    rows = io.BytesIO(raw)
    try:
        while line := rows.readline(MAX_LINE + 1):
            if len(line) > MAX_LINE:
                raise ValueError('line-limit')
            text = line.decode('utf-8').strip()
            if text.startswith('*** IR Dump '):
                expected_phase = 'Before' if not completed else 'After'
                if (phase is not None or len(completed) >= 2
                        or text != f'*** IR Dump {expected_phase} {PASS} ***'):
                    raise ValueError('snapshot-order-or-identity')
                phase = expected_phase.lower()
                result['snapshots'][phase] = dict.fromkeys(KEYS, 0)
                continue
            if phase is None:
                # The normal tool may print warnings outside snapshots. Retain
                # only the channel digest, never raw messages or paths.
                continue
            if not opened:
                if not text or text.startswith(';'):
                    continue
                if (not text.startswith('define ') or not text.endswith('{')
                        or len(re.findall(r'@' + FUNCTION + r'\(', text)) != 1):
                    raise ValueError('function-identity')
                opened = True
                continue
            if text == '}':
                completed.append(phase)
                phase, opened = None, False
                continue
            if not text or text.startswith(';'):
                continue
            count = result['snapshots'][phase]
            if LABEL.fullmatch(text):
                count['blocks'] += 1
                continue
            if CONTINUATION.fullmatch(text):
                continue
            match = INSTRUCTION.fullmatch(text)
            if not match:
                raise ValueError('instruction-format')
            opcode, operands = match.groups()
            if opcode not in OPCODES:
                raise ValueError('instruction-opcode')
            if not count['blocks']:
                count['blocks'] = 1  # Unnamed entry has no printed label.
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
            if opcode in {'phi', 'alloca', 'store', 'catchswitch'} and len(result['samples']) < 16:
                sample = {'phase': phase, 'opcode': opcode,
                          'instruction': count['instructions'], 'lineBytes': len(line),
                          'lineDigest': digest(line)}
                samples_bytes += len(str(sample).encode('ascii'))
                if samples_bytes > MAX_SAMPLES:
                    raise ValueError('sample-limit')
                result['samples'].append(sample)
        if phase is not None or completed != ['before', 'after']:
            raise ValueError('snapshot-incomplete')
        if any(not row['instructions'] for row in result['snapshots'].values()):
            raise ValueError('empty-function')
        result['delta'] = {key: result['snapshots']['after'][key]
                           - result['snapshots']['before'][key] for key in KEYS}
        result['status'] = 'observed'
    except UnicodeError:
        result['reason'] = 'encoding'
    except ValueError as error:
        result['reason'] = str(error)
    return result
