"""Actual host operator process cancelled while its real response is in flight."""
from pathlib import Path
import sys

sys.path.insert(0, '/source/tools')
sys.path.insert(0, '/source/tools/container_runtime')
from ci_operator import Transport, operate, protected

transport = Transport(Path('/usr/bin/docker'))
transport.receiver = '/source/tools/container_runtime/qualification_operator_pause.py'
summary = operate(transport, protected(Path('/journal/target.json')),
                  protected(Path('/journal/cancel-request.json')), Path('/journal/cancel-journal.json'))
assert summary['status'] == 'uncertain'
