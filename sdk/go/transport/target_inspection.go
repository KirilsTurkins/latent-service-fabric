package transport

import (
	"latent.dev/sdk/go/profile"
	"strings"
	"unicode"
)

func targetID(value string) bool {
	return value != "" && len(value) <= 512 && strings.IndexFunc(value, func(c rune) bool {
		return unicode.IsControl(c) || unicode.IsSpace(c)
	}) < 0
}
func targetHex(value string) bool {
	return len(value) == 64 && strings.Trim(value, "0123456789abcdef") == ""
}
func targetDigest(value, prefix string) bool {
	return strings.HasPrefix(value, prefix) && targetHex(strings.TrimPrefix(value, prefix))
}
func targetPublication(value *profile.PublicationRef, tenant string) bool {
	return value != nil && value.Tenant == tenant && targetID(tenant) && targetDigest(value.Id, "publication:sha256:")
}
func targetRequestValid(value profile.InspectHttpTargetRequest) bool {
	if !targetID(value.Service) || !targetID(value.Contract) || !targetID(value.Function) || value.MaximumWaitMillis > 30000 {
		return false
	}
	for _, text := range []*string{value.Route, value.RevisionId, value.RoutingKey} {
		if text != nil && !targetID(*text) {
			return false
		}
	}
	return value.Publication == nil || targetPublication(value.Publication, value.Publication.Tenant)
}
func targetResponseValid(value *profile.InspectHttpTargetResponse, request profile.InspectHttpTargetRequest) bool {
	if value.SchemaVersion != 1 || !targetID(value.Tenant) || value.Service != request.Service || value.Contract != request.Contract || value.Function != request.Function || !targetID(value.Route) || value.LiveGrantsChecked || len(value.Candidates) > 32 || request.Route != nil && value.Route != *request.Route || request.Publication != nil && value.Tenant != request.Publication.Tenant {
		return false
	}
	revisions := make(map[string]bool, len(value.Candidates))
	for _, candidate := range value.Candidates {
		if !targetID(candidate.DeploymentId) || !targetID(candidate.RevisionId) || revisions[candidate.RevisionId] || !targetDigest(candidate.ComponentDigest, "sha256:") || candidate.PackageDigest != nil && !targetDigest(*candidate.PackageDigest, "sha256:") || request.RevisionId != nil && candidate.RevisionId != *request.RevisionId || candidate.RoutingWeight > 65535 || len(candidate.Reasons) > 16 || len(candidate.Dependencies) > 32 || len(candidate.HttpBindings) > 32 {
			return false
		}
		revisions[candidate.RevisionId] = true
		for _, publication := range []*profile.PublicationRef{candidate.Publication, candidate.RequestedPublication} {
			if publication != nil && !targetPublication(publication, value.Tenant) {
				return false
			}
		}
		if request.Publication != nil && (candidate.Publication == nil || *candidate.Publication != *request.Publication) {
			return false
		}
		if candidate.PublicationKind != nil && (candidate.PackageDigest == nil || *candidate.PublicationKind != "capsule" && *candidate.PublicationKind != "browser-assets" && *candidate.PublicationKind != "ssr-package") {
			return false
		}
		for _, binding := range candidate.HttpBindings {
			if !targetID(binding.Id) || binding.Generation == 0 || binding.State != "configured-current" && binding.State != "deployment-changed" {
				return false
			}
		}
		for _, dependency := range candidate.Dependencies {
			if !targetID(dependency.Capability) || !targetID(dependency.ProviderProfile) || !targetID(dependency.ConfigurationDigest) || !targetHex(dependency.PolicyIdentityDigest) || dependency.Binding == nil || len(dependency.Policies) > 32 {
				return false
			}
			switch dependency.State {
			case "configured-current", "policy-changed-or-revoked", "provider-unavailable", "publication-unavailable", "route-changed-or-unavailable", "inspection-indeterminate":
			default:
				return false
			}
			if !targetID(dependency.Binding.Id) || !targetID(dependency.Binding.Digest) {
				return false
			}
			for _, revision := range dependency.Policies {
				if !targetID(revision.Id) || !targetID(revision.Digest) {
					return false
				}
			}
		}
		preparation := candidate.Preparation
		if preparation == nil || !request.IncludePreparation && preparation.State != 4 || request.IncludePreparation && preparation.State == 4 || len(preparation.Imports)+len(preparation.TypeImports) > 64 || len(preparation.Exports) > 128 {
			return false
		}
		for _, text := range []*string{preparation.EngineVersion, preparation.TargetTriple, preparation.CpuFeatureSet} {
			if text != nil && !targetID(*text) {
				return false
			}
		}
		if preparation.EngineConfigurationDigest != nil && !targetDigest(*preparation.EngineConfigurationDigest, "blake3:") || preparation.SealedMetadataFingerprint != nil && !targetHex(*preparation.SealedMetadataFingerprint) {
			return false
		}
		for _, imported := range preparation.Imports {
			if !targetID(imported) {
				return false
			}
			for _, imported := range preparation.TypeImports {
				if !targetID(imported) {
					return false
				}
			}
		}
		for _, exported := range preparation.Exports {
			if !targetID(exported.Contract) || !targetID(exported.Function) {
				return false
			}
		}
		if diagnostic := preparation.Diagnostic; diagnostic != nil && (diagnostic.SchemaVersion != 1 || diagnostic.ProfileDigest != nil && !targetHex(*diagnostic.ProfileDigest)) {
			return false
		}
		if preparation.State == 1 && (preparation.Profile == nil || preparation.EngineVersion == nil || preparation.EngineConfigurationDigest == nil || preparation.TargetTriple == nil || preparation.CpuFeatureSet == nil || preparation.DeclaredBudget == nil || preparation.ImportCount == nil || *preparation.ImportCount != uint64(len(preparation.Imports)+len(preparation.TypeImports)) || preparation.FunctionCount == nil || *preparation.FunctionCount != uint64(len(preparation.Exports)) || preparation.HostcallFuel == nil || preparation.MaximumLiftedBytes == nil || preparation.MaximumTypeNodes == nil) {
			return false
		}
		if candidate.Eligible {
			if value.State != 1 || !candidate.ExportCompatible || candidate.Publication == nil || candidate.PackageDigest == nil || candidate.PublicationGeneration == nil || candidate.RoutingWeight == 0 || len(candidate.Reasons) != 1 || candidate.Reasons[0] != 1 || preparation.State != 1 && preparation.State != 4 {
				return false
			}
			for _, dependency := range candidate.Dependencies {
				if dependency.State != "configured-current" {
					return false
				}
			}
		}
	}
	return value.SelectedRevisionId == nil || request.RoutingKey != nil && revisions[*value.SelectedRevisionId]
}
