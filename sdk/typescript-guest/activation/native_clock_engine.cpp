// Selected native clock module; existing Promise engine source stays unchanged.
#include "native_clocks.h"
#include "jsapi.h"

namespace lsf::typescript::activation {
namespace {
Clocks clocks;
bool wall_clock_value(JSContext* cx, unsigned argc, JS::Value* vp) {
  const auto args = JS::CallArgsFromVp(argc, vp);
  double value = 0;
  if (!clocks.wall(cx, value)) return false;
  args.rval().setDouble(value);
  return true;
}
bool performance_value(JSContext* cx, unsigned argc, JS::Value* vp, bool origin) {
  const auto args = JS::CallArgsFromVp(argc, vp);
  double elapsed = 0, epoch = 0;
  if (!clocks.performance(cx, elapsed, epoch)) return false;
  args.rval().setDouble(origin ? epoch : elapsed);
  return true;
}
bool monotonic_clock_value(JSContext* cx, unsigned argc, JS::Value* vp) {
  return performance_value(cx, argc, vp, false);
}
bool performance_origin_value(JSContext* cx, unsigned argc, JS::Value* vp) {
  return performance_value(cx, argc, vp, true);
}
}

bool install_clock_globals(JSContext* cx, JS::HandleObject global) {
  JS::RootedObject bridge(cx, JS_NewPlainObject(cx));
  if (!bridge || !JS_DefineFunction(cx, bridge, "wall", wall_clock_value, 0, 0) ||
      !JS_DefineFunction(cx, bridge, "now", monotonic_clock_value, 0, 0) ||
      !JS_DefineFunction(cx, bridge, "origin", performance_origin_value, 0, 0) ||
      !JS_DefineProperty(cx, global, "__lsfSelectedClockBridge", bridge, 0))
    return false;
  static constexpr char source[] =
#include "clock_globals.inc"
      ;
  JS::CompileOptions options(cx);
  options.setFileAndLine("lsf:typescript-clock-globals.v1", 1);
  JS::SourceText<mozilla::Utf8Unit> text;
  JS::RootedValue result(cx);
  return text.init(cx, source, sizeof(source)-1, JS::SourceOwnership::Borrowed) &&
         JS::Evaluate(cx, options, text, &result);
}

} // namespace lsf::typescript::activation
