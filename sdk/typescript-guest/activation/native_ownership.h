#pragma once
#include "js/TypeDecls.h"
#include <cstdint>

namespace lsf::typescript::activation {

struct Token { uint64_t generation = 0; uint64_t id = 0; };
struct JobOwners {
  Token task{};
  Token queued{};
  bool task_live = false;
  bool queued_live = false;
  bool compiler_snapshot = false;
};
struct NativeOwner { Token token{}; bool live = false; };

class PromiseAccounting {
public:
  virtual ~PromiseAccounting() = default;
  virtual bool beforeAllocate(JSContext*, NativeOwner&) = 0;
  virtual bool acknowledgeRetirement(JSContext*, NativeOwner&) = 0;
};

} // namespace lsf::typescript::activation
