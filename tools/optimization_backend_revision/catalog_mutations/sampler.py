"""The established bounded source sampler, with explicit mutation mode mapping."""
from tools.optimization_backend_revision.catalog import sampler as common
from . import model

MAX_BYTES = common.MAX_BYTES
MAX_ROW_BYTES = common.MAX_ROW_BYTES
MAX_ROWS = common.MAX_ROWS
PERIOD_NANOS = common.PERIOD_NANOS
COLUMNS = common.COLUMNS
cadence = common.cadence


def read(source, mode, *, pid, start_ticks, elapsed_nanos):
    selected = "reopen" if model.is_reopen(mode) else "initial"
    return common.read(source, selected, pid=pid, start_ticks=start_ticks, elapsed_nanos=elapsed_nanos)


def phase(rows, started_nanos, finished_nanos):
    return {**common.phase(rows, started_nanos, finished_nanos),
            "scope": "fixed-100ms-source-samples-wholly-inside-operation-read-window"}


def validate(value, mode, artifacts, directory, owner, elapsed, before_node, final_started):
    selected = "allocation" if model.profiled(mode) else mode
    return common.validate(value, selected, artifacts, directory, owner, elapsed, before_node, final_started)
