"""Pinned intrinsic Promise allocation/lifetime hooks for the opt-in engine.

These hooks require a source-built SpiderMonkey library. The previously linked
upstream library and its queue controls cannot qualify this distinct derivation.
"""
from __future__ import annotations

import hashlib

from tools.typescript_guest.activation_engine import identity, replace_once, FIREFOX_COMMIT

PREIMAGES = {
    "js/src/builtin/Promise.cpp": "03a0a7d9bd2a2bdd6b373486c9e86c99f35baae9d76814048c873bd8004d0649",
    "js/src/vm/PromiseObject.h": "92a691bff5bb06319c5e95a6ab21fe0e4cdbe32fc18cd2f51f748033d3d9cffd",
}

HOOK_SUPPORT = b'''
// Opt-in embedding hooks. Object slots, classes, GC policy and the original
// constructor/reaction implementation keep their original archived ABI.
static JSContext* activationPromiseContext = nullptr;
static const JS::ActivationPromiseHooks* activationPromiseHooks = nullptr;

JS_PUBLIC_API bool JS::SetActivationPromiseHooks(
    JSContext* cx, const JS::ActivationPromiseHooks* hooks) {
  if (!hooks || !hooks->beforeAllocate || !hooks->allocationFailed ||
      !hooks->created || !hooks->settled ||
      !hooks->beforeReactionAllocate || !hooks->reactionAllocationFailed ||
      !hooks->reactionCreated || !hooks->reactionRecord ||
      activationPromiseHooks) {
    JS_ReportErrorASCII(cx, "activation-runtime-promise-hooks-install-invalid");
    return false;
  }
  activationPromiseContext = cx;
  activationPromiseHooks = hooks;
  return true;
}
'''


def derive_promise_lifecycle(original: dict[str, bytes], header: bytes) -> tuple[dict[str, bytes], dict]:
    """Create a distinct carrier with mandatory pre-allocation/lifetime hooks.

    Installation occurs before content evaluation. Unsupported pending reaction
    granularity and other profile gates remain explicit in the returned receipt.
    No process, network, application source or existing compiler is modified.
    """
    before = identity(original)
    if not PREIMAGES.keys() <= original.keys():
        raise ValueError("missing pinned intrinsic Promise sources")
    for name, expected in PREIMAGES.items():
        if hashlib.sha256(original[name]).hexdigest() != expected:
            raise ValueError("unreviewed original Promise source:" + name)
    if not isinstance(header, bytes) or b"struct ActivationPromiseHooks" not in header:
        raise ValueError("explicit native Promise hook ABI required")
    result = dict(original)

    source = result["js/src/builtin/Promise.cpp"]
    source = replace_once(source, b'#include "builtin/Promise.h"\n',
        b'#include "builtin/Promise.h"\n#include "js/ActivationPromiseHooks.h"\n', "promise-hook-include")
    source = replace_once(source, b"using namespace js;\n", b"using namespace js;\n" + HOOK_SUPPORT,
                          "native-hook-install")
    source = replace_once(source,
        b"  PromiseObject* promise = NewObjectWithClassProto<PromiseObject>(cx, proto);\n"
        b"  if (!promise) {\n    return nullptr;\n  }\n",
        b"  void* activationRecord = nullptr;\n"
        b"  const bool activationObserved = activationPromiseHooks &&\n"
        b"      activationPromiseContext == cx;\n"
        b"  if (activationObserved &&\n"
        b"      !activationPromiseHooks->beforeAllocate(cx, &activationRecord)) {\n"
        b"    return nullptr;\n  }\n"
        b"  PromiseObject* promise = NewObjectWithClassProto<PromiseObject>(cx, proto);\n"
        b"  if (!promise) {\n"
        b"    if (activationObserved) activationPromiseHooks->allocationFailed(activationRecord);\n"
        b"    return nullptr;\n  }\n"
        b"  if (activationObserved) activationPromiseHooks->created(cx, promise, activationRecord);\n",
        "admit-before-intrinsic-allocation")
    source = replace_once(source,
        b"  promise->setFixedSlot(PromiseSlot_RejectFunction, UndefinedValue());\n",
        b"  promise->setFixedSlot(PromiseSlot_RejectFunction, UndefinedValue());\n"
        b"  if (activationPromiseHooks && activationPromiseContext == cx) {\n"
        b"    activationPromiseHooks->settled(cx, promise);\n  }\n", "actual-state-settlement")
    source = replace_once(source,
        b"  PromiseReactionRecord* reaction =\n"
        b"      NewBuiltinClassInstance<PromiseReactionRecord>(cx);\n"
        b"  if (!reaction) {\n    return nullptr;\n  }\n",
        b"  void* activationRecord = nullptr;\n"
        b"  const bool activationObserved = activationPromiseHooks &&\n"
        b"      activationPromiseContext == cx;\n"
        b"  if (activationObserved &&\n"
        b"      !activationPromiseHooks->beforeReactionAllocate(cx, &activationRecord)) {\n"
        b"    return nullptr;\n  }\n"
        b"  PromiseReactionRecord* reaction =\n"
        b"      NewBuiltinClassInstance<PromiseReactionRecord>(cx);\n"
        b"  if (!reaction) {\n"
        b"    if (activationObserved) activationPromiseHooks->reactionAllocationFailed(activationRecord);\n"
        b"    return nullptr;\n  }\n"
        b"  if (activationObserved) activationPromiseHooks->reactionCreated(cx, reaction, activationRecord);\n",
        "admit-before-intrinsic-reaction-allocation")
    source = replace_once(source,
        b"static bool PromiseReactionJob(JSContext* cx, unsigned argc, Value* vp);\n",
        b"static bool PromiseReactionJob(JSContext* cx, unsigned argc, Value* vp);\n\n"
        b"JS_PUBLIC_API bool JS::ActivationReactionRecordForJob(\n"
        b"    JSContext* cx, HandleObject job, void** output) {\n"
        b"  *output = nullptr;\n"
        b"  if (!job->is<JSFunction>() ||\n"
        b"      job->as<JSFunction>().maybeNative() != PromiseReactionJob) return true;\n"
        b"  const Value& value = job->as<JSFunction>().getExtendedSlot(ReactionJobSlot_ReactionRecord);\n"
        b"  JSObject* reaction = UncheckedUnwrap(&value.toObject());\n"
        b"  if (JS_IsDeadWrapper(reaction) || !reaction->is<PromiseReactionRecord>() ||\n"
        b"      activationPromiseContext != cx || !activationPromiseHooks) {\n"
        b"    JS_ReportErrorASCII(cx, \"activation-runtime-reaction-job-identity-invalid\");\n"
        b"    return false;\n  }\n"
        b"  *output = activationPromiseHooks->reactionRecord(cx, reaction);\n"
        b"  if (!*output) {\n"
        b"    JS_ReportErrorASCII(cx, \"activation-runtime-reaction-job-unadmitted\");\n"
        b"    return false;\n  }\n  return true;\n}\n",
        "original-reaction-job-private-record-lookup")
    result["js/src/builtin/Promise.cpp"] = source
    if "js/public/ActivationPromiseHooks.h" in original:
        raise ValueError("original engine already defines private hook ABI")
    result["js/public/ActivationPromiseHooks.h"] = header
    return result, {
        "format": "latent.typescript.intrinsic-promise-source-derivation.v1",
        "firefoxCommit": FIREFOX_COMMIT, "originalSource": before,
        "derivedSource": identity(result), "intrinsicAllocationSitesMatched": 1,
        "originalPromiseConstructorAndThenBehaviorReplaced": False,
        "nativeAdmissionBeforeObjectAllocation": True,
        "pendingReactionAdmissionBeforeAllocation": True,
        "originalReactionJobRecordLookup": True,
        "GCPerformsHostCallsOrRefunds": False,
        "originalPromiseObjectDeclarationUnchanged": True,
        "originalPromiseAndReactionClassOperationsUnchanged": True,
        "GCObservation": "original-weak-pointer-api-then-actual-collection-end",
        "newSourceBuiltSpiderMonkeyRequired": True,
        "priorPublicQueueProofQualifiesTheseNewHooks": False,
        "supportedAsyncProfile": False,
        "remaining": ["source-built-library-and-real-intrinsic-hook-controls",
                      "real-pending-reaction-admission-and-job-transfer-controls",
                      "native-thenable-job-preallocation",
                      "root-versus-accepted-work-drain", "standard-timers-and-stop-acknowledgement",
                      "real-async-import-lowering", "matching-signed-component-qualification"],
    }
