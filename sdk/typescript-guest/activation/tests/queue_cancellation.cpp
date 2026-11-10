// Production JobQueue with finite JS/broker doubles. This observes exact owner
// tokens and callable roots, not SpiderMonkey, a Wasm trap, or Store retirement.
#include "../native_job_queue.h"
#include <array>
#include <cstdio>
#include <cstring>

using namespace lsf::typescript::activation;
namespace {
const char* selected = nullptr;
bool passed = true;
#define CHECK(condition) do { if (!(condition)) { \
  std::fprintf(stderr, "%s:%d: %s\n", selected, __LINE__, #condition); passed = false; \
} } while (false)
struct Owner { bool task = false, queued = false; unsigned refunds = 0; };
struct Jobs final : Accounting {
  std::array<Owner, 8> owners{};
  unsigned admissions = 0, entries = 0, completions = 0, cancellations = 0;
  unsigned retirement_attempts = 0;
  bool refuse = false;
  bool admit(JSContext*, JobOwners& out) override {
    if (admissions == owners.size() || out.task_live || out.queued_live) return false;
    const auto id = ++admissions;
    owners[id - 1] = {true, true, 0};
    out.task = out.queued = {17, id};
    out.task_live = out.queued_live = true;
    return true;
  }
  bool started(JSContext*, JobOwners& out) override {
    ++entries;
    CHECK(out.task.generation == 17 && out.queued.generation == 17);
    auto& original = owners.at(out.task.id - 1);
    CHECK(original.queued && out.queued_live);
    original.queued = out.queued_live = false;
    return true;
  }
  bool release(JobOwners& out) {
    auto& original = owners.at(out.task.id - 1);
    CHECK(original.task && out.task_live && original.refunds == 0);
    original.task = original.queued = false;
    out.task_live = out.queued_live = false;
    ++original.refunds;
    return true;
  }
  bool rollback(JSContext*, JobOwners& out) override { return release(out); }
  bool completed(JSContext*, JobOwners& out) override {
    ++retirement_attempts;
    // The executing job root has died, while the queued sibling still owns
    // its root. A refused ACK must retain precisely the first task token.
    CHECK(fixture::roots == 1 && out.task.id == 1 && !out.queued_live);
    if (refuse) return false;
    ++completions;
    return release(out);
  }
  bool cancelled(JSContext*, JobOwners& out) override {
    CHECK(fixture::roots == 0 && out.task.id == 2 && out.queued_live);
    ++cancellations;
    return release(out);
  }
};
Jobs* jobs = nullptr;
JobQueue* queue = nullptr;
JSObject late;
unsigned notifications = 0;
void retired(void*, bool) { ++notifications; }

bool during_callback(JSContext* cx) {
  CHECK(fixture::calls == 1 && fixture::roots == 2);
  const auto attempts = jobs->retirement_attempts;
  CHECK(!queue->cancelQueued(cx));
  CHECK(queue->isDrainingStopped() && !queue->empty());
  CHECK(jobs->owners[0].task && jobs->owners[1].task && jobs->owners[1].queued);
  CHECK(jobs->retirement_attempts == attempts && fixture::roots == 2);
  // Neither a repeated cancellation nor a nested checkpoint retires a frame.
  CHECK(!queue->cancelQueued(cx));
  queue->runJobs(cx);
  CHECK(fixture::calls == 1 && fixture::roots == 2);

  const auto admitted = jobs->admissions;
  CHECK(!queue->enqueuePromiseJob(cx, nullptr, &late, nullptr, nullptr));
  CHECK(jobs->admissions == admitted && fixture::roots == 2);
  CHECK(JS_IsExceptionPending(cx));
  JS_ClearPendingException(cx);
  JobOwners prepaid;
  CHECK(jobs->admit(cx, prepaid));
  const auto id = prepaid.task.id;
  CHECK(!queue->enqueueAdmitted(cx, &late, prepaid, retired, nullptr));
  CHECK(prepaid.task_live && prepaid.queued_live && prepaid.task.id == id);
  CHECK(notifications == 0 && fixture::roots == 2);
  // A closed enqueue leaves this external caller, not the queue, responsible.
  if (prepaid.task_live) CHECK(jobs->rollback(cx, prepaid));
  JS_ClearPendingException(cx);
  if (std::strstr(selected, "exception")) {
    JS_ReportErrorASCII(cx, "original-callback-exception");
    return false;
  }
  return passed && !std::strstr(selected, "false");
}
}
int main(int argc, char** argv) {
  if (argc != 2) return 2;
  selected = argv[1];
  if (std::strcmp(selected, "reentrant-cancel-success") &&
      std::strcmp(selected, "reentrant-cancel-false") &&
      std::strcmp(selected, "reentrant-cancel-exception") &&
      std::strcmp(selected, "reentrant-cancel-ack-refusal")) return 2;
  JSContext cx;
  Jobs ledger;
  JobQueue actual(ledger);
  jobs = &ledger; queue = &actual;
  ledger.refuse = std::strstr(selected, "refusal") != nullptr;
  JSObject first, sibling;
  CHECK(actual.enqueuePromiseJob(&cx, nullptr, &first, nullptr, nullptr));
  CHECK(actual.enqueuePromiseJob(&cx, nullptr, &sibling, nullptr, nullptr));
  CHECK(ledger.admissions == 2 && fixture::roots == 2);
  fixture::callback = during_callback;
  actual.runJobs(&cx);
  CHECK(actual.isDrainingStopped() && !actual.empty());
  CHECK(fixture::calls == 1 && ledger.entries == 1 && fixture::roots == 1);
  CHECK(ledger.owners[1].task && ledger.owners[1].queued);
  CHECK(notifications == 0);
  if (ledger.refuse) {
    CHECK(ledger.owners[0].task && ledger.owners[0].refunds == 0);
    CHECK(!actual.cancelQueued(&cx));
    CHECK(ledger.owners[1].task && fixture::roots == 1);
    ledger.refuse = false;
  }
  CHECK(actual.cancelQueued(&cx) && actual.empty());
  CHECK(actual.cancelQueued(&cx));
  CHECK(ledger.completions == 1 && ledger.cancellations == 1);
  CHECK(fixture::roots == 0 && fixture::calls == 1 && notifications == 0);
  for (unsigned i = 0; i < ledger.admissions; ++i) {
    CHECK(!ledger.owners[i].task && !ledger.owners[i].queued && ledger.owners[i].refunds == 1);
  }
  if (std::strstr(selected, "exception")) {
    CHECK(cx.exception && !std::strcmp(cx.detail, "original-callback-exception"));
  } else CHECK(!cx.exception);
  std::printf("{\"case\":\"%s\",\"passed\":%s,\"engineQualified\":false,"
              "\"callbacks\":%u,\"retainedRoots\":%u,\"retiredTasks\":%u}\n",
              selected, passed ? "true" : "false", fixture::calls, fixture::roots,
              ledger.completions + ledger.cancellations);
  return passed ? 0 : 1;
}
