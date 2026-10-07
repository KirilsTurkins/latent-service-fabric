#pragma once
#include "js/TypeDecls.h"

namespace lsf::typescript::activation {
void configure_job_dispatch();
bool install_job_dispatch(JSContext* cx);
bool snapshot_jobs_empty(JSContext* cx);
bool acknowledge_promise_retirement(JSContext* cx);
bool has_pending_promises();
bool cancel_job_dispatch(JSContext* cx);
} // namespace lsf::typescript::activation
