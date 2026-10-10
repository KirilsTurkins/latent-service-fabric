package transport

import (
	"bytes"
	"reflect"
	"strings"
)

// A checked plan supplies no current policy, provider proof or retirement grant.
func (v *transactionValidator) effectVersion(value reflect.Value) {
	data := v.data(value, 32, true)
	v.check(len(data) == 32 && !bytes.Equal(data, make([]byte, 32)))
}

func (v *transactionValidator) effectMutation(value reflect.Value) {
	target := transactionField(value, "Effect")
	v.lookup(target)
	id := v.id(transactionField(target, "EffectId"))
	v.check(len(id) == 64 && !strings.ContainsFunc(id, func(char rune) bool {
		return !(char >= '0' && char <= '9' || char >= 'a' && char <= 'f')
	}))
	v.id(transactionField(value, "OperationId"))
	v.effectVersion(transactionField(value, "ExpectedVersion"))
	v.digest(transactionField(value, "ExpectedPolicyDigest"))
	v.text(transactionField(value, "Reason"), 1024, true, true)
	action := v.enum(transactionField(value, "Mutation"), 5, "state.mutation")
	delay := v.uint(transactionField(value, "RetryDelayMillis"))
	v.check(action == 1 && delay >= 1 && delay <= 60000 || (action == 2 || action == 5) && delay == 0)
}

func (v *transactionValidator) effectPlan(value reflect.Value) {
	original := transactionField(value, "Original")
	v.effectMutation(original)
	v.effectVersion(transactionField(value, "PlanDigest"))
	slot := v.uint(transactionField(value, "ManagementSequence"))
	owner, claim := v.uint(transactionField(value, "OwnerEpoch")), v.uint(transactionField(value, "ClaimGeneration"))
	attempt := v.uint(transactionField(value, "DispatchAttempt"))
	prepared, expires := v.uint(transactionField(value, "PreparedAtUnixMillis")), v.uint(transactionField(value, "ExpiresAtUnixMillis"))
	attempted := owner != 0 && claim != 0 && attempt != 0
	v.check(slot >= 1 && slot <= 128 && attempt <= 128 && (attempted || owner == 0 && claim == 0 && attempt == 0) &&
		prepared != 0 && expires > prepared && expires-prepared <= 30000)
	before := v.enum(transactionField(value, "Before"), 10, "effect.disposition")
	safety := v.enum(transactionField(value, "Safety"), 4, "effect.plan.safety")
	action := v.enum(transactionField(original, "Mutation"), 5, "state.mutation")
	v.check(action == 1 && attempted && (safety == 1 && before == 4 || safety == 2 && (before == 4 || before == 5)) ||
		action == 5 && attempted && safety == 3 && (before == 4 || before == 5) ||
		action == 2 && safety == 4 && (before == 1 || before == 4 || before == 5 || before == 7 || before == 9))
	dedup := transactionField(value, "DedupValidUntilUnixMillis")
	v.check((safety == 2) == transactionHas(dedup))
	if transactionHas(dedup) {
		v.check(v.uint(dedup) > expires)
	}
	// Historical receipt decoding deliberately does not compare the current clock.
}

func (v *transactionValidator) effectPlanAssociation(value, plan reflect.Value, recovery bool) {
	v.effectPlan(plan)
	original := transactionField(plan, "Original")
	target, current := transactionField(original, "Effect"), transactionField(value, "Namespace")
	v.check(transactionEqual(transactionField(current, "Namespace"), transactionField(transactionField(target, "Command"), "Namespace")) &&
		transactionEqual(transactionField(current, "Profile"), transactionField(target, "Profile")) &&
		transactionEqual(transactionField(value, "OperationId"), transactionField(original, "OperationId")))
	if !recovery {
		v.check(transactionEqual(transactionField(current, "AuthorizationPublication"), transactionField(target, "AuthorizationPublication")) &&
			transactionEqual(transactionField(value, "RecordId"), transactionField(target, "EffectId")))
		for _, name := range []string{"Mutation", "ExpectedVersion", "ExpectedPolicyDigest", "Reason"} {
			v.check(transactionEqual(transactionField(value, name), transactionField(original, name)))
		}
	}
}

func (v *transactionValidator) effectPlanReceipt(value, expected reflect.Value) {
	details := transactionField(value, "Effect")
	plan := transactionField(details, "OriginalPlan")
	original := transactionField(plan, "Original")
	v.effectPlan(plan)
	v.check(transactionEqual(plan, expected) && transactionEqual(transactionField(details, "Before"), transactionField(plan, "Before")))
	for _, name := range []string{"OperationId", "Mutation"} {
		v.check(transactionEqual(transactionField(value, name), transactionField(original, name)))
	}
	v.check(transactionEqual(transactionField(value, "RecordId"), transactionField(transactionField(original, "Effect"), "EffectId")) &&
		transactionEqual(transactionField(value, "BeforeVersion"), transactionField(original, "ExpectedVersion")) &&
		transactionEqual(transactionField(value, "PolicyDigest"), transactionField(original, "ExpectedPolicyDigest")))
	v.effectVersion(transactionField(value, "BeforeVersion"))
	v.effectVersion(transactionField(value, "AfterVersion"))
	completed := v.uint(transactionField(value, "CompletedAtUnixMillis"))
	v.check(v.enum(transactionField(value, "Disposition"), 5, "state.disposition") == 1 &&
		completed >= v.uint(transactionField(plan, "PreparedAtUnixMillis")) && completed < v.uint(transactionField(plan, "ExpiresAtUnixMillis")))
	fact := v.enum(transactionField(details, "Fact"), 3, "effect.management.fact")
	action := v.enum(transactionField(original, "Mutation"), 5, "state.mutation")
	after := v.enum(transactionField(details, "After"), 10, "effect.disposition")
	v.check(fact == 1 && action == 1 && after == 9 || fact == 2 && action == 5 && after == 3 || fact == 3 && action == 2 && (after == 8 || after == 10))
	provider, observed := transactionField(details, "ProviderReceipt"), transactionField(details, "ProviderObservedAtUnixMillis")
	v.check((fact == 2) == transactionHas(provider) && transactionHas(provider) == transactionHas(observed))
	v.optionalID(provider)
	if transactionHas(observed) {
		v.check(v.uint(observed) != 0 && v.uint(observed) <= completed)
	}
}
