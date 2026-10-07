// Internal core exports consumed by the source-owned splicer. These are not
// public application Component Model exports or capability-granting APIs.
#include "native_engine.h"
#include "js/Conversions.h"
#include "jsapi.h"

extern "C" {
__attribute__((export_name("lsf_import_reserve"))) uint32_t
lsf_import_reserve(JSContext* cx, uint32_t result_size, uint32_t parameter_size,
                   JS::Value* captures, uint32_t* result, uint32_t* parameters) {
  uint32_t id = 0;
  void* result_buffer = nullptr;
  void* parameter_buffer = nullptr;
  JS::RootedValue rooted(cx, *captures);
  if (!lsf::typescript::activation::reserve_import(cx, result_size, parameter_size,
          rooted, &id, &result_buffer, &parameter_buffer)) return 0;
  *result = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(result_buffer));
  *parameters = static_cast<uint32_t>(reinterpret_cast<uintptr_t>(parameter_buffer));
  return id;
}
__attribute__((export_name("lsf_import_begin"))) bool
lsf_import_begin(JSContext* cx, uint32_t id) {
  return lsf::typescript::activation::begin_import_lowering(cx, id);
}
__attribute__((export_name("lsf_import_started"))) bool
lsf_import_started(JSContext* cx, uint32_t id, uint32_t status, JS::Value* result) {
  JS::RootedObject promise(cx);
  if (!lsf::typescript::activation::start_import(cx, id, status, &promise)) return false;
  *result = JS::ObjectValue(*promise);
  return true;
}
__attribute__((export_name("lsf_import_lift"))) uint32_t
lsf_import_lift(JSContext* cx, uint32_t id) {
  void* result = nullptr;
  if (!lsf::typescript::activation::lift_import(cx, id, &result)) return 0;
  return static_cast<uint32_t>(reinterpret_cast<uintptr_t>(result));
}
__attribute__((export_name("lsf_import_finish"))) bool
lsf_import_finish(JSContext* cx, uint32_t id) {
  return lsf::typescript::activation::finish_import(cx, id);
}
__attribute__((export_name("lsf_import_cancel"))) bool
lsf_import_cancel(JSContext* cx, uint32_t id) {
  return lsf::typescript::activation::cancel_import(cx, id);
}
}
