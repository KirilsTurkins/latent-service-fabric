package providerworkflow

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"time"

	"latent.dev/sdk/go/profile"
	"latent.dev/sdk/go/transport"
)

const mediaType = "application/vnd.latent.wit-values.v1+json"

type Result struct {
	SchemaVersion string          `json:"schemaVersion"`
	Language      string          `json:"language"`
	Assertions    map[string]bool `json:"assertions"`
	ActivationIDs []string        `json:"activationIds"`
	OperationID   string          `json:"operationId"`
	AuditAttempt  *string         `json:"auditAttempt"`
	Transport     string          `json:"transport"`
}

type workflow struct {
	input     Input
	config    transport.Config
	client    *transport.Client
	clients   []*transport.Client
	result    Result
	auditSeen bool
}

func Run(ctx context.Context, input Input, token string) (Result, error) {
	owner := &workflow{input: input, config: transport.DefaultConfig(input.Endpoint, token), result: Result{
		SchemaVersion: "latent.sdk.provider.workflow.result.v1", Language: "go", Assertions: make(map[string]bool),
		OperationID: "go-policy-create", Transport: "numeric-loopback-http2-protobuf-v1"}}
	owner.config.DefaultTimeout = 3 * time.Second
	defer owner.closeAll()
	client, failure := owner.open(ctx, owner.config)
	if failure != nil {
		return Result{}, errors.New("participant-connect-failed")
	}
	owner.client = client
	for _, step := range []func(context.Context) error{owner.guests, owner.authority, owner.management, owner.responseLimit, owner.heldCases} {
		if failure := step(ctx); failure != nil {
			return Result{}, failure
		}
	}
	if !owner.closeAll() {
		return Result{}, errors.New("participant-client-owners-not-reaped")
	}
	owner.result.Assertions["clientOwnersReaped"] = true
	if owner.auditSeen {
		return Result{}, errors.New("participant-current-node-audit-metadata-must-be-absent")
	}
	if len(owner.result.Assertions) != 18 || len(owner.result.ActivationIDs) < 6 || len(owner.result.ActivationIDs) > 16 {
		return Result{}, errors.New("participant-acceptance-incomplete")
	}
	return owner.result, nil
}

func (owner *workflow) open(ctx context.Context, config transport.Config) (*transport.Client, error) {
	client, failure := transport.New(ctx, config)
	if failure == nil {
		owner.clients = append(owner.clients, client)
	}
	return client, failure
}

func (owner *workflow) closeAll() bool {
	clean := true
	for _, client := range owner.clients {
		if client.Close() != nil || !client.Snapshot().Reaped {
			clean = false
		}
	}
	return clean
}

func (owner *workflow) observe(metadata profile.ResponseMetadata) {
	if metadata.AuditAck != nil || metadata.AuditStatus != nil || metadata.AuditAttemptSequence != nil {
		owner.auditSeen = true
	}
}

func (owner *workflow) observeFailure(failure error) {
	var detail *profile.ClientFailure
	if errors.As(failure, &detail) {
		owner.observe(profile.ResponseMetadata{AuditAck: detail.AuditAck, AuditStatus: detail.AuditStatus, AuditAttemptSequence: detail.AuditAttemptSequence})
	}
}

func (owner *workflow) request(name, identity string) profile.InvokeRequest {
	target := owner.input.Targets[name]
	budget := &profile.ResourceBudget{CpuFuel: 10000000000, MemoryBytes: 16777216, WallTimeLimitMillis: reference(uint64(5000)), OutboundRequests: 8}
	arguments := []any{uint32(0), "", "0"}
	if name == "http" {
		arguments[1] = owner.input.UpstreamURL
	} else if name == "blob" {
		budget.BlobReadBytes = 65536
		budget.BlobWriteBytes = 65536
	} else {
		budget.CpuFuel = 100000000
		budget.MemoryBytes = 4194304
		budget.OutboundRequests = 0
		arguments = []any{}
	}
	payload, _ := json.Marshal(arguments)
	return profile.InvokeRequest{ActivationId: reference(identity), Target: &profile.InvocationTarget{
		Tenant: owner.input.Tenant, Service: target.Service, Route: reference(target.Route), Contract: target.Contract, Function: target.Function},
		Payload: payload, MediaType: mediaType, Budget: budget}
}

func (owner *workflow) guests(ctx context.Context) error {
	// lsf-example-begin: invoke
	for _, sample := range []struct {
		name      string
		id        string
		value     uint64
		assertion string
	}{{"http", "go-http", 2201, "httpGuest"}, {"blob", "go-blob", 4, "blobGuest"}} {
		response, failure := owner.client.Invoke(ctx, owner.request(sample.name, sample.id), profile.CallOptions{})
		if failure != nil || !u64Result(response.Value, sample.value) || !owner.pin(response.Value, sample.name) {
			return errors.New("participant-" + sample.assertion + "-failed")
		}
		owner.observe(response.Metadata)
		if failure := owner.retain(ctx, sample.id); failure != nil {
			return failure
		}
		owner.result.Assertions[sample.assertion] = true
	}
	// lsf-example-end: invoke
	declared := owner.request("callee", "go-declared")
	declared.Target.Function = "fail"
	response, failure := owner.client.Invoke(ctx, declared, profile.CallOptions{})
	if failure != nil || response.Value.DeclaredError == nil || !owner.pin(response.Value, "callee") {
		return errors.New("participant-declared-error-missing")
	}
	owner.observe(response.Metadata)
	if failure := owner.retain(ctx, "go-declared"); failure != nil {
		return failure
	}
	owner.result.Assertions["declaredError"] = true
	platform := owner.request("callee", "go-platform")
	platform.Target.Function = "spin"
	platform.Budget.CpuFuel = 1000
	response, failure = owner.client.Invoke(ctx, platform, profile.CallOptions{})
	if failure != nil || response.Value.PlatformFailure == nil || response.Value.Consumption == nil {
		return errors.New("participant-platform-outcome-missing")
	}
	owner.observe(response.Metadata)
	if failure := owner.retain(ctx, "go-platform"); failure != nil {
		return failure
	}
	owner.result.Assertions["platformFailure"] = true
	return nil
}

func (owner *workflow) pin(value profile.InvokeResponse, name string) bool {
	target := owner.input.Targets[name]
	return value.ReleaseDigest == target.ComponentDigest && value.PublicationId != nil && *value.PublicationId == target.Publication
}

func (owner *workflow) authority(ctx context.Context) error {
	request := owner.request("callee", "go-wrong-tenant")
	request.Target.Tenant = "wrong-tenant"
	_, failure := owner.client.Invoke(ctx, request, profile.CallOptions{})
	owner.observeFailure(failure)
	if !rpcStatus(failure, 7) {
		return errors.New("participant-wrong-tenant-not-rejected")
	}
	owner.result.Assertions["wrongTenant"] = true
	config := owner.config
	config.BearerToken = "LSF-GO-WRONG-CREDENTIAL-TEST-ONLY"
	client, failure := owner.open(ctx, config)
	if failure != nil {
		return errors.New("participant-wrong-credential-connect-failed")
	}
	_, failure = client.Invoke(ctx, owner.request("callee", "go-wrong-credential"), profile.CallOptions{})
	owner.observeFailure(failure)
	if !rpcStatus(failure, 16) || client.Close() != nil {
		return errors.New("participant-wrong-credential-not-rejected")
	}
	owner.result.Assertions["wrongCredential"] = true
	return nil
}

func (owner *workflow) responseLimit(ctx context.Context) error {
	config := owner.config
	config.MaxResponseBytes = 1
	client, failure := owner.open(ctx, config)
	if failure != nil {
		return errors.New("participant-response-limit-connect-failed")
	}
	_, failure = client.Invoke(ctx, owner.request("callee", "go-response-limit"), profile.CallOptions{})
	owner.observeFailure(failure)
	var detail *profile.ClientFailure
	if !errors.As(failure, &detail) || detail.Category != profile.FailureCategoryLimit || !detail.Dispatched ||
		detail.Outcome != profile.OutcomeKnowledgeUnknown || client.Close() != nil {
		return errors.New("participant-response-limit-not-enforced")
	}
	if failure := owner.retain(ctx, "go-response-limit"); failure != nil {
		return failure
	}
	owner.result.Assertions["responseLimit"] = true
	return nil
}

func u64Result(value profile.InvokeResponse, expected uint64) bool {
	if value.Success == nil || value.Success.MediaType != mediaType || len(value.Success.Payload) > 1024 {
		return false
	}
	var result []string
	if decodeJSON(value.Success.Payload, &result) != nil || len(result) != 1 {
		return false
	}
	parsed, valid := profile.ParseU64Decimal(result[0])
	return valid && parsed == expected
}

func rpcStatus(failure error, expected int32) bool {
	var detail *profile.ClientFailure
	return errors.As(failure, &detail) && detail.GrpcStatus != nil && *detail.GrpcStatus == expected
}

func reference[Value any](value Value) *Value { return &value }

func sameReceipt(left, right *profile.CapabilityPolicyOperation) bool {
	return left != nil && right != nil && reflect.DeepEqual(left, right)
}
