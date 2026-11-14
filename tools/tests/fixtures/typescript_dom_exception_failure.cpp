// Exact emitted native DOMException functions, with fault-injecting JSAPI doubles.
// Not a SpiderMonkey collector or signed-component qualification.
#include <cassert>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <vector>
namespace std { template<class E> constexpr auto to_underlying(E value) { return static_cast<underlying_type_t<E>>(value); } }
struct JSObject;
struct JSString { std::string text; };
static unsigned invalid_access = 0, late_allocations = 0, slot_writes = 0;
namespace JS {
struct Value {
  JSString* string = nullptr;
  JSObject* object = nullptr;
  bool defined = false;
  void setString(JSString* value) { if (!value) ++invalid_access; string = value; defined = true; }
  void setObject(JSObject& value) { object = &value; defined = true; }
};
}
struct JSObject { bool native = true; JS::Value slots[2]; };
static JSObject invalid_object{false, {}}, constructor_object{false, {}};
static JSString empty_string{""};
struct JSContext {
  unsigned pending = 0, strings = 0, objects = 0, gets = 0, constructs = 0, conversions = 0;
  unsigned fail_string = 0, fail_conversion = 0;
  bool string_pending = false, object_failure = false, object_pending = false;
  bool getter_failure = false, getter_pending = false, fatal = false, wrong_class = false;
  bool construct_failure = false, construct_pending = false, null_result = false;
  bool reenter = false, reentered = false, returned = false;
  JSObject* thrown = nullptr;
  std::vector<void*> roots;
  std::vector<std::unique_ptr<JSString>> string_heap;
  std::vector<std::unique_ptr<JSObject>> object_heap;
};
[[maybe_unused]] static bool JS_IsExceptionPending(JSContext* cx) { return cx->pending != 0; }
struct Root {
  JSContext* cx;
  explicit Root(JSContext* cx) : cx(cx) { cx->roots.push_back(this); }
  ~Root() { if (cx->roots.empty() || cx->roots.back() != this) ++invalid_access; else cx->roots.pop_back(); }
};
namespace JS {
struct RootedString : Root {
  JSString* value;
  RootedString(JSContext* cx, JSString* value) : Root(cx), value(value) {}
  operator JSString*() const { return value; }
};
struct RootedObject : Root {
  JSObject* value;
  explicit RootedObject(JSContext* cx, JSObject* value = nullptr) : Root(cx), value(value) {}
  operator JSObject*() const { return value; }
  JSObject& operator*() const { if (!value) { ++invalid_access; return invalid_object; } return *value; }
  void set(JSObject* next) { value = next; }
};
struct RootedValue : Root, Value {
  RootedValue(JSContext* cx, Value value) : Root(cx), Value(value) {}
};
template<size_t N> struct RootedValueArray : Root {
  Value values[N];
  explicit RootedValueArray(JSContext* cx) : Root(cx) {}
  Value& operator[](size_t i) { return values[i]; }
};
static Value StringValue(JSString* value) { Value result; result.setString(value); return result; }
static Value ObjectValue(JSObject& value) { Value result; result.setObject(value); return result; }
static void SetReservedSlot(JSObject* object, size_t slot, Value value) {
  if (!object || !object->native || slot >= 2) { ++invalid_access; return; }
  ++slot_writes; object->slots[slot] = value;
}
static bool Construct(JSContext*, const Value&, const RootedValueArray<2>&, RootedObject*);
}
static JSString* JS_NewStringCopyN(JSContext* cx, const char* text, size_t length) {
  ++cx->strings;
  if (cx->returned) ++late_allocations;
  if (cx->strings == cx->fail_string) { if (!cx->fatal) cx->pending = 11; return nullptr; }
  auto value = std::make_unique<JSString>(); value->text.assign(text, length);
  auto* result = value.get(); cx->string_heap.push_back(std::move(value));
  if (cx->string_pending) cx->pending = 12;
  return result;
}
static JSString* JS_NewStringCopyZ(JSContext* cx, const char* text) { return JS_NewStringCopyN(cx, text, std::strlen(text)); }
static JSString* JS_GetEmptyString(JSContext*) { return &empty_string; }
[[maybe_unused]] static JS::Value JS_GetEmptyStringValue(JSContext* cx) { return JS::StringValue(JS_GetEmptyString(cx)); }
static JSObject* JS_GetConstructor(JSContext* cx, JSObject*) {
  ++cx->gets;
  if (cx->getter_failure) { if (!cx->fatal) cx->pending = 21; return nullptr; }
  if (cx->getter_pending) cx->pending = 22;
  return &constructor_object;
}
static void JS_SetPendingException(JSContext* cx, const JS::Value& value) { cx->pending = 31; cx->thrown = value.object; }
struct CallArgs {
  unsigned argc; JS::Value* values;
  bool hasDefined(unsigned i) const { return i < argc && values[i].defined; }
  JS::Value get(unsigned i) const { return i < argc ? values[i] : JS::Value{}; }
  JS::Value& rval() { return values[2]; }
};
#define CTOR_HEADER(name, count) CallArgs args{argc, vp}
static JSObject* JS_NewObjectForConstructor(JSContext* cx, const int*, CallArgs&) {
  ++cx->objects;
  if (cx->object_failure) { if (!cx->fatal) cx->pending = 41; return nullptr; }
  auto value = std::make_unique<JSObject>(); auto* result = value.get();
  cx->object_heap.push_back(std::move(value));
  if (cx->object_pending) cx->pending = 42;
  return result;
}
namespace JS {
static JSString* ToString(JSContext* cx, Value value) {
  ++cx->conversions;
  if (cx->conversions == cx->fail_conversion) { if (!cx->fatal) cx->pending = 51; return nullptr; }
  return value.string ? value.string : JS_NewStringCopyZ(cx, "converted");
}
}
namespace api {
enum class Errors { TypeError };
template<class... Args> static bool throw_error(JSContext* cx, Errors, Args...) { cx->pending = 61; return false; }
}
struct DOMException {
  enum class Slots { Message, Name };
  inline static int class_ = 0;
  inline static JSObject* proto_obj = &invalid_object;
  static bool is_instance(JSObject* value) { return value && value->native; }
  static JSObject* create(JSContext*, std::string_view, std::string_view);
  static bool raise(JSContext*, std::string_view, std::string_view);
  static bool constructor(JSContext*, unsigned, JS::Value*);
};

// INSERT_EMITTED_DOM_EXCEPTION

namespace JS {
static bool Construct(JSContext* cx, const Value& ctor, const RootedValueArray<2>& values, RootedObject* output) {
  ++cx->constructs;
  if (cx->pending || ctor.object != &constructor_object) { ++invalid_access; return false; }
  if (cx->construct_failure) { if (!cx->fatal) cx->pending = 71; return false; }
  if (cx->null_result) { cx->returned = true; return true; }
  if (cx->reenter && !cx->reentered) {
    cx->reentered = true;
    auto* nested = DOMException::create(cx, "nested", "NestedError");
    if (!nested) return false;
    cx->returned = false;
  }
  JS::Value arguments[3] = {values.values[0], values.values[1], {}};
  if (!DOMException::constructor(cx, 2, arguments)) return false;
  output->set(arguments[2].object);
  if (cx->wrong_class) output->value->native = false;
  if (cx->construct_pending) cx->pending = 72;
  cx->returned = true;
  return true;
}
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  const std::string_view selected(argv[1]);
  const auto is = [&](std::string_view value) { return selected == value; };
  const bool raise = selected.substr(0, 6) == "raise-";
  const bool constructor = selected.substr(0, 5) == "ctor-";
  JSContext cx;
  const std::string message("message\0tail", 12);
  bool passed = false;
  if (is("factory-first-oom") || is("raise-first-oom") || is("ctor-default-oom")) cx.fail_string = 1;
  if (is("factory-second-oom")) cx.fail_string = 2;
  if (is("factory-string-pending")) cx.string_pending = true;
  if (is("factory-getter-error") || is("raise-getter-error")) cx.getter_failure = true;
  if (is("factory-getter-fatal") || is("raise-getter-fatal")) cx.getter_failure = cx.fatal = true;
  if (is("factory-getter-pending")) cx.getter_pending = true;
  if (is("factory-construct-error") || is("raise-construct-error")) cx.construct_failure = true;
  if (is("factory-construct-fatal") || is("raise-construct-fatal")) cx.construct_failure = cx.fatal = true;
  if (is("factory-construct-pending")) cx.construct_pending = true;
  if (is("factory-wrong-class") || is("raise-wrong-class")) cx.wrong_class = true;
  if (is("factory-null-result")) cx.null_result = true;
  if (is("factory-reentry")) cx.reenter = true;
  if (is("factory-entry-pending") || is("raise-entry-pending") || is("ctor-entry-pending")) cx.pending = 81;
  if (constructor) {
    JS::Value values[3];
    unsigned count = 0;
    if (is("ctor-conversion-error") || is("ctor-name-error") || is("ctor-conversion-pending")) {
      count = 2; values[0].defined = values[1].defined = true;
      if (is("ctor-conversion-pending")) cx.string_pending = true;
      else cx.fail_conversion = is("ctor-name-error") ? 2 : 1;
    }
    if (is("ctor-object-oom")) cx.object_failure = true;
    if (is("ctor-object-pending")) cx.object_pending = true;
    const bool ok = DOMException::constructor(&cx, count, values);
    if (is("ctor-normal")) passed = ok && !cx.pending && values[2].object &&
        values[2].object->slots[0].string->text.empty() && values[2].object->slots[1].string->text == "Error";
    else passed = !ok && cx.pending && !values[2].object;
    if (is("ctor-entry-pending")) passed &= cx.pending == 81 && cx.objects == 0 && cx.strings == 0;
  } else {
    JSObject* result = nullptr;
    bool ok = false;
    if (raise) { ok = DOMException::raise(&cx, message, "AbortError"); result = cx.thrown; }
    else result = DOMException::create(&cx, message, "AbortError");
    if (is("factory-normal") || is("factory-reentry") || is("raise-normal")) {
      passed = result && result->native && result->slots[0].string && result->slots[1].string &&
          result->slots[0].string->text == message && result->slots[1].string->text == "AbortError" &&
          (raise ? !ok && cx.pending == 31 : cx.pending == 0) && !late_allocations;
      if (is("factory-reentry")) passed &= cx.reentered && cx.constructs == 2;
    } else {
      passed = !result && !ok && (cx.fatal ? cx.pending == 0 : cx.pending != 0);
      if (cx.fail_string) passed &= cx.pending == 11 && cx.gets == 0 && cx.constructs == 0;
      if (cx.getter_failure) passed &= cx.constructs == 0 && cx.pending == (cx.fatal ? 0 : 21);
      if (cx.getter_pending) passed &= cx.constructs == 0 && cx.pending == 22;
      if (cx.construct_failure) passed &= cx.pending == (cx.fatal ? 0 : 71);
      if (cx.construct_pending) passed &= cx.pending == 72;
      if (cx.wrong_class || cx.null_result) passed &= cx.pending == 61;
      if (is("factory-entry-pending") || is("raise-entry-pending"))
        passed &= cx.pending == 81 && cx.strings == 0 && cx.gets == 0 && cx.constructs == 0;
    }
  }
  passed &= invalid_access == 0 && cx.roots.empty();
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n", argv[1], passed ? "true" : "false");
  return passed ? 0 : 1;
}
