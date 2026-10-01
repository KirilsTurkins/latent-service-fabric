package transport

import (
	"bytes"
	"errors"
	"latent.dev/sdk/go/profile"
	tx "latent.dev/sdk/go/transaction"
	"math"
	"reflect"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

type transactionWireValue struct{ field, value string }

func (value *transactionWireValue) Error() string { return "unsupported transaction wire value" }
func transactionInvalid(state *callState, invalid error, response bool) *profile.ClientFailure {
	category := profile.FailureCategoryInvalidRequest
	if response {
		category = profile.FailureCategoryDecode
	}
	failure := state.fail(category, "invalid bounded transaction value")
	var unsupported *transactionWireValue
	if errors.As(invalid, &unsupported) {
		failure.UnsupportedWireValue = &profile.UnsupportedWireValue{Field: unsupported.field, Value: unsupported.value}
	}
	return failure
}

func transactionDeref(value reflect.Value) reflect.Value {
	for value.IsValid() && (value.Kind() == reflect.Pointer || value.Kind() == reflect.Interface) {
		if value.IsNil() {
			return reflect.Value{}
		}
		value = value.Elem()
	}
	return value
}
func transactionField(value reflect.Value, name string) reflect.Value {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.Struct {
		return reflect.Value{}
	}
	return value.FieldByName(name)
}
func transactionHas(value reflect.Value) bool { return transactionDeref(value).IsValid() }
func transactionEqual(left, right reflect.Value) bool {
	left, right = transactionDeref(left), transactionDeref(right)
	if !left.IsValid() || !right.IsValid() {
		return left.IsValid() == right.IsValid()
	}
	return reflect.DeepEqual(left.Interface(), right.Interface())
}

type transactionValidator struct{ failure error }

func (v *transactionValidator) check(valid bool) {
	if !valid && v.failure == nil {
		v.failure = errShape
	}
}
func (v *transactionValidator) text(value reflect.Value, maximum int, required, controls bool) string {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.String {
		v.check(false)
		return ""
	}
	text := value.String()
	v.check(utf8.ValidString(text) && len(text) <= maximum && (!required || len(text) != 0) && (!controls || !strings.ContainsFunc(text, unicode.IsControl)))
	return text
}
func (v *transactionValidator) id(value reflect.Value) string { return v.text(value, 256, true, true) }
func (v *transactionValidator) identity(value reflect.Value) string {
	text := v.text(value, 256, true, false)
	v.check(!strings.ContainsRune(text, 0))
	return text
}
func (v *transactionValidator) optionalID(value reflect.Value) {
	if transactionHas(value) {
		v.id(value)
	}
}
func (v *transactionValidator) data(value reflect.Value, maximum int, required bool) []byte {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.Slice || value.Type().Elem().Kind() != reflect.Uint8 {
		v.check(false)
		return nil
	}
	data := value.Bytes()
	v.check(len(data) <= maximum && (!required || len(data) != 0))
	return data
}
func (v *transactionValidator) uint(value reflect.Value) uint64 {
	value = transactionDeref(value)
	if !value.IsValid() || (value.Kind() != reflect.Uint64 && value.Kind() != reflect.Uint32) {
		v.check(false)
		return 0
	}
	return value.Uint()
}
func (v *transactionValidator) boolean(value reflect.Value) bool {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.Bool {
		v.check(false)
		return false
	}
	return value.Bool()
}
func (v *transactionValidator) enum(value reflect.Value, maximum int64, field string) int64 {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.Int32 {
		v.check(false)
		return 0
	}
	number := value.Int()
	if (number < 1 || number > maximum) && v.failure == nil {
		v.failure = &transactionWireValue{field, strconv.FormatInt(number, 10)}
	}
	return number
}
func (v *transactionValidator) list(value reflect.Value, maximum int) []reflect.Value {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.Slice {
		v.check(false)
		return nil
	}
	if value.Len() > maximum {
		v.check(false)
		return nil
	}
	items := make([]reflect.Value, value.Len())
	for i := range items {
		items[i] = value.Index(i)
	}
	return items
}
func (v *transactionValidator) digest(value reflect.Value) {
	text := v.text(value, 71, true, true)
	v.check(len(text) == 71 && strings.HasPrefix(text, "sha256:"))
	if len(text) == 71 {
		for _, r := range text[7:] {
			v.check(r >= '0' && r <= '9' || r >= 'a' && r <= 'f')
		}
	}
}
func (v *transactionValidator) namespace(value reflect.Value, tenant string) {
	actual := v.id(transactionField(value, "Tenant"))
	v.id(transactionField(value, "Namespace"))
	incarnation := v.text(transactionField(value, "Incarnation"), 20, true, true)
	parsed, failure := strconv.ParseUint(incarnation, 10, 64)
	v.check(failure == nil && parsed != 0 && strconv.FormatUint(parsed, 10) == incarnation && (tenant == "" || tenant == actual))
}
func (v *transactionValidator) publication(value reflect.Value, tenant string) {
	id := v.id(transactionField(value, "Id"))
	v.check(strings.HasPrefix(id, "publication:") && v.id(transactionField(value, "Tenant")) == tenant)
	if strings.HasPrefix(id, "publication:") {
		v.digest(reflect.ValueOf(strings.TrimPrefix(id, "publication:")))
	}
}
func (v *transactionValidator) selector(value reflect.Value) string {
	ns := transactionField(value, "Namespace")
	v.namespace(ns, "")
	tenant := v.id(transactionField(ns, "Tenant"))
	v.identity(transactionField(value, "Operation"))
	v.identity(transactionField(value, "ClientKey"))
	for _, name := range []string{"Entity", "SharedRecoveryScope"} {
		field := transactionField(value, name)
		if transactionHas(field) {
			v.identity(field)
		}
	}
	return tenant
}
func (v *transactionValidator) selected(value reflect.Value) {
	v.check(transactionEqual(value, reflect.ValueOf(tx.CurrentProfile())))
}
func (v *transactionValidator) inspect(value reflect.Value) {
	v.selected(transactionField(value, "Profile"))
	ns := transactionField(value, "Namespace")
	v.namespace(ns, "")
	v.publication(transactionField(value, "AuthorizationPublication"), v.id(transactionField(ns, "Tenant")))
}
func (v *transactionValidator) lookup(value reflect.Value) {
	v.selected(transactionField(value, "Profile"))
	tenant := v.selector(transactionField(value, "Command"))
	v.publication(transactionField(value, "AuthorizationPublication"), tenant)
	v.optionalID(transactionField(value, "AttemptId"))
}
func (v *transactionValidator) fence(value reflect.Value) {
	for _, name := range []string{"CommandId", "AttemptId", "TransactionId"} {
		v.id(transactionField(value, name))
	}
	v.data(transactionField(value, "OwnerFence"), 256, true)
}
func (v *transactionValidator) page(value reflect.Value) {
	limit := v.uint(transactionField(value, "Limit"))
	v.check(limit >= 1 && limit <= 128)
	if cursor := transactionField(value, "Cursor"); transactionHas(cursor) {
		v.data(cursor, 256, true)
	}
}
func (v *transactionValidator) media(value reflect.Value) {
	text := v.text(value, 128, true, true)
	for _, r := range text {
		v.check(r >= ' ' && r <= '~')
	}
}
func (v *transactionValidator) metadata(value reflect.Value, caller bool) {
	value = transactionDeref(value)
	if !value.IsValid() || value.Kind() != reflect.Map || value.Len() > 32 {
		v.check(false)
		return
	}
	size := 0
	iterator := value.MapRange()
	for iterator.Next() {
		key := v.id(iterator.Key())
		text := v.text(iterator.Value(), 1024, false, true)
		size += len(key) + len(text)
		lower := strings.ToLower(key)
		v.check(!caller || !strings.HasPrefix(lower, "latent.auth.") && !strings.HasPrefix(lower, "latent.principal."))
	}
	v.check(size <= 8192)
}
func (v *transactionValidator) invocation(value reflect.Value, tenant string) {
	for _, name := range []string{"ActivationId", "ParentActivationId", "RootActivationId", "IdempotencyKey"} {
		v.optionalID(transactionField(value, name))
	}
	v.check(!transactionHas(transactionField(value, "ParentActivationId")) || transactionHas(transactionField(value, "RootActivationId")))
	target := transactionField(value, "Target")
	for _, name := range []string{"Tenant", "Service", "Contract", "Function"} {
		v.id(transactionField(target, name))
	}
	v.check(v.id(transactionField(target, "Tenant")) == tenant)
	v.optionalID(transactionField(target, "Route"))
	v.data(transactionField(value, "Payload"), 1024*1024, false)
	v.media(transactionField(value, "MediaType"))
	v.metadata(transactionField(value, "Metadata"), true)
	v.check(transactionHas(transactionField(value, "Budget")) && v.uint(transactionField(value, "Priority")) <= 255)
}
func (v *transactionValidator) quota(value reflect.Value) {
	for _, name := range []string{"StateKeys", "ResultRows", "EffectRows"} {
		count := v.uint(transactionField(value, name))
		v.check(count >= 1 && count <= 1000000)
	}
	for _, name := range []string{"StateBytes", "ResultBytes", "EffectBytes", "PayloadBytes", "RecoveryBytes"} {
		size := v.uint(transactionField(value, name))
		v.check(size >= 1 && size <= 1073741824)
	}
	v.check(v.uint(transactionField(value, "RecoveryBytes")) <= v.uint(transactionField(value, "ResultBytes")))
}
func (v *transactionValidator) dispatcherGeneration(value reflect.Value) (uint64, uint64) {
	epoch := v.uint(transactionField(value, "OwnerEpoch"))
	revision := v.uint(transactionField(value, "Revision"))
	v.check(epoch != 0 && revision != 0)
	return epoch, revision
}
func (v *transactionValidator) dispatcherControl(value reflect.Value) {
	v.selected(transactionField(value, "Profile"))
	v.enum(transactionField(value, "Scope"), 1, "dispatcher.scope")
	v.id(transactionField(value, "OperationId"))
	v.enum(transactionField(value, "Action"), 2, "dispatcher.action")
	_, revision := v.dispatcherGeneration(transactionField(value, "ExpectedGeneration"))
	v.check(revision != math.MaxUint64)
}
func (v *transactionValidator) dispatcherReceipt(value, original reflect.Value) {
	for _, name := range []string{"OperationId", "ReceiptId", "AuthenticatedOperator", "ActorTenant"} {
		v.id(transactionField(value, name))
	}
	action := v.enum(transactionField(value, "Action"), 2, "dispatcher.action")
	disposition := v.enum(transactionField(value, "Disposition"), 5, "dispatcher.disposition")
	before := transactionField(value, "BeforeGeneration")
	epoch, revision := v.dispatcherGeneration(before)
	afterEpoch, afterRevision := v.dispatcherGeneration(transactionField(value, "AfterGeneration"))
	v.check(transactionEqual(transactionField(value, "OperationId"), transactionField(original, "OperationId")) &&
		transactionEqual(transactionField(value, "Action"), transactionField(original, "Action")) &&
		transactionEqual(before, transactionField(original, "ExpectedGeneration")))
	v.check(disposition == 1 && revision != math.MaxUint64 && afterEpoch == epoch && afterRevision == revision+1)
	if action == 2 {
		v.check(v.boolean(transactionField(value, "ClockContinuityProven")) && !v.boolean(transactionField(value, "RestoreReviewRequired")))
	}
}
func validateTransactionRequest(request any) error {
	raw := reflect.ValueOf(request)
	v := transactionValidator{}
	switch raw.Type().Name() {
	case "InvokeCommandRequest":
		v.selected(transactionField(raw, "Profile"))
		tenant := v.selector(transactionField(raw, "Command"))
		v.invocation(transactionField(raw, "Invocation"), tenant)
		v.identity(transactionField(raw, "InputFormat"))
		keys := make(map[string]bool)
		for _, entry := range v.list(transactionField(raw, "ExpectedVersions"), 128) {
			key := string(v.data(transactionField(entry, "Key"), 1024, false))
			v.check(!keys[key])
			keys[key] = true
			absent, version := transactionField(entry, "Absent"), transactionField(entry, "Version")
			v.check(transactionHas(absent) != transactionHas(version))
			if transactionHas(absent) {
				v.check(v.boolean(absent))
			}
			if transactionHas(version) {
				v.data(version, 256, true)
			}
		}
		if retry := transactionField(raw, "RetryAttempt"); transactionHas(retry) {
			v.id(transactionField(retry, "RequestId"))
			v.fence(transactionField(retry, "ExpectedAbort"))
		}
	case "QueryRequest":
		v.selected(transactionField(raw, "Profile"))
		ns := transactionField(raw, "Namespace")
		v.namespace(ns, "")
		v.invocation(transactionField(raw, "Invocation"), v.id(transactionField(ns, "Tenant")))
		if entity := transactionField(raw, "Entity"); transactionHas(entity) {
			v.identity(entity)
		}
		if minimum := transactionField(raw, "MinimumViewVersion"); transactionHas(minimum) {
			v.data(minimum, 256, true)
		}
	case "LookupCommandRequest":
		v.lookup(raw)
	case "LookupCommitRequest":
		v.lookup(raw)
		v.id(transactionField(raw, "ReceiptId"))
	case "GetEffectRequest":
		v.lookup(raw)
		v.id(transactionField(raw, "EffectId"))
	case "ListEffectHistoryRequest":
		v.lookup(transactionField(raw, "Effect"))
		v.id(transactionField(transactionField(raw, "Effect"), "EffectId"))
		v.page(transactionField(raw, "Page"))
	case "CancelCommandRequest":
		v.lookup(transactionField(raw, "Command"))
		v.text(transactionField(raw, "Reason"), 1024, true, true)
	case "InspectNamespaceRequest":
		v.inspect(raw)
	case "SelectEntityRequest":
		v.inspect(transactionField(raw, "Namespace"))
		v.page(transactionField(raw, "Page"))
		if prefix := transactionField(raw, "Prefix"); transactionHas(prefix) {
			v.data(prefix, 256, false)
		}
	case "GetStateOperationReceiptRequest":
		v.inspect(transactionField(raw, "Namespace"))
		v.id(transactionField(raw, "OperationId"))
	case "MutateStateRequest":
		v.inspect(transactionField(raw, "Namespace"))
		v.id(transactionField(raw, "OperationId"))
		v.data(transactionField(raw, "ExpectedVersion"), 256, true)
		v.digest(transactionField(raw, "ExpectedPolicyDigest"))
		v.text(transactionField(raw, "Reason"), 1024, true, true)
		mutation := v.enum(transactionField(raw, "Mutation"), 4, "state.mutation")
		record := transactionField(raw, "RecordId")
		v.check((mutation == 4) == !transactionHas(record))
		v.optionalID(record)
	case "MutateNamespaceRequest":
		target := transactionField(raw, "Namespace")
		v.inspect(target)
		v.id(transactionField(raw, "OperationId"))
		expected := transactionField(raw, "ExpectedGeneration")
		before := v.uint(expected)
		mutation := v.enum(transactionField(raw, "Mutation"), 5, "namespace.mutation")
		v.check(transactionHas(expected) && (mutation == 1) == (before == 0))
		if mutation == 1 {
			v.check(v.id(transactionField(transactionField(target, "Namespace"), "Incarnation")) == "1")
		}
		configuration := transactionField(raw, "Configuration")
		if mutation == 1 || mutation == 5 {
			v.id(transactionField(configuration, "StateSchema"))
			v.quota(transactionField(configuration, "Quota"))
		} else {
			v.check(!transactionHas(configuration))
		}
	case "InspectDispatcherRequest":
		v.selected(transactionField(raw, "Profile"))
		v.enum(transactionField(raw, "Scope"), 1, "dispatcher.scope")
	case "ControlDispatcherRequest":
		v.dispatcherControl(raw)
	case "GetDispatcherOperationRequest":
		v.dispatcherControl(transactionField(raw, "Original"))
	default:
		v.check(false)
	}
	return v.failure
}

func (v *transactionValidator) source(value reflect.Value) {
	publication := v.id(transactionField(value, "PublicationId"))
	v.check(strings.HasPrefix(publication, "publication:"))
	if strings.HasPrefix(publication, "publication:") {
		v.digest(reflect.ValueOf(strings.TrimPrefix(publication, "publication:")))
	}
	for _, name := range []string{"RevisionId", "InputFormat", "ResultFormat"} {
		v.identity(transactionField(value, name))
	}
	for _, name := range []string{"ReleaseDigest", "ComponentDigest", "ContractDigest", "StateSchema"} {
		v.digest(transactionField(value, name))
	}
	v.check(v.uint(transactionField(value, "RouteGeneration")) != 0)
}
func (v *transactionValidator) retention(value reflect.Value) {
	if !transactionHas(value) {
		return
	}
	v.id(transactionField(value, "RecordFormat"))
	v.check(v.uint(transactionField(value, "RecordVersion")) != 0)
	for _, id := range v.list(transactionField(value, "RequiredRecordIds"), 256) {
		v.id(id)
	}
}
func (v *transactionValidator) result(value reflect.Value, kind string) {
	if kind == "TechnicalFailure" || kind == "CleanupFailure" {
		code := v.id(transactionField(value, "Code"))
		v.text(transactionField(value, "Message"), 1024, false, false)
		valid := false
		for _, known := range []string{"unavailable", "deadline-exceeded", "cancelled", "resource-exhausted", "permission-denied", "unauthenticated", "invalid-argument", "not-found", "already-exists", "incompatible-contract", "state-conflict", "dependency-failed", "guest-trap", "corrupt-artifact", "route-unavailable", "admission-rejected", "internal"} {
			if known == code {
				valid = true
			}
		}
		if !valid && v.failure == nil {
			v.failure = &transactionWireValue{"platform_error.code", code}
		}
		for _, detail := range v.list(transactionField(value, "DetailItems"), 16) {
			v.id(transactionField(detail, "Kind"))
			v.metadata(transactionField(detail, "Fields"), false)
		}
		return
	}
	v.data(transactionField(value, "Payload"), 1024*1024, false)
	v.media(transactionField(value, "MediaType"))
	v.metadata(transactionField(value, "Metadata"), false)
	if kind == "BusinessRejection" {
		v.id(transactionField(value, "Code"))
		v.text(transactionField(value, "Message"), 4096, false, false)
	} else {
		v.optionalID(transactionField(value, "CommittedStateVersion"))
		for _, id := range v.list(transactionField(value, "EffectIds"), 128) {
			v.id(id)
		}
	}
}
func (v *transactionValidator) command(value, selected reflect.Value) {
	key := transactionField(value, "Key")
	ns := transactionField(key, "Namespace")
	v.namespace(ns, v.id(transactionField(transactionField(selected, "Namespace"), "Tenant")))
	v.identity(transactionField(key, "RecoveryScope"))
	v.identity(transactionField(key, "Operation"))
	v.identity(transactionField(key, "ClientKey"))
	if entity := transactionField(key, "Entity"); transactionHas(entity) {
		v.identity(entity)
	}
	for _, part := range []string{"Namespace", "Operation", "Entity", "ClientKey"} {
		v.check(transactionEqual(transactionField(key, part), transactionField(selected, part)))
	}
	outcome := v.enum(transactionField(value, "Outcome"), 7, "command.outcome")
	known := outcome != 5 && outcome != 6
	for _, name := range []string{"CommandId", "AttemptId"} {
		field := transactionField(value, name)
		text := v.text(field, 256, false, true)
		if known || text != "" {
			v.id(field)
		}
	}
	fingerprint := v.data(transactionField(value, "FingerprintSha256"), 32, known)
	v.check(!known || len(fingerprint) == 32)
	source := transactionField(value, "Source")
	if known || transactionHas(source) {
		v.source(source)
	}
	v.retention(transactionField(value, "Retention"))
	results := 0
	for _, name := range []string{"Success", "BusinessRejection", "TechnicalFailure"} {
		field := transactionField(value, name)
		if transactionHas(field) {
			results++
			v.result(field, name)
		}
	}
	v.check(results <= 1)
	if cleanup := transactionField(value, "CleanupFailure"); transactionHas(cleanup) {
		v.result(cleanup, "CleanupFailure")
	}
	commit, abort := transactionField(value, "Commit"), transactionField(value, "ProvenAbort")
	if transactionHas(commit) {
		for _, name := range []string{"CommandId", "AttemptId", "TransactionId", "ReceiptId"} {
			v.id(transactionField(commit, name))
		}
		v.data(transactionField(commit, "CommittedVersion"), 256, true)
		v.source(transactionField(commit, "Source"))
		ids := make(map[string]bool)
		for _, raw := range v.list(transactionField(commit, "EffectIds"), 128) {
			id := v.id(raw)
			v.check(!ids[id])
			ids[id] = true
		}
		for _, name := range []string{"CommandId", "AttemptId", "Source"} {
			v.check(transactionEqual(transactionField(commit, name), transactionField(value, name)))
		}
	}
	if transactionHas(abort) {
		v.fence(abort)
		for _, name := range []string{"CommandId", "AttemptId"} {
			v.check(transactionEqual(transactionField(abort, name), transactionField(value, name)))
		}
	}
	durable := v.boolean(transactionField(value, "MetadataDurable"))
	committed := v.boolean(transactionField(value, "ApplicationStateCommitted"))
	retention := transactionField(value, "Retention")
	omitted := results == 0 && transactionHas(retention) && !v.boolean(transactionField(retention, "PayloadAvailable"))
	success, rejected := transactionHas(transactionField(value, "Success")), transactionHas(transactionField(value, "BusinessRejection"))
	switch outcome {
	case 2:
		v.check(durable && committed && transactionHas(commit) && !transactionHas(abort) && (success || omitted))
	case 3:
		v.check(durable && !committed && !transactionHas(commit) && !transactionHas(abort) && (rejected || omitted))
	case 4:
		v.check(durable && !committed && !transactionHas(commit) && transactionHas(abort) && !success && !rejected)
	case 7:
		v.check(durable && !transactionHas(abort) && results == 0 && committed == transactionHas(commit))
	default:
		v.check(!committed && !transactionHas(commit) && !transactionHas(abort) && results == 0)
	}
}
func (v *transactionValidator) effect(value reflect.Value, expected reflect.Value) {
	for _, name := range []string{"EffectId", "CommandId", "CommandAttemptId", "ProviderProfile"} {
		v.id(transactionField(value, name))
	}
	for _, name := range []string{"ProviderReceipt", "FailureCode", "ManagementOperationReceiptId"} {
		v.optionalID(transactionField(value, name))
	}
	v.enum(transactionField(value, "Disposition"), 8, "effect.disposition")
	v.check(transactionEqual(transactionField(value, "EffectId"), expected))
	v.retention(transactionField(value, "Retention"))
}
func (v *transactionValidator) pageResponse(value, request reflect.Value, count int) {
	v.check(v.uint(transactionField(value, "ReturnedCount")) == uint64(count) && uint64(count) <= v.uint(transactionField(request, "Limit")) && v.uint(transactionField(value, "EncodedBytes")) <= 1024*1024)
	if cursor := transactionField(value, "NextCursor"); transactionHas(cursor) {
		v.data(cursor, 256, true)
		v.check(!transactionEqual(cursor, transactionField(request, "Cursor")))
	}
}
func (v *transactionValidator) view(value, expected reflect.Value) {
	v.namespace(transactionField(value, "Namespace"), v.id(transactionField(expected, "Tenant")))
	v.check(transactionEqual(transactionField(value, "Namespace"), expected))
	v.data(transactionField(value, "Version"), 256, true)
	v.id(transactionField(value, "StateSchema"))
}
func (v *transactionValidator) invocationResponse(value, source, activation reflect.Value) {
	v.source(source)
	v.id(transactionField(value, "ActivationId"))
	v.check(transactionHas(transactionField(value, "Consumption")))
	if transactionHas(activation) {
		v.check(transactionEqual(transactionField(value, "ActivationId"), activation))
	}
	for _, pair := range [][2]string{{"PublicationId", "PublicationId"}, {"RevisionId", "RevisionId"}, {"ReleaseDigest", "ComponentDigest"}, {"RouteGeneration", "RouteGeneration"}} {
		v.check(transactionEqual(transactionField(value, pair[0]), transactionField(source, pair[1])))
	}
	results := 0
	for _, pair := range [][2]string{{"Success", "Success"}, {"DeclaredError", "BusinessRejection"}, {"PlatformFailure", "TechnicalFailure"}} {
		field := transactionField(value, pair[0])
		if transactionHas(field) {
			results++
			v.result(field, pair[1])
		}
	}
	v.check(results == 1)
}
func (v *transactionValidator) receipt(value, request reflect.Value, lifecycle bool) {
	target := transactionField(transactionField(request, "Namespace"), "Namespace")
	actual := transactionField(value, "Namespace")
	v.namespace(actual, v.id(transactionField(target, "Tenant")))
	for _, name := range []string{"OperationId", "ReceiptId", "AuthenticatedOperator"} {
		v.id(transactionField(value, name))
	}
	v.check(transactionEqual(transactionField(value, "OperationId"), transactionField(request, "OperationId")))
	disposition := v.enum(transactionField(value, "Disposition"), 5, "state.disposition")
	if lifecycle {
		v.check(transactionEqual(transactionField(actual, "Namespace"), transactionField(target, "Namespace")))
		v.id(transactionField(value, "StateSchema"))
		v.enum(transactionField(value, "Status"), 4, "namespace.status")
		v.enum(transactionField(value, "Mutation"), 5, "namespace.mutation")
		v.check(disposition != 1 || v.uint(transactionField(value, "AfterGeneration")) != 0)
	} else {
		v.check(transactionEqual(actual, target))
		v.data(transactionField(value, "BeforeVersion"), 256, true)
		v.data(transactionField(value, "AfterVersion"), 256, true)
		v.digest(transactionField(value, "PolicyDigest"))
		v.enum(transactionField(value, "Mutation"), 4, "state.mutation")
		v.optionalID(transactionField(value, "RecordId"))
	}
}
func validateTransactionResponse(response, original any, state *callState) error {
	value, request := reflect.ValueOf(response), reflect.ValueOf(original)
	v := transactionValidator{}
	switch request.Type().Name() {
	case "InvokeCommandRequest":
		command := transactionField(value, "Command")
		v.command(command, transactionField(request, "Command"))
		invocation := transactionField(value, "Invocation")
		v.invocationResponse(invocation, transactionField(command, "Source"), transactionField(transactionField(request, "Invocation"), "ActivationId"))
		for _, pair := range [][2]string{{"Success", "Success"}, {"BusinessRejection", "DeclaredError"}, {"TechnicalFailure", "PlatformFailure"}} {
			result := transactionField(command, pair[0])
			if transactionHas(result) {
				v.check(transactionEqual(result, transactionField(invocation, pair[1])))
			}
		}
		v.check(transactionHas(transactionField(command, "Success")) || transactionHas(transactionField(command, "BusinessRejection")) || transactionHas(transactionField(command, "TechnicalFailure")) || transactionHas(transactionField(invocation, "PlatformFailure")))
	case "LookupCommandRequest":
		command := transactionField(value, "Command")
		v.command(command, transactionField(request, "Command"))
		if attempt := transactionField(request, "AttemptId"); transactionHas(attempt) {
			v.check(transactionEqual(transactionField(command, "AttemptId"), attempt))
		}
	case "LookupCommitRequest":
		v.command(transactionField(value, "Command"), transactionField(request, "Command"))
		v.check(transactionEqual(transactionField(transactionField(transactionField(value, "Command"), "Commit"), "ReceiptId"), transactionField(request, "ReceiptId")))
	case "GetEffectRequest":
		v.effect(transactionField(value, "Effect"), transactionField(request, "EffectId"))
	case "ListEffectHistoryRequest":
		items := v.list(transactionField(value, "Receipts"), 128)
		for _, entry := range items {
			v.effect(entry, transactionField(transactionField(request, "Effect"), "EffectId"))
		}
		v.pageResponse(transactionField(value, "Page"), transactionField(request, "Page"), len(items))
	case "CancelCommandRequest":
		disposition := v.enum(transactionField(value, "Disposition"), 5, "command.cancel.disposition")
		command := transactionField(value, "Command")
		if transactionHas(command) {
			v.command(command, transactionField(transactionField(request, "Command"), "Command"))
			v.check(disposition != 2 || v.enum(transactionField(command, "Outcome"), 7, "command.outcome") == 2)
		} else {
			v.check(disposition == 4)
		}
	case "QueryRequest":
		v.view(transactionField(value, "View"), transactionField(request, "Namespace"))
		v.invocationResponse(transactionField(value, "Invocation"), transactionField(value, "Source"), transactionField(transactionField(request, "Invocation"), "ActivationId"))
	case "InspectNamespaceRequest":
		inspected := transactionField(value, "Namespace")
		v.view(transactionField(inspected, "View"), transactionField(request, "Namespace"))
		v.enum(transactionField(inspected, "Status"), 4, "namespace.status")
		v.check(v.uint(transactionField(inspected, "Generation")) != 0)
		v.quota(transactionField(inspected, "Quota"))
		v.id(transactionField(inspected, "EngineProfile"))
		v.digest(transactionField(inspected, "EngineProfileDigest"))
		for _, format := range v.list(transactionField(inspected, "RetainedFormats"), 128) {
			v.retention(format)
		}
	case "SelectEntityRequest":
		entries := v.list(transactionField(value, "Entities"), 128)
		ids := make(map[string]bool)
		for _, entry := range entries {
			id := v.identity(transactionField(entry, "Entity"))
			v.data(transactionField(entry, "Version"), 256, true)
			v.check(!ids[id])
			ids[id] = true
		}
		v.pageResponse(transactionField(value, "Page"), transactionField(request, "Page"), len(entries))
	case "MutateStateRequest":
		receipt := transactionField(value, "Receipt")
		v.receipt(receipt, request, false)
		for _, pair := range [][2]string{{"Mutation", "Mutation"}, {"RecordId", "RecordId"}, {"BeforeVersion", "ExpectedVersion"}, {"PolicyDigest", "ExpectedPolicyDigest"}} {
			v.check(transactionEqual(transactionField(receipt, pair[0]), transactionField(request, pair[1])))
		}
	case "MutateNamespaceRequest":
		receipt := transactionField(value, "Receipt")
		v.receipt(receipt, request, true)
		mutation := v.enum(transactionField(request, "Mutation"), 5, "namespace.mutation")
		v.check(transactionEqual(transactionField(receipt, "Mutation"), transactionField(request, "Mutation")))
		before := transactionField(receipt, "BeforeGeneration")
		if mutation == 1 {
			v.check(!transactionHas(before))
		} else {
			v.check(transactionEqual(before, transactionField(request, "ExpectedGeneration")))
		}
		if v.enum(transactionField(receipt, "Disposition"), 5, "state.disposition") == 1 {
			generation := v.uint(transactionField(request, "ExpectedGeneration"))
			target := transactionField(transactionField(request, "Namespace"), "Namespace")
			inc, _ := strconv.ParseUint(v.id(transactionField(target, "Incarnation")), 10, 64)
			v.check(generation != math.MaxUint64 && (mutation != 5 || inc != math.MaxUint64))
			if mutation == 5 {
				inc++
			}
			v.check(v.uint(transactionField(receipt, "AfterGeneration")) == generation+1 && v.id(transactionField(transactionField(receipt, "Namespace"), "Incarnation")) == strconv.FormatUint(inc, 10))
			status := mutation
			if mutation == 1 || mutation == 5 {
				status = 1
			}
			v.check(v.enum(transactionField(receipt, "Status"), 4, "namespace.status") == status)
			if config := transactionField(request, "Configuration"); transactionHas(config) {
				v.check(transactionEqual(transactionField(receipt, "StateSchema"), transactionField(config, "StateSchema")))
			}
		}
	case "GetStateOperationReceiptRequest":
		stateReceipt, namespaceReceipt := transactionField(value, "Receipt"), transactionField(value, "NamespaceReceipt")
		v.check(transactionHas(stateReceipt) != transactionHas(namespaceReceipt))
		if transactionHas(stateReceipt) {
			v.receipt(stateReceipt, request, false)
		} else {
			v.receipt(namespaceReceipt, request, true)
		}
	case "InspectDispatcherRequest":
		snapshot := transactionField(value, "Dispatcher")
		v.dispatcherGeneration(transactionField(snapshot, "Generation"))
		v.enum(transactionField(snapshot, "Failure"), 7, "dispatcher.failure")
		v.check(!(v.boolean(transactionField(snapshot, "PendingControl")) || v.boolean(transactionField(snapshot, "RestoreReviewRequired"))) || v.boolean(transactionField(snapshot, "Paused")))
	case "ControlDispatcherRequest":
		v.dispatcherReceipt(transactionField(value, "Receipt"), request)
		v.check(!(v.boolean(transactionField(value, "Replayed")) && v.boolean(transactionField(value, "Published"))))
		v.check(v.enum(transactionField(request, "Action"), 2, "dispatcher.action") != 1 || !v.boolean(transactionField(value, "Published")) || v.boolean(transactionField(value, "Paused")))
	case "GetDispatcherOperationRequest":
		v.dispatcherReceipt(transactionField(value, "Receipt"), transactionField(request, "Original"))
	default:
		v.check(false)
	}
	if v.failure != nil {
		return v.failure
	}
	state.transactionObserved = transactionObserve(response)
	state.transactionIdentity = transactionExtendIdentity(state.transactionIdentity, state.transactionObserved)
	state.metadata.Outcome = profile.OutcomeKnowledgeUnknown
	if transactionKnown(state.transactionObserved) {
		state.metadata.Outcome = profile.OutcomeKnowledgeObserved
	}
	// Independent audit decoding cannot erase a validated durable observation.
	if audit := transactionField(value, "AuditAck"); transactionHas(audit) {
		v.enum(transactionField(audit, "Status"), 4, "audit.status")
	}
	return v.failure
}

func transactionCollections(value reflect.Value, depth int, field string) error {
	if depth > 16 {
		return errBound
	}
	if !value.IsValid() {
		return errShape
	}
	if value.Kind() == reflect.Pointer {
		if value.IsNil() {
			return nil
		}
		return transactionCollections(value.Elem(), depth+1, field)
	}
	switch value.Kind() {
	case reflect.Struct:
		for i := 0; i < value.NumField(); i++ {
			if failure := transactionCollections(value.Field(i), depth+1, value.Type().Field(i).Name); failure != nil {
				return failure
			}
		}
	case reflect.Slice:
		if value.Type().Elem().Kind() == reflect.Uint8 {
			return nil
		}
		maximum := 128
		if field == "RequiredRecordIds" {
			maximum = 256
		}
		if value.Len() > maximum {
			return errBound
		}
		for i := 0; i < value.Len(); i++ {
			if failure := transactionCollections(value.Index(i), depth+1, ""); failure != nil {
				return failure
			}
		}
	case reflect.Map:
		if value.Len() > 32 {
			return errBound
		}
	}
	return nil
}
func transactionRecovery(request any) bool {
	switch request.(type) {
	case tx.LookupCommandRequest, tx.LookupCommitRequest, tx.GetEffectRequest, tx.ListEffectHistoryRequest, tx.CancelCommandRequest, tx.GetStateOperationReceiptRequest, tx.InspectDispatcherRequest, tx.ControlDispatcherRequest, tx.GetDispatcherOperationRequest:
		return true
	}
	return false
}
func transactionWallDeadline(request any) *uint64 {
	switch value := request.(type) {
	case tx.InvokeCommandRequest:
		if value.Invocation != nil {
			return value.Invocation.DeadlineUnixMillis
		}
	case tx.QueryRequest:
		if value.Invocation != nil {
			return value.Invocation.DeadlineUnixMillis
		}
	}
	return nil
}
func transactionObserve(response any) *tx.ObservedOutcome {
	var command *tx.CommandInspection
	switch value := response.(type) {
	case tx.InvokeCommandResponse:
		command = value.Command
	case tx.LookupCommandResponse:
		command = value.Command
	case tx.LookupCommitResponse:
		command = value.Command
	case tx.CancelCommandResponse:
		command = value.Command
	case tx.GetEffectResponse:
		return &tx.ObservedOutcome{Effect: value.Effect}
	case tx.MutateStateResponse:
		return &tx.ObservedOutcome{State: value.Receipt}
	case tx.MutateNamespaceResponse:
		return &tx.ObservedOutcome{Namespace: value.Receipt}
	case tx.GetStateOperationReceiptResponse:
		return &tx.ObservedOutcome{State: value.Receipt, Namespace: value.NamespaceReceipt}
	case tx.ControlDispatcherResponse:
		return &tx.ObservedOutcome{Dispatcher: value.Receipt}
	case tx.GetDispatcherOperationResponse:
		return &tx.ObservedOutcome{Dispatcher: value.Receipt}
	}
	if command == nil {
		return nil
	}
	copy := *command
	copy.Success = nil
	copy.BusinessRejection = nil
	copy.TechnicalFailure = nil
	copy.CleanupFailure = nil
	return &tx.ObservedOutcome{Command: &copy}
}
func transactionKnown(observed *tx.ObservedOutcome) bool {
	if observed == nil {
		return false
	}
	if observed.Command != nil {
		command := observed.Command
		return command.MetadataDurable && (command.Outcome == tx.CommandOutcomeCommitted || command.Outcome == tx.CommandOutcomeRejected || command.Outcome == tx.CommandOutcomeAborted)
	}
	if observed.State != nil {
		return observed.State.Disposition >= 1 && observed.State.Disposition <= 3
	}
	if observed.Namespace != nil {
		return observed.Namespace.Disposition >= 1 && observed.Namespace.Disposition <= 3
	}
	if observed.Dispatcher != nil {
		return observed.Dispatcher.Disposition == tx.StateOperationDispositionCommitted
	}
	return false
}
func transactionExtendIdentity(identity tx.RecoveryIdentity, observed *tx.ObservedOutcome) tx.RecoveryIdentity {
	if observed == nil {
		return identity
	}
	if observed.Command != nil {
		command := observed.Command
		if command.CommandId != "" {
			identity.CommandId = copyIdentity(&command.CommandId)
		}
		if identity.AttemptId == nil && command.AttemptId != "" {
			identity.AttemptId = copyIdentity(&command.AttemptId)
		}
		if identity.ReceiptId == nil && command.Commit != nil {
			identity.ReceiptId = copyIdentity(&command.Commit.ReceiptId)
		}
		if len(command.FingerprintSha256) != 0 {
			identity.FingerprintSha256 = bytes.Clone(command.FingerprintSha256)
		}
	} else if observed.State != nil {
		identity.ReceiptId = copyIdentity(&observed.State.ReceiptId)
	} else if observed.Namespace != nil {
		identity.ReceiptId = copyIdentity(&observed.Namespace.ReceiptId)
	} else if observed.Dispatcher != nil {
		identity.ReceiptId = copyIdentity(&observed.Dispatcher.ReceiptId)
	}
	return identity
}

func transactionClone(value reflect.Value) reflect.Value {
	switch value.Kind() {
	case reflect.Pointer:
		if value.IsNil() {
			return reflect.Zero(value.Type())
		}
		result := reflect.New(value.Type().Elem())
		result.Elem().Set(transactionClone(value.Elem()))
		return result
	case reflect.Struct:
		result := reflect.New(value.Type()).Elem()
		for i := 0; i < value.NumField(); i++ {
			result.Field(i).Set(transactionClone(value.Field(i)))
		}
		return result
	case reflect.String:
		return reflect.ValueOf(strings.Clone(value.String())).Convert(value.Type())
	case reflect.Slice:
		if value.IsNil() {
			return reflect.Zero(value.Type())
		}
		result := reflect.MakeSlice(value.Type(), value.Len(), value.Len())
		for i := 0; i < value.Len(); i++ {
			result.Index(i).Set(transactionClone(value.Index(i)))
		}
		return result
	default:
		return value
	}
}
func transactionIdentity(request any) tx.RecoveryIdentity {
	original := tx.RecoveryIdentity{}
	var command *tx.CommandSelector
	var inspect *tx.InspectNamespaceRequest
	switch value := request.(type) {
	case tx.InvokeCommandRequest:
		command = value.Command
		if value.Invocation != nil {
			original.ActivationId = value.Invocation.ActivationId
		}
		original.ExpectedVersions = value.ExpectedVersions
		if value.RetryAttempt != nil {
			original.RetryRequestId = &value.RetryAttempt.RequestId
			original.ExpectedAbort = value.RetryAttempt.ExpectedAbort
			if original.ExpectedAbort != nil {
				original.AttemptId = &original.ExpectedAbort.AttemptId
			}
		}
	case tx.QueryRequest:
		original.Namespace = value.Namespace
		if value.Invocation != nil {
			original.ActivationId = value.Invocation.ActivationId
		}
	case tx.LookupCommandRequest:
		command = value.Command
		original.AttemptId = value.AttemptId
		original.AuthorizationPublication = value.AuthorizationPublication
	case tx.LookupCommitRequest:
		command = value.Command
		original.ReceiptId = &value.ReceiptId
		original.AuthorizationPublication = value.AuthorizationPublication
	case tx.GetEffectRequest:
		command = value.Command
		original.EffectId = &value.EffectId
		original.AuthorizationPublication = value.AuthorizationPublication
	case tx.ListEffectHistoryRequest:
		if value.Effect != nil {
			command = value.Effect.Command
			original.EffectId = &value.Effect.EffectId
			original.AuthorizationPublication = value.Effect.AuthorizationPublication
		}
	case tx.CancelCommandRequest:
		if value.Command != nil {
			command = value.Command.Command
			original.AttemptId = value.Command.AttemptId
			original.AuthorizationPublication = value.Command.AuthorizationPublication
		}
	case tx.InspectNamespaceRequest:
		inspect = &value
	case tx.SelectEntityRequest:
		inspect = value.Namespace
	case tx.MutateNamespaceRequest:
		inspect = value.Namespace
		original.OperationId = &value.OperationId
		original.ExpectedGeneration = value.ExpectedGeneration
	case tx.MutateStateRequest:
		inspect = value.Namespace
		original.OperationId = &value.OperationId
		original.ExpectedVersion = &value.ExpectedVersion
		original.ExpectedPolicyDigest = &value.ExpectedPolicyDigest
	case tx.GetStateOperationReceiptRequest:
		inspect = value.Namespace
		original.OperationId = &value.OperationId
	case tx.ControlDispatcherRequest:
		original.OperationId = &value.OperationId
		original.DispatcherAction = &value.Action
		original.DispatcherExpectedGeneration = value.ExpectedGeneration
	case tx.GetDispatcherOperationRequest:
		if value.Original != nil {
			original.OperationId = &value.Original.OperationId
			original.DispatcherAction = &value.Original.Action
			original.DispatcherExpectedGeneration = value.Original.ExpectedGeneration
		}
	}
	if command != nil {
		original.Command = command
		original.Namespace = command.Namespace
	}
	if inspect != nil {
		original.Namespace = inspect.Namespace
		original.AuthorizationPublication = inspect.AuthorizationPublication
	}
	value := reflect.ValueOf(original)
	budget := graphBudget{bytes: 384 * 1024, nodes: 4096}
	if transactionCollections(value, 0, "") != nil || budget.scan(value, 0) != nil {
		return tx.RecoveryIdentity{}
	}
	v := transactionValidator{}
	if original.Namespace != nil {
		v.namespace(reflect.ValueOf(original.Namespace), "")
	}
	if command != nil {
		v.selector(reflect.ValueOf(command))
	}
	for _, id := range []*string{original.ActivationId, original.OperationId, original.AttemptId, original.ReceiptId, original.EffectId, original.RetryRequestId} {
		if id != nil {
			v.id(reflect.ValueOf(id))
		}
	}
	if original.ExpectedAbort != nil {
		v.fence(reflect.ValueOf(original.ExpectedAbort))
	}
	if original.ExpectedVersion != nil {
		v.data(reflect.ValueOf(original.ExpectedVersion), 256, true)
	}
	if original.DispatcherAction != nil {
		v.enum(reflect.ValueOf(original.DispatcherAction), 2, "dispatcher.action")
		v.dispatcherGeneration(reflect.ValueOf(original.DispatcherExpectedGeneration))
	}
	for _, expected := range original.ExpectedVersions {
		v.data(reflect.ValueOf(expected.Key), 1024, false)
		if expected.Version != nil {
			v.data(reflect.ValueOf(expected.Version), 256, true)
		}
	}
	if v.failure != nil {
		return tx.RecoveryIdentity{}
	}
	return transactionClone(value).Interface().(tx.RecoveryIdentity)
}
