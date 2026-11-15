// A real Wasm trap witness using the unchanged production lease templates.
// No JS engine, collector, native heap allocator or host ledger is modeled as qualified.
namespace lsf::typescript::activation {
struct Records {
  struct Record { bool physical = true; bool complete = false; };
  static void physicallyRetired(Record* record);
  static void frameRetired(Record* record);
};
// INSERT_LEASES
static Records::Record record;
static unsigned body_destroyed, retired, callbacks, early;
void Records::physicallyRetired(Record* item) { if (item) item->physical = false; }
void Records::frameRetired(Record* item) {
  if (!item) return;
  early += !body_destroyed;
  item->physical = false;
  item->complete = true;
  ++retired;
}
struct Body { ~Body() { ++body_destroyed; } };
extern "C" __attribute__((export_name("run"))) void run(unsigned trap) {
  NativeFrameLease<Records> custody;
  if (!custody.lease().bind(&record)) __builtin_trap();
  Body body;
  ++callbacks;
  if (trap) __builtin_trap();
  ++callbacks;
}
extern "C" __attribute__((export_name("observe"))) unsigned observe() {
  return (record.physical ? 1U : 0U) | (record.complete ? 2U : 0U) |
         body_destroyed << 4 | retired << 8 | callbacks << 12 | early << 16;
}
}
