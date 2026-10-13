// Original embedding raw-value ABI after canonical subtask terminal/drop.
// WIT-specific JavaScript lifting still handles full public values/resources.
#pragma once
#include "js/BigInt.h"
#include "js/Conversions.h"
#include "jsapi.h"
#include <cstdint>
#include <cstring>

namespace lsf::typescript::activation {
enum class ImportRawResult : uint32_t { None, I32, I64, F32, F64, Pointer, I8, U8, I16, U16 };

inline bool lift_raw_import(JSContext* cx, void* result, size_t bytes,
                            ImportRawResult kind, JS::MutableHandleValue out) {
  auto need = [bytes](size_t required) { return bytes == required; };
  switch (kind) {
  case ImportRawResult::I8: {
    if(!result || !need(1))break;
    int8_t value;std::memcpy(&value,result,1);out.setInt32(value);return true;
  }
  case ImportRawResult::U8: {
    if(!result || !need(1))break;
    uint8_t value;std::memcpy(&value,result,1);out.setInt32(value);return true;
  }
  case ImportRawResult::I16: {
    if(!result || !need(2))break;
    int16_t value;std::memcpy(&value,result,2);out.setInt32(value);return true;
  }
  case ImportRawResult::U16: {
    if(!result || !need(2))break;
    uint16_t value;std::memcpy(&value,result,2);out.setInt32(value);return true;
  }
  case ImportRawResult::None:
    if (!need(0)) break;
    out.setUndefined(); return true;
  case ImportRawResult::I32: {
    if (!result || !need(4)) break;
    int32_t value; std::memcpy(&value,result,sizeof(value)); out.setInt32(value); return true;
  }
  case ImportRawResult::I64: {
    if (!result || !need(8)) break;
    uint64_t value; std::memcpy(&value,result,sizeof(value));
    auto* bigint = JS::NumberToBigInt(cx,value);
    if (!bigint) return false;
    out.setBigInt(bigint); return true;
  }
  case ImportRawResult::F32: {
    if (!result || !need(4)) break;
    float value; std::memcpy(&value,result,sizeof(value)); out.setDouble(value); return true;
  }
  case ImportRawResult::F64: {
    if (!result || !need(8)) break;
    double value; std::memcpy(&value,result,sizeof(value)); out.setDouble(value); return true;
  }
  case ImportRawResult::Pointer:
    if (!result || bytes == 0) break;
    out.setInt32(static_cast<int32_t>(reinterpret_cast<uintptr_t>(result))); return true;
  }
  JS_ReportErrorASCII(cx,"activation-runtime-import-result-layout-invalid");
  return false;
}
} // namespace lsf::typescript::activation
