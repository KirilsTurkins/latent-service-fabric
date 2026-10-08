#pragma once
#include "js/TypeDecls.h"
#include "js/ValueArray.h"

namespace lsf::typescript::activation {
void configure_job_dispatch();
bool install_job_dispatch(JSContext* cx);
bool snapshot_jobs_empty(JSContext* cx);
bool acknowledge_promise_retirement(JSContext* cx);
bool has_pending_promises();
bool cancel_job_dispatch(JSContext* cx);
bool begin_root(JSContext* cx);
bool park_root(JSContext* cx);
bool settle_root(JSContext* cx);
bool root_work_drained(JSContext* cx);
bool acknowledge_result_retirement(JSContext* cx);
bool start_timer(JSContext* cx, JS::HandleObject callback,
                 const JS::HandleValueArray& arguments, int32_t delay_ms,
                 bool repeat, int32_t* id);
bool clear_timer(JSContext* cx, int32_t id);
bool has_pending_timer_work();
bool run_timer_turn(JSContext* cx);
} // namespace lsf::typescript::activation
