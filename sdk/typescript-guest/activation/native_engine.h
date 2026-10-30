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
void observe_result_retirement(JSContext* cx);
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
bool set_import_disposer(JSContext* cx,uint32_t id,uint32_t pointer,uint32_t result_bytes);
bool mark_import_delivered(JSContext* cx,uint32_t id);
bool cancel_import(JSContext* cx, uint32_t id);
bool watch_import_borrow(JSContext* cx, uint32_t id, JS::MutableHandleObject handle);
bool observe_import_borrow(JSContext* cx, JS::HandleObject handle, bool cancel,
                           JS::MutableHandleObject promise);
bool begin_import_own_plans(JSContext*, uint32_t version, uint32_t plans, uint32_t slots);
bool bind_import_own_slot(JSContext*, uint32_t key, uint32_t bytes, uint32_t count,
    uint32_t index, uint32_t offset, uint32_t resource, JS::HandleObject prototype, JS::HandleId symbol);
bool seal_import_own_plans(JSContext*);
bool prepare_import_own_lift(JSContext*, uint32_t id, uint32_t key, uint32_t getter,
    uint32_t disposer, uint32_t count);
bool attach_import_own(JSContext*, uint32_t id, uint32_t slot, JS::MutableHandleObject);
bool uncertain_import_own(JSContext*, uint32_t id);
bool install_import_bridge(JSContext* cx,JS::HandleObject global);
} // namespace lsf::typescript::activation
