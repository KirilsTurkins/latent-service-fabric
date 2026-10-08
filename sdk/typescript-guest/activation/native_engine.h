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
bool start_timeout_nanoseconds(JSContext* cx, JS::HandleObject callback,
                               const JS::HandleValueArray& arguments,
                               uint64_t nanos, int32_t* id);
bool has_pending_timer_work();
bool run_timer_turn(JSContext* cx);
bool reserve_import(JSContext* cx, uint32_t result_size, uint32_t parameter_size,
                    uint32_t raw_kind, const JS::HandleValueArray& captures, uint32_t* id, void** result, void** parameters);
bool begin_import_lowering(JSContext* cx, uint32_t id);
void* import_result_buffer(uint32_t id);
void* import_parameter_buffer(uint32_t id);
bool start_import(JSContext* cx, uint32_t id, uint32_t status, JS::MutableHandleObject promise);
bool lift_import(JSContext* cx, uint32_t id, void** result);
bool lift_import_value(JSContext* cx, uint32_t id, JS::MutableHandleValue value);
bool finish_import(JSContext* cx, uint32_t id);
bool cancel_import(JSContext* cx, uint32_t id);
bool install_import_bridge(JSContext* cx,JS::HandleObject global);
} // namespace lsf::typescript::activation
