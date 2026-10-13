// Explicit original P3 asynchronous cancellation. The generated v0.62 helper
// imports the synchronous intrinsic; it can block and traps while joined.
#pragma once
#include "jobs.h"

extern "C" {
#if defined(__wasm__)
__attribute__((__import_module__("$root"), __import_name__("[async-lower][subtask-cancel]")))
#endif
uint32_t lsf_async_subtask_cancel(uint32_t handle);
}

namespace lsf::typescript::activation {
constexpr uint32_t SubtaskCancellationBlocked = 0xffffffffu;
}
