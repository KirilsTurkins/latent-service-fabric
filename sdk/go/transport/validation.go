package transport

import (
	"encoding/hex"
	"strconv"
	"strings"
	"unicode"

	"latent.dev/sdk/go/profile"
)

func validateRequest(request any, maximum int) error {
	switch value := request.(type) {
	case profile.InvokeRequest:
		if len(value.Payload) > maximum {
			return errBound
		}
		for _, identity := range []*string{value.ActivationId, value.RootActivationId, value.ParentActivationId} {
			if identity != nil && len(*identity) > 256 {
				return errShape
			}
		}
	case profile.CancelRequest:
		if !validIdentity(value.ActivationId) || len(value.Reason) > 1024 {
			return errShape
		}
	case profile.GetActivationRequest:
		if !validIdentity(value.ActivationId) {
			return errShape
		}
	case profile.GetPolicyRequest:
		if !validKind(value.RecordKind) || !validIdentity(value.Id) {
			return errShape
		}
	case profile.ListPoliciesRequest:
		if !validKind(value.RecordKind) || value.Page == nil || value.Page.PageSize < 1 || value.Page.PageSize > 32 ||
			!validToken(value.Page.PageToken, 117) {
			return errShape
		}
	case profile.ListCapabilitiesRequest:
		if !validIdentity(value.DeploymentId) || (value.Page != nil && (value.Page.PageSize > 128 || !validToken(value.Page.PageToken, 160))) {
			return errShape
		}
	case profile.ApplyPolicyRequest:
		if value.ExpectedGeneration == nil || !validIdentity(value.OperationId) || value.Policy == nil {
			return errShape
		}
		policy := value.Policy
		if !validIdentity(policy.Id) || !validKind(policy.RecordKind) || policy.Generation != 0 ||
			policy.ContentDigest != "" || policy.Revoked || len(policy.Document) > maximum ||
			policy.Metadata == nil || policy.Metadata.Name != policy.Id || policy.Metadata.Tenant == nil ||
			!validIdentity(*policy.Metadata.Tenant) || policy.Metadata.Namespace != nil ||
			len(policy.Metadata.Labels) != 0 || len(policy.Metadata.Annotations) != 0 {
			return errShape
		}
		language := "lsf-capability-policy-v1"
		if policy.RecordKind == profile.CapabilityPolicyRecordKindProviderBinding {
			language = "lsf-provider-binding-v1"
		}
		if policy.Language != language {
			return errShape
		}
	case profile.GetPolicyOperationRequest:
		if !validIdentity(value.OperationId) {
			return errShape
		}
	default:
		return errShape
	}
	return nil
}

func validateResponse(response, request any, state *callState) error {
	invalid := func() error {
		return state.fail(profile.FailureCategoryDecode, "response contradicts the bounded profile")
	}
	switch value := response.(type) {
	case *profile.InvokeResponse:
		if !recordActivation(value.ActivationId, state) || value.Consumption == nil ||
			present(value.Success != nil, value.DeclaredError != nil, value.PlatformFailure != nil) != 1 {
			return invalid()
		}
		if value.RevisionId == "" || value.ReleaseDigest == "" {
			if value.RevisionId != "" || value.ReleaseDigest != "" || value.RouteGeneration != 0 ||
				value.PublicationId != nil || value.PlatformFailure == nil {
				return invalid()
			}
		} else if !validIdentity(value.RevisionId) || !validIdentity(value.ReleaseDigest) || !validPublication(value.PublicationId) {
			return invalid()
		}
		if value.PlatformFailure != nil && !knownPlatformCode(value.PlatformFailure.Code) {
			return unsupported(state, "platform_error.code", value.PlatformFailure.Code)
		}
	case *profile.CancelResponse:
		switch value.Disposition {
		case profile.CancelDispositionAccepted, profile.CancelDispositionNotFound:
			if value.TerminalState != nil {
				return invalid()
			}
		case profile.CancelDispositionAlreadyTerminal:
			if value.TerminalState == nil {
				return invalid()
			}
			if !knownTerminal(*value.TerminalState) {
				return unsupported(state, "cancel.terminal_state", *value.TerminalState)
			}
		default:
			return unsupported(state, "cancel.disposition", strconv.FormatInt(int64(value.Disposition), 10))
		}
		if value.Disposition == profile.CancelDispositionNotFound {
			return nil
		}
	case *profile.ActivationStatus:
		if !recordActivation(value.ActivationId, state) {
			return invalid()
		}
		if !knownPhase(value.Phase) {
			return unsupported(state, "activation.phase", value.Phase)
		}
		outcomes := present(value.Succeeded != nil, value.DeclaredError != nil, value.PlatformFailure != nil)
		if value.TerminalState == nil {
			if outcomes != 0 || value.FinalConsumption != nil || value.TerminalAtUnixMillis != nil {
				return invalid()
			}
		} else {
			if !knownTerminal(*value.TerminalState) {
				return unsupported(state, "activation.terminal_state", *value.TerminalState)
			}
			if outcomes != 1 || value.FinalConsumption == nil || value.TerminalAtUnixMillis == nil ||
				((*value.TerminalState == "completed") == (value.PlatformFailure != nil)) {
				return invalid()
			}
			if value.PlatformFailure != nil && !knownPlatformCode(value.PlatformFailure.Code) {
				return unsupported(state, "platform_error.code", value.PlatformFailure.Code)
			}
		}
	case *profile.ListPoliciesResponse:
		page := request.(profile.ListPoliciesRequest).Page
		if len(value.Policies) > int(page.PageSize) || (value.Page != nil && !validToken(value.Page.NextPageToken, 117)) {
			return invalid()
		}
	case *profile.ListCapabilitiesResponse:
		page := request.(profile.ListCapabilitiesRequest).Page
		maximum := 128
		if page != nil && page.PageSize != 0 {
			maximum = int(page.PageSize)
		}
		if len(value.Capabilities) > maximum || (value.Page != nil && !validToken(value.Page.NextPageToken, 160)) {
			return invalid()
		}
	case *profile.ApplyPolicyResponse:
		input := request.(profile.ApplyPolicyRequest)
		if value.Receipt == nil || value.Policy == nil || value.Receipt.OperationId != input.OperationId ||
			value.Receipt.Id != input.Policy.Id || value.Policy.Id != value.Receipt.Id ||
			value.Policy.Generation != value.Receipt.Generation || value.Policy.ContentDigest != value.Receipt.ContentDigest ||
			value.Policy.RecordKind != value.Receipt.RecordKind || value.Receipt.RecordKind != input.Policy.RecordKind ||
			value.Receipt.Tenant != *input.Policy.Metadata.Tenant || value.Policy.Revoked != value.Receipt.Revoked {
			return invalid()
		}
	case *profile.GetPolicyOperationResponse:
		if value.Receipt == nil {
			return nil
		}
		if value.Receipt.OperationId != request.(profile.GetPolicyOperationRequest).OperationId {
			return invalid()
		}
	}
	state.metadata.Outcome = profile.OutcomeKnowledgeObserved
	return nil
}

func recordActivation(identity string, state *callState) bool {
	if state.identity.ActivationId != nil && *state.identity.ActivationId != identity {
		return false
	}
	if state.identity.ActivationId == nil {
		state.identity.ActivationId = copyIdentity(&identity)
	}
	return validIdentity(identity)
}

func validIdentity(value string) bool {
	return len(value) > 0 && len(value) <= 256 && strings.IndexFunc(value, func(character rune) bool {
		return unicode.IsControl(character) || unicode.IsSpace(character)
	}) == -1
}

func validToken(value *string, maximum int) bool { return value == nil || len(*value) <= maximum }

func validKind(value profile.CapabilityPolicyRecordKind) bool {
	return value == profile.CapabilityPolicyRecordKindPolicy || value == profile.CapabilityPolicyRecordKindProviderBinding
}

func present(values ...bool) int {
	count := 0
	for _, value := range values {
		if value {
			count++
		}
	}
	return count
}

func validPublication(value *string) bool {
	if value == nil {
		return true
	}
	const prefix = "publication:sha256:"
	if !strings.HasPrefix(*value, prefix) || len(*value) != len(prefix)+64 || strings.ToLower(*value) != *value {
		return false
	}
	_, failure := hex.DecodeString((*value)[len(prefix):])
	return failure == nil
}

func knownPhase(value string) bool {
	switch value {
	case "received", "resolved", "admitted", "queued", "materializing", "running", "suspended", "preparing_commit", "committed", "effects_pending":
		return true
	}
	return false
}

func knownTerminal(value string) bool {
	switch value {
	case "completed", "rejected", "cancelled", "deadline_exceeded", "resource_exhausted", "guest_trap", "state_conflict", "dependency_failed", "platform_failed":
		return true
	}
	return false
}

func knownPlatformCode(value string) bool {
	switch value {
	case "unavailable", "deadline-exceeded", "cancelled", "resource-exhausted", "permission-denied", "unauthenticated", "invalid-argument", "not-found", "already-exists", "incompatible-contract", "state-conflict", "dependency-failed", "guest-trap", "corrupt-artifact", "route-unavailable", "admission-rejected", "internal":
		return true
	}
	return false
}

func unsupported(state *callState, field, value string) error {
	failure := state.fail(profile.FailureCategoryDecode, "unsupported invocation wire value")
	if len(value) > 256 {
		value = value[:256]
	}
	failure.UnsupportedWireValue = &profile.UnsupportedWireValue{Field: field, Value: value}
	return failure
}
