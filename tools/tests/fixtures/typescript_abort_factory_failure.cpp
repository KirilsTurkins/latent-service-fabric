// Execute the emitted guarded factory. Finite JSAPI doubles, not engine qualification.
#include <array>
#include <cassert>
#include <cstddef>
#include <cstdio>
#include <cstring>

struct JSContext { int pending = 0; };
struct JSString { const char* text; };
struct JSObject { bool native = true; };
struct Value {
  JSString* string = nullptr;
  JSObject* object = nullptr;
  void setString(JSString* text) { assert(text); string = text; }
};
struct RootedString {
  JSString* value;
  RootedString(JSContext*, JSString* text) : value(text) {}
  operator JSString*() const { return value; }
};
struct RootedObject {
  JSObject* value;
  explicit RootedObject(JSContext*, JSObject* object = nullptr) : value(object) {}
  operator JSObject*() const { return value; }
  JSObject& operator*() const { assert(value); return *value; }
};
struct RootedValue : Value {
  RootedValue(JSContext*, Value initial) : Value(initial) {}
};
static struct {
  int phase = 0, allocations = 0, lookups = 0, constructs = 0, slot_writes = 0;
  bool invalid_slot = false, lookup_with_pending = false;
  JSString text{""};
  JSObject constructor, exception;
} state;
static bool JS_IsExceptionPending(JSContext* cx) { return cx->pending != 0; }
static JSString* JS_NewStringCopyZ(JSContext* cx, const char* text) {
  ++state.allocations;
  if (state.phase == 1) { cx->pending = 101; return nullptr; }
  if (state.phase == 11) cx->pending = 111; // pointer does not imply a clean context
  state.text.text = text;
  return &state.text;
}
static JSObject* JS_GetConstructor(JSContext* cx, JSObject*) {
  state.lookup_with_pending |= cx->pending != 0;
  ++state.lookups;
  if (state.phase == 2) { cx->pending = 202; return nullptr; }
  if (state.phase == 3) return nullptr; // native false/no-pending lookup
  if (state.phase == 4) cx->pending = 204;
  return &state.constructor;
}
namespace JS {
template<size_t N> struct RootedValueArray {
  std::array<Value, N> values{};
  explicit RootedValueArray(JSContext*) {}
  Value& operator[](size_t index) { return values[index]; }
};
static Value ObjectValue(JSObject& object) { Value result; result.object = &object; return result; }
static bool Construct(JSContext* cx, RootedValue& ctor, RootedValueArray<2>& args,
                      RootedObject* out) {
  assert(!cx->pending && ctor.object == &state.constructor);
  assert(args[0].string && args[0].string == args[1].string);
  ++state.constructs;
  if (state.phase == 5) { cx->pending = 505; return false; }
  if (state.phase == 6) return false; // native termination
  if (state.phase == 7) cx->pending = 507; // invalid native true/pending
  if (state.phase == 8) state.exception.native = false;
  if (state.phase != 9) out->value = &state.exception;
  return true;
}
static void SetReservedSlot(JSObject* object, size_t, const Value& value) {
  state.invalid_slot |= !object || !object->native || value.string != &state.text;
  ++state.slot_writes;
}
}
namespace dom_exception {
struct DOMException {
  enum class Slots { Name, Message };
  inline static JSObject prototype;
  inline static JSObject* proto_obj = &prototype;
  static bool is_instance(JSObject* object) { return object && object->native; }
};
}
namespace api {
namespace Errors { constexpr int TypeError = 1; }
static bool throw_error(JSContext* cx, int, const char*, const char*, const char*) {
  cx->pending = 808; return false;
}
}
// INSERT_EMITTED_ABORT_FACTORY
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  struct Case { const char* name; int phase; int pending; int lookups; int constructs; };
  const Case cases[] = {
    {"success-abort", 0, 0, 1, 1}, {"success-timeout", 0, 0, 1, 1},
    {"string-pending-abort", 11, 111, 0, 0}, {"string-pending-timeout", 11, 111, 0, 0},
    {"string-oom", 1, 101, 0, 0}, {"constructor-lookup-failure", 2, 202, 1, 0},
    {"constructor-lookup-terminal", 3, 0, 1, 0}, {"constructor-lookup-pending", 4, 204, 1, 0},
    {"constructor-throw", 5, 505, 1, 1}, {"constructor-terminal", 6, 0, 1, 1},
    {"constructor-pending", 7, 507, 1, 1}, {"constructor-wrong-class", 8, 808, 1, 1},
    {"constructor-null-result", 9, 808, 1, 1}, {"entry-pending", 10, 999, 0, 0},
  };
  for (const auto& selected : cases) {
    if (std::strcmp(argv[1], selected.name)) continue;
    state.phase = selected.phase;
    JSContext cx;
    if (selected.phase == 10) cx.pending = 999;
    const char* reason = std::strstr(argv[1], "timeout") != nullptr ? "TimeoutError" : "AbortError";
    JSObject* result = create_abort_exception(&cx, reason);
    bool passed = (result != nullptr) == (selected.phase == 0) &&
        cx.pending == selected.pending && state.lookups == selected.lookups &&
        state.constructs == selected.constructs && !state.invalid_slot && !state.lookup_with_pending &&
        state.slot_writes == (selected.phase == 0 ? 2 : 0) &&
        state.allocations == (selected.phase == 10 ? 0 : 1);
    if (result) passed &= !std::strcmp(state.text.text, reason);
    std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
                argv[1], passed ? "true" : "false");
    return passed ? 0 : 1;
  }
  return 2;
}
