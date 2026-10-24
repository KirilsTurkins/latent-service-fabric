"""Test-only real pipes/descendants; never an admitted compiler/guest runner."""
from pathlib import Path
import os
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.java_guest import wineh_filter
from tools.rust_capsule_project import canonical

CHILD = r'''
from pathlib import Path
import os,subprocess,sys,time
work=Path(sys.argv[1]);mode=sys.argv[2]
data=(work/'control.txt').read_bytes()
if mode=='deadline':
    time.sleep(1)
    (work/'late-side-effect').write_bytes(b'not retired')
    time.sleep(20)
elif mode=='held-pipe':
    code="from pathlib import Path;import sys,time;time.sleep(1);Path(sys.argv[1]).write_bytes(b'not retired')"
    subprocess.Popen([sys.executable,'-c',code,str(work/'late-side-effect')],
        stdin=subprocess.DEVNULL,stdout=sys.stdout,stderr=sys.stderr,close_fds=True)
    os.write(2,data)
elif mode=='raw-limit':
    os.write(1,b'x'*1024)
elif mode=='line-limit':
    os.write(2,b';'+b'x'*(256*1024)+b'\n')
else:
    for offset in range(0,len(data),7):os.write(2,data[offset:offset+7])
    if mode=='nonzero':sys.exit(3)
'''


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in {
            'success', 'raw-limit', 'line-limit', 'deadline', 'held-pipe', 'nonzero'}:
        raise SystemExit('fixed test case required')
    work, mode = Path(sys.argv[1]), sys.argv[2]
    if mode == 'raw-limit':
        wineh_filter.RAW_TRANSIT_BUDGET = 128  # Test process only, never production CLI.
    if mode == 'held-pipe':
        wineh_filter.DRAIN_SECONDS = 0.05
    process = subprocess.Popen([sys.executable, '-B', '-c', CHILD, str(work), mode],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        close_fds=True, bufsize=0, start_new_session=False)
    identity = {'ownerLeaderPid': os.getpid(), 'childPid': process.pid, 'platform': os.name}
    if os.name != 'nt':
        identity.update(leaderGroup=os.getpgrp(), childGroup=os.getpgid(process.pid))
    # No context manager or wait on a live child. The existing outer owner
    # accounts this fixture, direct child and held-pipe grandchild before return.
    result = wineh_filter.collect(process, time.monotonic() + (0.1 if mode == 'deadline' else 3))
    sys.stdout.buffer.write(canonical({**identity, **result}) + b'\n')
    sys.stdout.buffer.flush()


if __name__ == '__main__':
    main()
