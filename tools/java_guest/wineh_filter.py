"""Count one admitted public Clang print inside the EXISTING outer owner.

No sessions, jobs, group signals, broad child reapers or raw retained IR. On
abort we exit without waiting for a live child: the unreaped outer leader pins
the group until build_process's original owner kills/accounts all descendants.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.java_guest.public_wineh import (
    FILTER_SCHEMA, RAW_TRANSIT_BUDGET, SUMMARY_LIMIT, load_ticket, refusal,
)
from tools.java_guest.wineh_ir import Counter
from tools.rust_capsule_project import canonical

CHUNK = 16 * 1024
INNER_SECONDS = 590
DRAIN_SECONDS = 5


def collect(process: subprocess.Popen, deadline: float) -> dict:
    """Bound real pipes, not a captured full stream; poll only this child."""
    streams = (process.stdout, process.stderr)
    checksums = (hashlib.sha256(), hashlib.sha256())
    sizes = [0, 0]
    counter = Counter()
    opened = {0, 1}
    child_exit = None
    drain_deadline = None
    failure = None
    complete = False
    try:
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
        while opened or child_exit is None:
            now = time.monotonic()
            if now >= deadline:
                failure = 'filter-deadline'
                break
            progressed = False
            for index in tuple(opened):
                remaining = RAW_TRANSIT_BUDGET - sum(sizes)
                if remaining <= 0:
                    failure = 'raw-transit-limit'
                    break
                try:
                    chunk = os.read(streams[index].fileno(), min(CHUNK, remaining))
                except BlockingIOError:
                    continue
                if not chunk:
                    opened.remove(index)
                    progressed = True
                    continue
                checksums[index].update(chunk)
                sizes[index] += len(chunk)
                progressed = True
                if index == 1 and not counter.feed(chunk):
                    failure = 'print-incomplete'
                    break
            if failure is not None:
                break
            # Popen.poll is waitpid(this direct child,WNOHANG), not a competing
            # reaper of the outer filter leader or any sibling process.
            child_exit = process.poll()
            if child_exit is not None:
                if not opened:
                    complete = True
                    break
                if drain_deadline is None:
                    drain_deadline = min(deadline, time.monotonic() + DRAIN_SECONDS)
                if time.monotonic() >= drain_deadline:
                    failure = 'pipe-eof'
                    break
            if not progressed:
                time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    except OSError:
        failure = 'pipe-error'
    except (KeyboardInterrupt, SystemExit):
        failure = 'filter-interrupted'
    except Exception:
        failure = 'pipe-error'
    finally:
        # Raw nonblocking FileIO close has no child wait. Never use a Popen
        # context manager/communicate/wait on the early-abort path.
        for stream in streams:
            try:
                stream.close()
            except OSError:
                failure = 'pipe-error'
    observation = counter.finish(stream_complete=complete)
    if failure is None:
        if child_exit != 0:
            failure = 'child-exit'
        elif sizes[0]:
            failure = 'child-stdout'
        elif observation['status'] != 'observed':
            failure = 'print-incomplete'
    result = {'status': 'observed' if failure is None else 'incomplete',
              'childStarted': True, 'childExitCode': child_exit,
              'stdoutBytes': sizes[0], 'stdoutDigest': 'sha256:' + checksums[0].hexdigest(),
              'stderrBytes': sizes[1], 'stderrDigest': 'sha256:' + checksums[1].hexdigest(),
              'rawTransitMaximum': RAW_TRANSIT_BUDGET, 'observation': observation,
              'pipeEOFComplete': complete}
    if failure is not None:
        result['reason'] = failure
    return result


def main() -> int:
    started = time.monotonic()
    report = {'schemaVersion': FILTER_SCHEMA, 'status': 'incomplete',
              'qualification': False, 'childStarted': False,
              'rawTransitMaximum': RAW_TRANSIT_BUDGET, 'refusalStage': 'admission',
              'ticketDigest': None}
    try:
        if (len(sys.argv) != 3 or sys.platform != 'linux'
                or os.getpgrp() != os.getpid() or os.getsid(0) != os.getpid()):
            raise ValueError('ticket-context')
        output = Path(sys.argv[1])
        ticket_digest = sys.argv[2]
        if len(ticket_digest) != 64 or any(ch not in '0123456789abcdef' for ch in ticket_digest):
            raise ValueError('ticket-digest')
        report['ticketDigest'] = ticket_digest
        environment = dict(os.environ)
        ticket = load_ticket(output, ticket_digest, environment, deadline=started + INNER_SECONDS)
        if Path.cwd() != output / 'compiler':
            raise ValueError('ticket-context')
        if ticket['schemaVersion'] == 'latent.java.public-wineh-preclang-ticket.v1':
            from tools.java_guest.wineh_preclang import child_environment
            environment = child_environment(ticket, environment)
        report.update(sourceCommit=ticket['source']['revision'],
                      diagnosticCommandDigest='sha256:' + hashlib.sha256(
                          canonical(ticket['diagnosticCommand'])).hexdigest())
        if time.monotonic() >= started + INNER_SECONDS:
            report.update(reason='filter-deadline')
        else:
            report['refusalStage'] = 'spawn'
            report['childStarted'] = None  # Spawn interruption can be uncertain.
            process = subprocess.Popen(ticket['diagnosticCommand'], cwd=Path.cwd(), env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, close_fds=True, start_new_session=False)
            report['childStarted'] = True
            report['refusalStage'] = 'collect'
            report.update(collect(process, started + INNER_SECONDS))
    except (KeyboardInterrupt, SystemExit):
        report.update(status='incomplete', reason='filter-interrupted')
    except Exception as error:
        report.update(status='incomplete', reason=refusal(error))
    if report['status'] == 'observed':
        report.pop('refusalStage', None)
    raw = canonical(report)
    if len(raw) + 1 > SUMMARY_LIMIT:
        report = {'schemaVersion': FILTER_SCHEMA, 'status': 'incomplete',
            'qualification': False, 'ticketDigest': report['ticketDigest'],
            'rawTransitMaximum': RAW_TRANSIT_BUDGET, 'childStarted': report['childStarted'],
            'refusalStage': 'summary', 'reason': 'filter-summary-limit',
            **({name: report[name] for name in ('stdoutBytes', 'stdoutDigest', 'stderrBytes', 'stderrDigest',
                 'sourceCommit', 'diagnosticCommandDigest', 'childExitCode', 'pipeEOFComplete')}
               if report['childStarted'] else {})}
        if report['childStarted']:
            report['observation'] = {**Counter().finish(stream_complete=False),
                'reason': 'summary-limit', 'streamBytes': report['stderrBytes'],
                'streamDigest': report['stderrDigest']}
        raw = canonical(report)
    sys.stdout.buffer.write(raw + b'\n')
    sys.stdout.buffer.flush()
    return 0 if report['status'] == 'observed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
