// Executes the emitted EventTarget registration body with finite lifetime and
// allocation doubles. This is not a SpiderMonkey or signed-guest witness.
#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

struct JSContext {};
struct Signal;
struct Value {
  int id = 0;
  Signal* signal = nullptr;
  bool isObject() const { return signal != nullptr; }
  Signal& toObject() const { return *signal; }
  bool operator==(const Value& other) const { return id == other.id && signal == other.signal; }
};
struct HeapValue {
  Value value;
  HeapValue& operator=(const Value& other) { value = other; return *this; }
  Value get() const { return value; }
};
template<class T> class RefPtr {
  std::shared_ptr<T> value_;
public:
  RefPtr() = default;
  RefPtr(T* value) : value_(value) {}
  RefPtr& operator=(T* value) { value_.reset(value); return *this; }
  explicit operator bool() const { return bool(value_); }
  T* operator->() const { return value_.get(); }
  T* get() const { return value_.get(); }
};
namespace lsf::typescript::activation {
inline unsigned admissions = 0, live = 0, deny_at = 0;
struct NativeObjectLease {
  bool accepted = false;
  NativeObjectLease() = default;
  NativeObjectLease(const NativeObjectLease&) = delete;
  NativeObjectLease(NativeObjectLease&& other) : accepted(other.accepted) { other.accepted = false; }
  ~NativeObjectLease() { if (accepted) --live; }
};
bool admit_native_object(JSContext*, NativeObjectLease& lease) {
  ++admissions;
  if (admissions == deny_at) return false;
  lease.accepted = true; ++live; return true;
}
}
struct EventListener {
  lsf::typescript::activation::NativeObjectLease owner;
  explicit EventListener(lsf::typescript::activation::NativeObjectLease&& value)
      : owner(std::move(value)) {}
  HeapValue callback, signal;
  std::string type;
  bool passive = false, capture = false, once = false, removed = false;
};
template<class T, class... Args> T* js_new(Args&&... args) {
  return new T(std::forward<Args>(args)...);
}
struct Terminator {
  lsf::typescript::activation::NativeObjectLease owner;
  Terminator(lsf::typescript::activation::NativeObjectLease&& value,
             JSContext*, void*, Value, Value, Value) : owner(std::move(value)) {}
};
namespace js {
template<class T, class... Args> std::unique_ptr<T> MakeUnique(Args&&... args) {
  return std::make_unique<T>(std::forward<Args>(args)...);
}
}
struct Signal {
  bool aborted = false, refuse_algorithm = false;
  std::vector<std::unique_ptr<Terminator>> algorithms;
};
struct RootedObject {
  Signal* value;
  RootedObject(JSContext*, Signal* object) : value(object) {}
};
struct AbortSignal {
  static bool is_instance(Value value) { return value.signal != nullptr; }
  static bool is_aborted(RootedObject value) { return value.value->aborted; }
  static bool add_algorithm(RootedObject value, std::unique_ptr<Terminator> algorithm) {
    if (value.value->aborted || value.value->refuse_algorithm) return false;
    value.value->algorithms.push_back(std::move(algorithm));
    return true;
  }
};
inline bool out_of_memory = false;
void JS_ReportOutOfMemory(JSContext*) { out_of_memory = true; }
struct List {
  std::array<RefPtr<EventListener>, 8> values;
  size_t size = 0, reserved = 0;
  bool refuse_reserve = false;
  RefPtr<EventListener>* begin() { return values.data(); }
  RefPtr<EventListener>* end() { return values.data() + size; }
  size_t length() const { return size; }
  bool reserve(size_t count) {
    if (refuse_reserve || count > values.size()) return false;
    if (count > reserved) reserved = count;
    return true;
  }
  bool append(const RefPtr<EventListener>& value) {
    if (!reserve(size + 1)) return false;
    values[size++] = value;
    return true;
  }
  void infallibleAppend(const RefPtr<EventListener>& value) {
    if (size >= reserved) std::abort();
    values[size++] = value;
  }
  void erase(RefPtr<EventListener>* item) {
    const auto index = static_cast<size_t>(item - begin());
    for (size_t i = index; i + 1 < size; ++i) values[i] = values[i + 1];
    values[--size] = RefPtr<EventListener>();
  }
};

bool emitted_body(JSContext* cx, List* list, Value callback_val, Value signal_val) {
  const std::string_view type = "event";
  const Value type_val{}, opts_val{};
  void* self = nullptr;
  const bool capture = false, passive = false, once = false;
  // INSERT_EMITTED_EVENT_BODY
  return true;
}

RefPtr<EventListener> existing(int id, bool removed) {
  RefPtr<EventListener> result = new EventListener(lsf::typescript::activation::NativeObjectLease{});
  result->type = "event";
  result->callback = Value{id, nullptr};
  result->removed = removed;
  return result;
}

int main(int argc, char** argv) {
  if (argc != 2) return 2;
  using namespace lsf::typescript::activation;
  JSContext cx;
  List list;
  Signal signal;
  const Value callback{1, nullptr};
  const Value with_signal{0, &signal};
  const char* name = argv[1];
  bool passed = false;
  if (!std::strcmp(name, "native-refusal-before-listener-publication")) {
    deny_at = 2;
    passed = !emitted_body(&cx, &list, callback, with_signal) && list.size == 0 &&
             signal.algorithms.empty() && live == 0 && admissions == 2;
  } else if (!std::strcmp(name, "algorithm-refusal-before-listener-publication")) {
    signal.refuse_algorithm = true;
    passed = !emitted_body(&cx, &list, callback, with_signal) && list.size == 0 &&
             signal.algorithms.empty() && live == 0 && out_of_memory;
  } else if (!std::strcmp(name, "vector-refusal-before-algorithm-publication")) {
    list.refuse_reserve = true;
    passed = !emitted_body(&cx, &list, callback, with_signal) && list.size == 0 &&
             signal.algorithms.empty() && live == 0 && admissions == 1 && out_of_memory;
  } else if (!std::strcmp(name, "successful-registration-retains-both-owners")) {
    passed = emitted_body(&cx, &list, callback, with_signal) && list.size == 1 &&
             signal.algorithms.size() == 1 && live == 2 && !list.values[0]->removed;
  } else if (!std::strcmp(name, "once-listener-reinserted-after-original-neighbor")) {
    auto first = existing(1, true);
    auto second = existing(2, false);
    if (!list.append(first) || !list.append(second)) return 3;
    passed = emitted_body(&cx, &list, callback, Value{}) && list.size == 2 &&
             list.values[0].get() == second.get() && list.values[1].get() == first.get() &&
             !first->removed;
  } else if (!std::strcmp(name, "reactivation-refusal-keeps-existing-listener")) {
    auto first = existing(1, true);
    auto second = existing(2, false);
    if (!list.append(first) || !list.append(second)) return 3;
    deny_at = 1;
    passed = !emitted_body(&cx, &list, callback, with_signal) && list.size == 2 &&
             list.values[0].get() == first.get() && list.values[1].get() == second.get() &&
             first->removed && signal.algorithms.empty() && live == 0;
  } else if (!std::strcmp(name, "signal-aborted-during-type-conversion")) {
    signal.aborted = true;
    passed = emitted_body(&cx, &list, callback, with_signal) && list.size == 0 &&
             signal.algorithms.empty() && live == 0;
  } else return 2;
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false}\n",
              name, passed ? "true" : "false");
  return passed ? 0 : 1;
}
