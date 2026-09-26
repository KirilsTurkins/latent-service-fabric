package providerworkflow

import (
	"context"
	"encoding/json"
	"errors"
	"net/url"
	"strconv"

	"latent.dev/sdk/go/profile"
)

func (owner *workflow) management(ctx context.Context) error {
	for _, kind := range []profile.CapabilityPolicyRecordKind{profile.CapabilityPolicyRecordKindPolicy, profile.CapabilityPolicyRecordKindProviderBinding} {
		first, failure := owner.client.ListPolicies(ctx, profile.ListPoliciesRequest{RecordKind: kind, Page: &profile.PageRequest{PageSize: 1}}, profile.CallOptions{})
		if failure != nil || len(first.Value.Policies) != 1 || first.Value.Page == nil || first.Value.Page.NextPageToken == nil || *first.Value.Page.NextPageToken == "" {
			return errors.New("participant-bounded-policy-first-page-failed")
		}
		owner.observe(first.Metadata)
		second, failure := owner.client.ListPolicies(ctx, profile.ListPoliciesRequest{RecordKind: kind,
			Page: &profile.PageRequest{PageSize: 1, PageToken: first.Value.Page.NextPageToken}}, profile.CallOptions{})
		if failure != nil || len(second.Value.Policies) != 1 || second.Value.Policies[0].Id == first.Value.Policies[0].Id ||
			first.Value.CatalogGeneration != second.Value.CatalogGeneration {
			return errors.New("participant-bounded-policy-next-page-failed")
		}
		owner.observe(second.Metadata)
		read, failure := owner.client.GetPolicy(ctx, profile.GetPolicyRequest{Id: first.Value.Policies[0].Id, RecordKind: kind}, profile.CallOptions{})
		if failure != nil || read.Value.Policy == nil || read.Value.Policy.Id != first.Value.Policies[0].Id || read.Value.Policy.RecordKind != kind ||
			read.Value.Policy.Generation != first.Value.Policies[0].Generation || read.Value.Policy.Document == "" {
			return errors.New("participant-policy-provider-record-read-failed")
		}
		owner.observe(read.Metadata)
	}
	owner.result.Assertions["boundedPages"] = true
	for _, name := range []string{"http", "blob"} {
		target := owner.input.Targets[name]
		response, failure := owner.client.ListCapabilities(ctx, profile.ListCapabilitiesRequest{DeploymentId: target.Route, Page: &profile.PageRequest{PageSize: 1}}, profile.CallOptions{})
		if failure != nil || len(response.Value.Capabilities) != 1 || response.Value.Revision == nil {
			return errors.New("participant-provider-inspection-page-failed")
		}
		owner.observe(response.Metadata)
		value := response.Value.Capabilities[0].Inspection
		revision := response.Value.Revision
		if value == nil || value.ProviderBinding == nil || value.ProviderBinding.Id == "" || value.ProviderBinding.Revision == 0 ||
			value.ProviderConfigurationDigest == "" || value.ProviderConfigurationEpoch == 0 || value.ProviderProfile == "" ||
			revision.ComponentDigest != target.ComponentDigest || revision.PublicationId == nil || *revision.PublicationId != target.Publication {
			return errors.New("participant-redacted-provider-identity-missing")
		}
	}
	owner.result.Assertions["providerInspection"] = true
	request := profile.ApplyPolicyRequest{OperationId: owner.result.OperationID, ExpectedGeneration: reference(uint64(0)),
		Policy: &profile.Policy{Id: "go-no-authority", Metadata: &profile.ObjectMetadata{Name: "go-no-authority", Tenant: reference(owner.input.Tenant)},
			RecordKind: profile.CapabilityPolicyRecordKindPolicy, Language: "lsf-capability-policy-v1", Document: owner.input.PolicyDocument}}
	created, failure := owner.client.ApplyPolicy(ctx, request, profile.CallOptions{})
	if failure != nil || created.Value.Receipt == nil || created.Value.Receipt.OperationId != request.OperationId || created.Value.Receipt.Generation == 0 {
		return errors.New("participant-preconditioned-policy-create-failed")
	}
	owner.observe(created.Metadata)
	// lsf-example-begin: management
	lookup, failure := owner.client.GetPolicyOperation(ctx, profile.GetPolicyOperationRequest{OperationId: request.OperationId}, profile.CallOptions{})
	if failure != nil || !sameReceipt(created.Value.Receipt, lookup.Value.Receipt) || lookup.Metadata.Outcome != profile.OutcomeKnowledgeObserved {
		return errors.New("participant-original-policy-operation-recovery-failed")
	}
	owner.observe(lookup.Metadata)
	// lsf-example-end: management
	owner.result.Assertions["mutationReceipt"] = true
	replay, failure := owner.client.ApplyPolicy(ctx, request, profile.CallOptions{})
	if failure != nil || !sameReceipt(created.Value.Receipt, replay.Value.Receipt) {
		return errors.New("participant-exact-explicit-policy-replay-failed")
	}
	owner.observe(replay.Metadata)
	owner.result.Assertions["exactReplay"] = true
	request.Policy.Document = owner.denyDocument()
	_, failure = owner.client.ApplyPolicy(ctx, request, profile.CallOptions{})
	owner.observeFailure(failure)
	if !rpcStatus(failure, 9) && !rpcStatus(failure, 10) {
		return errors.New("participant-changed-document-replay-not-conflicted")
	}
	request.Policy.Document = owner.input.PolicyDocument
	request.OperationId = "go-policy-stale"
	_, failure = owner.client.ApplyPolicy(ctx, request, profile.CallOptions{})
	owner.observeFailure(failure)
	if !rpcStatus(failure, 9) && !rpcStatus(failure, 10) {
		return errors.New("participant-stale-generation-not-conflicted")
	}
	owner.result.Assertions["preconditionConflict"] = true
	return nil
}

func (owner *workflow) denyDocument() string {
	origin, _ := url.Parse(owner.input.UpstreamURL)
	port, _ := strconv.ParseUint(origin.Port(), 10, 16)
	target := owner.input.Targets["http"]
	document := map[string]any{"formatVersion": 1, "tenant": owner.input.Tenant, "rules": []any{map[string]any{
		"id": "go-deny-only", "effect": "deny", "principals": []any{map[string]string{"kind": "user", "subject": "workflow-operator"}},
		"services": []string{target.Service}, "publications": []string{target.Publication}, "capability": "latent:http/client@0.2.0", "operations": []string{"send"},
		"resources": map[string]any{"kind": "http", "origins": []any{map[string]any{"scheme": "http", "host": "localhost", "port": port}},
			"methods": []string{"GET"}, "paths": []string{"/allowed"}, "pathPrefixes": []string{}},
		"ceiling": map[string]uint64{"operations": 0, "inputBytes": 0, "outputBytes": 0, "wallTimeMillis": 0},
	}}}
	encoded, _ := json.Marshal(document)
	return string(encoded)
}
