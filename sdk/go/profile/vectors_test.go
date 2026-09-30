package profile

import (
	"strconv"
	"testing"
)

func fixturePointer[Value any](value Value) *Value { return &value }

func TestSharedProfileVectors(tester *testing.T) {
	{
		value := ActivationDiagnostic{SchemaVersion: uint32(1), Stage: DiagnosticStage(3), Reason: DiagnosticReason(1)}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.schema_version")
		}
		if !(int32(value.Stage) == 3) {
			tester.Fatal("diagnostic-absent-profile-and-bound.stage")
		}
		if !(int32(value.Reason) == 1) {
			tester.Fatal("diagnostic-absent-profile-and-bound.reason")
		}
		if !(!(value.Profile != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.profile.presence")
		}
		if !(!(value.ProfileDigest != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.profile_digest.presence")
		}
		if !(!(value.ConfiguredBound != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.configured_bound.presence")
		}
		if !(!(value.CalculatedRequirement != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.calculated_requirement.presence")
		}
		if !(!(value.FixedBytes != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.fixed_bytes.presence")
		}
		if !(!(value.LiftingFuel != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.lifting_fuel.presence")
		}
		if !(!(value.LiftMultiplier != nil)) {
			tester.Fatal("diagnostic-absent-profile-and-bound.lift_multiplier.presence")
		}
	}
	{
		value := ActivationDiagnostic{SchemaVersion: uint32(1), Stage: DiagnosticStage(2147483647), Reason: DiagnosticReason(-1), Profile: fixturePointer(DiagnosticProfile(999)), ProfileDigest: fixturePointer("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), ConfiguredBound: fixturePointer(uint64(0)), CalculatedRequirement: fixturePointer(uint64(18446744073709551615)), FixedBytes: fixturePointer(uint64(9223372036854775808)), LiftingFuel: fixturePointer(uint64(0)), LiftMultiplier: fixturePointer(uint64(18446744073709551615))}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.schema_version")
		}
		if !(int32(value.Stage) == 2147483647) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.stage")
		}
		if !(int32(value.Reason) == -1) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.reason")
		}
		if !(value.Profile != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.profile.presence")
		}
		if !(int32((*value.Profile)) == 999) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.profile")
		}
		if !(value.ProfileDigest != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.profile_digest.presence")
		}
		if !((*value.ProfileDigest) == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.profile_digest")
		}
		if !(value.ConfiguredBound != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.configured_bound.presence")
		}
		if !((*value.ConfiguredBound) == uint64(0)) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.configured_bound")
		}
		if !(value.CalculatedRequirement != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.calculated_requirement.presence")
		}
		if !((*value.CalculatedRequirement) == uint64(18446744073709551615)) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.calculated_requirement")
		}
		if !(value.FixedBytes != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.fixed_bytes.presence")
		}
		if !((*value.FixedBytes) == uint64(9223372036854775808)) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.fixed_bytes")
		}
		if !(value.LiftingFuel != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.lifting_fuel.presence")
		}
		if !((*value.LiftingFuel) == uint64(0)) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.lifting_fuel")
		}
		if !(value.LiftMultiplier != nil) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.lift_multiplier.presence")
		}
		if !((*value.LiftMultiplier) == uint64(18446744073709551615)) {
			tester.Fatal("diagnostic-unknown-enums-and-present-zero.lift_multiplier")
		}
	}
	{
		value := InspectActivationTreeRequest{ActivationId: "activation-a"}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("activation-tree-default-page.activation_id")
		}
		if !(!(value.Page != nil)) {
			tester.Fatal("activation-tree-default-page.page.presence")
		}
		if !(!(value.Service != nil)) {
			tester.Fatal("activation-tree-default-page.service.presence")
		}
		if !(!(value.FromUnixMillis != nil)) {
			tester.Fatal("activation-tree-default-page.from_unix_millis.presence")
		}
	}
	{
		value := InspectActivationTreeRequest{ActivationId: "", Page: fixturePointer(PageRequest{PageSize: uint32(128)}), Service: fixturePointer("examples/java-http-adapter"), FromUnixMillis: fixturePointer(uint64(18446744073709551615))}
		if !(value.ActivationId == "") {
			tester.Fatal("activation-roots-service-time-selector.activation_id")
		}
		if !(value.Page != nil) {
			tester.Fatal("activation-roots-service-time-selector.page.presence")
		}
		if !((*value.Page).PageSize == uint32(128)) {
			tester.Fatal("activation-roots-service-time-selector.page.page_size")
		}
		if !(!((*value.Page).PageToken != nil)) {
			tester.Fatal("activation-roots-service-time-selector.page.page_token.presence")
		}
		if !(value.Service != nil) {
			tester.Fatal("activation-roots-service-time-selector.service.presence")
		}
		if !((*value.Service) == "examples/java-http-adapter") {
			tester.Fatal("activation-roots-service-time-selector.service")
		}
		if !(value.FromUnixMillis != nil) {
			tester.Fatal("activation-roots-service-time-selector.from_unix_millis.presence")
		}
		if !((*value.FromUnixMillis) == uint64(18446744073709551615)) {
			tester.Fatal("activation-roots-service-time-selector.from_unix_millis")
		}
	}
	{
		value := InspectActivationTreeResponse{SchemaVersion: uint32(1), Nodes: []ActivationTreeNode{ActivationTreeNode{ActivationId: "host-generated-root", RootActivationId: "host-generated-root", Phase: "running", LastUpdatedUnixMillis: uint64(0), PrincipalKind: "trigger", DiagnosticIsTerminal: false, TargetService: "examples/java-http-adapter", ReceivedAtUnixMillis: uint64(18446744073709551615)}}, Page: fixturePointer(PageResponse{}), HistoryAvailable: true, CursorExpired: false, RetainedHistoryOnly: true}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("activation-root-real-ingress-identity.schema_version")
		}
		if !(len(value.Nodes) == 1) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.count")
		}
		if !(value.Nodes[0].ActivationId == "host-generated-root") {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.activation_id")
		}
		if !(!(value.Nodes[0].ParentActivationId != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.parent_activation_id.presence")
		}
		if !(value.Nodes[0].RootActivationId == "host-generated-root") {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.root_activation_id")
		}
		if !(value.Nodes[0].Phase == "running") {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.phase")
		}
		if !(!(value.Nodes[0].TerminalState != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.terminal_state.presence")
		}
		if !(value.Nodes[0].LastUpdatedUnixMillis == uint64(0)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.last_updated_unix_millis")
		}
		if !(!(value.Nodes[0].Diagnostic != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.diagnostic.presence")
		}
		if !(value.Nodes[0].PrincipalKind == "trigger") {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.principal_kind")
		}
		if !(!(value.Nodes[0].CallerService != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.caller_service.presence")
		}
		if !(!(value.Nodes[0].GrantedBudget != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.granted_budget.presence")
		}
		if !(!(value.Nodes[0].EffectiveDeadlineUnixMillis != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.effective_deadline_unix_millis.presence")
		}
		if !(value.Nodes[0].DiagnosticIsTerminal == false) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.diagnostic_is_terminal")
		}
		if !(value.Nodes[0].TargetService == "examples/java-http-adapter") {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.target_service")
		}
		if !(value.Nodes[0].ReceivedAtUnixMillis == uint64(18446744073709551615)) {
			tester.Fatal("activation-root-real-ingress-identity.nodes.0.received_at_unix_millis")
		}
		if !(value.Page != nil) {
			tester.Fatal("activation-root-real-ingress-identity.page.presence")
		}
		if !(!((*value.Page).NextPageToken != nil)) {
			tester.Fatal("activation-root-real-ingress-identity.page.next_page_token.presence")
		}
		if !(value.HistoryAvailable == true) {
			tester.Fatal("activation-root-real-ingress-identity.history_available")
		}
		if !(value.CursorExpired == false) {
			tester.Fatal("activation-root-real-ingress-identity.cursor_expired")
		}
		if !(value.RetainedHistoryOnly == true) {
			tester.Fatal("activation-root-real-ingress-identity.retained_history_only")
		}
	}
	{
		value := InspectActivationTreeResponse{SchemaVersion: uint32(1), Nodes: []ActivationTreeNode{}, Page: fixturePointer(PageResponse{}), HistoryAvailable: false, CursorExpired: true, RetainedHistoryOnly: true}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.schema_version")
		}
		if !(len(value.Nodes) == 0) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.nodes.count")
		}
		if !(value.Page != nil) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.page.presence")
		}
		if !(!((*value.Page).NextPageToken != nil)) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.page.next_page_token.presence")
		}
		if !(value.HistoryAvailable == false) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.history_available")
		}
		if !(value.CursorExpired == true) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.cursor_expired")
		}
		if !(value.RetainedHistoryOnly == true) {
			tester.Fatal("activation-tree-expired-is-not-absence-proof.retained_history_only")
		}
	}
	{
		value := InspectActivationTreeResponse{SchemaVersion: uint32(1), Nodes: []ActivationTreeNode{ActivationTreeNode{ActivationId: "child-a", ParentActivationId: fixturePointer("root-a"), RootActivationId: "root-a", Phase: "received", TerminalState: fixturePointer("resource_exhausted"), LastUpdatedUnixMillis: uint64(18446744073709551615), Diagnostic: fixturePointer(ActivationDiagnostic{SchemaVersion: uint32(1), Stage: DiagnosticStage(3), Reason: DiagnosticReason(1), Profile: fixturePointer(DiagnosticProfile(1)), ConfiguredBound: fixturePointer(uint64(16777216)), CalculatedRequirement: fixturePointer(uint64(67108864))}), PrincipalKind: "service", CallerService: fixturePointer("adapter"), DiagnosticIsTerminal: true, TargetService: "", ReceivedAtUnixMillis: uint64(0)}}, Page: fixturePointer(PageResponse{NextPageToken: fixturePointer("opaque-scoped-cursor")}), HistoryAvailable: true, CursorExpired: false, RetainedHistoryOnly: true}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.schema_version")
		}
		if !(len(value.Nodes) == 1) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.count")
		}
		if !(value.Nodes[0].ActivationId == "child-a") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.activation_id")
		}
		if !(value.Nodes[0].ParentActivationId != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.parent_activation_id.presence")
		}
		if !((*value.Nodes[0].ParentActivationId) == "root-a") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.parent_activation_id")
		}
		if !(value.Nodes[0].RootActivationId == "root-a") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.root_activation_id")
		}
		if !(value.Nodes[0].Phase == "received") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.phase")
		}
		if !(value.Nodes[0].TerminalState != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.terminal_state.presence")
		}
		if !((*value.Nodes[0].TerminalState) == "resource_exhausted") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.terminal_state")
		}
		if !(value.Nodes[0].LastUpdatedUnixMillis == uint64(18446744073709551615)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.last_updated_unix_millis")
		}
		if !(value.Nodes[0].Diagnostic != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.presence")
		}
		if !((*value.Nodes[0].Diagnostic).SchemaVersion == uint32(1)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.schema_version")
		}
		if !(int32((*value.Nodes[0].Diagnostic).Stage) == 3) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.stage")
		}
		if !(int32((*value.Nodes[0].Diagnostic).Reason) == 1) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.reason")
		}
		if !((*value.Nodes[0].Diagnostic).Profile != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.profile.presence")
		}
		if !(int32((*(*value.Nodes[0].Diagnostic).Profile)) == 1) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.profile")
		}
		if !(!((*value.Nodes[0].Diagnostic).ProfileDigest != nil)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.profile_digest.presence")
		}
		if !((*value.Nodes[0].Diagnostic).ConfiguredBound != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.configured_bound.presence")
		}
		if !((*(*value.Nodes[0].Diagnostic).ConfiguredBound) == uint64(16777216)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.configured_bound")
		}
		if !((*value.Nodes[0].Diagnostic).CalculatedRequirement != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.calculated_requirement.presence")
		}
		if !((*(*value.Nodes[0].Diagnostic).CalculatedRequirement) == uint64(67108864)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.calculated_requirement")
		}
		if !(!((*value.Nodes[0].Diagnostic).FixedBytes != nil)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.fixed_bytes.presence")
		}
		if !(!((*value.Nodes[0].Diagnostic).LiftingFuel != nil)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.lifting_fuel.presence")
		}
		if !(!((*value.Nodes[0].Diagnostic).LiftMultiplier != nil)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.lift_multiplier.presence")
		}
		if !(value.Nodes[0].PrincipalKind == "service") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.principal_kind")
		}
		if !(value.Nodes[0].CallerService != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.caller_service.presence")
		}
		if !((*value.Nodes[0].CallerService) == "adapter") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.caller_service")
		}
		if !(!(value.Nodes[0].GrantedBudget != nil)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.granted_budget.presence")
		}
		if !(!(value.Nodes[0].EffectiveDeadlineUnixMillis != nil)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.effective_deadline_unix_millis.presence")
		}
		if !(value.Nodes[0].DiagnosticIsTerminal == true) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.diagnostic_is_terminal")
		}
		if !(value.Nodes[0].TargetService == "") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.target_service")
		}
		if !(value.Nodes[0].ReceivedAtUnixMillis == uint64(0)) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.nodes.0.received_at_unix_millis")
		}
		if !(value.Page != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.page.presence")
		}
		if !((*value.Page).NextPageToken != nil) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.page.next_page_token.presence")
		}
		if !((*(*value.Page).NextPageToken) == "opaque-scoped-cursor") {
			tester.Fatal("activation-tree-failed-preparation-before-guest.page.next_page_token")
		}
		if !(value.HistoryAvailable == true) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.history_available")
		}
		if !(value.CursorExpired == false) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.cursor_expired")
		}
		if !(value.RetainedHistoryOnly == true) {
			tester.Fatal("activation-tree-failed-preparation-before-guest.retained_history_only")
		}
	}
	{
		value := InvokeRequest{Target: fixturePointer(InvocationTarget{Tenant: "tenant-a", Service: "echo", Contract: "example:echo/api@1.0.0", Function: "echo"}), Payload: []byte{0, 1, 2, 255}, MediaType: "application/octet-stream", Priority: uint32(0), Budget: fixturePointer(ResourceBudget{CpuFuel: uint64(18446744073709551615), MemoryBytes: uint64(9223372036854775808), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(0), EffectCount: uint32(0)}), Metadata: map[string]string{"trace": "redacted"}}
		if !(!(value.ActivationId != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.activation_id.presence")
		}
		if !(!(value.ParentActivationId != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.parent_activation_id.presence")
		}
		if !(!(value.RootActivationId != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.root_activation_id.presence")
		}
		if !(value.Target != nil) {
			tester.Fatal("invoke-absent-identity-and-deadlines.target.presence")
		}
		if !((*value.Target).Tenant == "tenant-a") {
			tester.Fatal("invoke-absent-identity-and-deadlines.target.tenant")
		}
		if !((*value.Target).Service == "echo") {
			tester.Fatal("invoke-absent-identity-and-deadlines.target.service")
		}
		if !((*value.Target).Contract == "example:echo/api@1.0.0") {
			tester.Fatal("invoke-absent-identity-and-deadlines.target.contract")
		}
		if !((*value.Target).Function == "echo") {
			tester.Fatal("invoke-absent-identity-and-deadlines.target.function")
		}
		if !(!((*value.Target).Route != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.target.route.presence")
		}
		if !(len(value.Payload) == 4) {
			tester.Fatal("invoke-absent-identity-and-deadlines.payload.length")
		}
		if !(value.Payload[0] == 0) {
			tester.Fatal("invoke-absent-identity-and-deadlines.payload.0")
		}
		if !(value.Payload[1] == 1) {
			tester.Fatal("invoke-absent-identity-and-deadlines.payload.1")
		}
		if !(value.Payload[2] == 2) {
			tester.Fatal("invoke-absent-identity-and-deadlines.payload.2")
		}
		if !(value.Payload[3] == 255) {
			tester.Fatal("invoke-absent-identity-and-deadlines.payload.3")
		}
		if !(value.MediaType == "application/octet-stream") {
			tester.Fatal("invoke-absent-identity-and-deadlines.media_type")
		}
		if !(!(value.DeadlineUnixMillis != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.deadline_unix_millis.presence")
		}
		if !(value.Priority == uint32(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.priority")
		}
		if !(!(value.IdempotencyKey != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.idempotency_key.presence")
		}
		if !(value.Budget != nil) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.presence")
		}
		if !((*value.Budget).CpuFuel == uint64(18446744073709551615)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.cpu_fuel")
		}
		if !((*value.Budget).MemoryBytes == uint64(9223372036854775808)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.memory_bytes")
		}
		if !((*value.Budget).ChildCalls == uint32(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.child_calls")
		}
		if !((*value.Budget).OutboundRequests == uint32(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.outbound_requests")
		}
		if !((*value.Budget).StateReadBytes == uint64(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.state_read_bytes")
		}
		if !((*value.Budget).StateWriteBytes == uint64(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.state_write_bytes")
		}
		if !((*value.Budget).BlobReadBytes == uint64(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.blob_read_bytes")
		}
		if !((*value.Budget).BlobWriteBytes == uint64(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.blob_write_bytes")
		}
		if !((*value.Budget).LogBytes == uint64(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.log_bytes")
		}
		if !((*value.Budget).EffectCount == uint32(0)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.effect_count")
		}
		if !(!((*value.Budget).WallTimeLimitMillis != nil)) {
			tester.Fatal("invoke-absent-identity-and-deadlines.budget.wall_time_limit_millis.presence")
		}
		if !(len(value.Metadata) == 1) {
			tester.Fatal("invoke-absent-identity-and-deadlines.metadata.count")
		}
		if !(value.Metadata["trace"] == "redacted") {
			tester.Fatal("invoke-absent-identity-and-deadlines.metadata.0")
		}
	}
	{
		value := InvokeRequest{ActivationId: fixturePointer(""), ParentActivationId: fixturePointer("parent-a"), RootActivationId: fixturePointer(""), Target: fixturePointer(InvocationTarget{Tenant: "", Service: "", Contract: "", Function: "", Route: fixturePointer("")}), Payload: []byte{}, MediaType: "", DeadlineUnixMillis: fixturePointer(uint64(0)), Priority: uint32(0), IdempotencyKey: fixturePointer(""), Budget: fixturePointer(ResourceBudget{CpuFuel: uint64(0), MemoryBytes: uint64(0), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(0), EffectCount: uint32(0), WallTimeLimitMillis: fixturePointer(uint64(0))}), Metadata: map[string]string{}}
		if !(value.ActivationId != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.activation_id.presence")
		}
		if !((*value.ActivationId) == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.activation_id")
		}
		if !(value.ParentActivationId != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.parent_activation_id.presence")
		}
		if !((*value.ParentActivationId) == "parent-a") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.parent_activation_id")
		}
		if !(value.RootActivationId != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.root_activation_id.presence")
		}
		if !((*value.RootActivationId) == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.root_activation_id")
		}
		if !(value.Target != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.presence")
		}
		if !((*value.Target).Tenant == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.tenant")
		}
		if !((*value.Target).Service == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.service")
		}
		if !((*value.Target).Contract == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.contract")
		}
		if !((*value.Target).Function == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.function")
		}
		if !((*value.Target).Route != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.route.presence")
		}
		if !((*(*value.Target).Route) == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.target.route")
		}
		if !(len(value.Payload) == 0) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.payload.length")
		}
		if !(value.MediaType == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.media_type")
		}
		if !(value.DeadlineUnixMillis != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.deadline_unix_millis.presence")
		}
		if !((*value.DeadlineUnixMillis) == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.deadline_unix_millis")
		}
		if !(value.Priority == uint32(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.priority")
		}
		if !(value.IdempotencyKey != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.idempotency_key.presence")
		}
		if !((*value.IdempotencyKey) == "") {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.idempotency_key")
		}
		if !(value.Budget != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.presence")
		}
		if !((*value.Budget).CpuFuel == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.cpu_fuel")
		}
		if !((*value.Budget).MemoryBytes == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.memory_bytes")
		}
		if !((*value.Budget).ChildCalls == uint32(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.child_calls")
		}
		if !((*value.Budget).OutboundRequests == uint32(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.outbound_requests")
		}
		if !((*value.Budget).StateReadBytes == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.state_read_bytes")
		}
		if !((*value.Budget).StateWriteBytes == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.state_write_bytes")
		}
		if !((*value.Budget).BlobReadBytes == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.blob_read_bytes")
		}
		if !((*value.Budget).BlobWriteBytes == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.blob_write_bytes")
		}
		if !((*value.Budget).LogBytes == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.log_bytes")
		}
		if !((*value.Budget).EffectCount == uint32(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.effect_count")
		}
		if !((*value.Budget).WallTimeLimitMillis != nil) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis.presence")
		}
		if !((*(*value.Budget).WallTimeLimitMillis) == uint64(0)) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis")
		}
		if !(len(value.Metadata) == 0) {
			tester.Fatal("invoke-present-invalid-and-zero-not-absence.metadata.count")
		}
	}
	{
		value := InvokeRequest{ActivationId: fixturePointer("activation-a"), ParentActivationId: fixturePointer("parent-a"), RootActivationId: fixturePointer("root-a"), Payload: []byte{}, MediaType: "", DeadlineUnixMillis: fixturePointer(uint64(18446744073709551615)), Priority: uint32(4294967295), IdempotencyKey: fixturePointer("not-an-authority-or-retry-key"), Metadata: map[string]string{}}
		if !(value.ActivationId != nil) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.activation_id.presence")
		}
		if !((*value.ActivationId) == "activation-a") {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.activation_id")
		}
		if !(value.ParentActivationId != nil) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.presence")
		}
		if !((*value.ParentActivationId) == "parent-a") {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.parent_activation_id")
		}
		if !(value.RootActivationId != nil) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.root_activation_id.presence")
		}
		if !((*value.RootActivationId) == "root-a") {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.root_activation_id")
		}
		if !(!(value.Target != nil)) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.target.presence")
		}
		if !(len(value.Payload) == 0) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.payload.length")
		}
		if !(value.MediaType == "") {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.media_type")
		}
		if !(value.DeadlineUnixMillis != nil) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis.presence")
		}
		if !((*value.DeadlineUnixMillis) == uint64(18446744073709551615)) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis")
		}
		if !(value.Priority == uint32(4294967295)) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.priority")
		}
		if !(value.IdempotencyKey != nil) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.idempotency_key.presence")
		}
		if !((*value.IdempotencyKey) == "not-an-authority-or-retry-key") {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.idempotency_key")
		}
		if !(!(value.Budget != nil)) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.budget.presence")
		}
		if !(len(value.Metadata) == 0) {
			tester.Fatal("invoke-known-identity-full-width-deadline-and-priority.metadata.count")
		}
	}
	{
		value := ResourceBudget{CpuFuel: uint64(18446744073709551615), MemoryBytes: uint64(18446744073709551615), ChildCalls: uint32(4294967295), OutboundRequests: uint32(4294967295), StateReadBytes: uint64(18446744073709551615), StateWriteBytes: uint64(18446744073709551615), BlobReadBytes: uint64(18446744073709551615), BlobWriteBytes: uint64(18446744073709551615), LogBytes: uint64(18446744073709551615), EffectCount: uint32(4294967295), WallTimeLimitMillis: fixturePointer(uint64(18446744073709551615))}
		if !(value.CpuFuel == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.cpu_fuel")
		}
		if !(value.MemoryBytes == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.memory_bytes")
		}
		if !(value.ChildCalls == uint32(4294967295)) {
			tester.Fatal("full-resource-budget.child_calls")
		}
		if !(value.OutboundRequests == uint32(4294967295)) {
			tester.Fatal("full-resource-budget.outbound_requests")
		}
		if !(value.StateReadBytes == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.state_read_bytes")
		}
		if !(value.StateWriteBytes == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.state_write_bytes")
		}
		if !(value.BlobReadBytes == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.blob_read_bytes")
		}
		if !(value.BlobWriteBytes == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.blob_write_bytes")
		}
		if !(value.LogBytes == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.log_bytes")
		}
		if !(value.EffectCount == uint32(4294967295)) {
			tester.Fatal("full-resource-budget.effect_count")
		}
		if !(value.WallTimeLimitMillis != nil) {
			tester.Fatal("full-resource-budget.wall_time_limit_millis.presence")
		}
		if !((*value.WallTimeLimitMillis) == uint64(18446744073709551615)) {
			tester.Fatal("full-resource-budget.wall_time_limit_millis")
		}
	}
	{
		value := InvokeResponse{ActivationId: "activation-a", RevisionId: "revision-a", ReleaseDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", RouteGeneration: uint64(18446744073709551615), Success: fixturePointer(Success{Payload: []byte{0, 1, 2, 255}, MediaType: "application/octet-stream", CommittedStateVersion: fixturePointer(""), EffectIds: []string{"effect-a", "effect-b"}, Metadata: map[string]string{"result": "redacted"}}), Consumption: fixturePointer(BudgetConsumption{CpuFuel: uint64(18446744073709551615), PeakMemoryBytes: uint64(0), WallTimeMicros: uint64(9007199254740993), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(0), EffectCount: uint32(0)}), PublicationId: fixturePointer("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111")}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("invoke-success-retains-publication-and-component.activation_id")
		}
		if !(value.RevisionId == "revision-a") {
			tester.Fatal("invoke-success-retains-publication-and-component.revision_id")
		}
		if !(value.ReleaseDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("invoke-success-retains-publication-and-component.release_digest")
		}
		if !(value.RouteGeneration == uint64(18446744073709551615)) {
			tester.Fatal("invoke-success-retains-publication-and-component.route_generation")
		}
		if !(value.Success != nil) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.presence")
		}
		if !(len((*value.Success).Payload) == 4) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.payload.length")
		}
		if !((*value.Success).Payload[0] == 0) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.payload.0")
		}
		if !((*value.Success).Payload[1] == 1) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.payload.1")
		}
		if !((*value.Success).Payload[2] == 2) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.payload.2")
		}
		if !((*value.Success).Payload[3] == 255) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.payload.3")
		}
		if !((*value.Success).MediaType == "application/octet-stream") {
			tester.Fatal("invoke-success-retains-publication-and-component.success.media_type")
		}
		if !((*value.Success).CommittedStateVersion != nil) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.committed_state_version.presence")
		}
		if !((*(*value.Success).CommittedStateVersion) == "") {
			tester.Fatal("invoke-success-retains-publication-and-component.success.committed_state_version")
		}
		if !(len((*value.Success).EffectIds) == 2) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.effect_ids.count")
		}
		if !((*value.Success).EffectIds[0] == "effect-a") {
			tester.Fatal("invoke-success-retains-publication-and-component.success.effect_ids.0")
		}
		if !((*value.Success).EffectIds[1] == "effect-b") {
			tester.Fatal("invoke-success-retains-publication-and-component.success.effect_ids.1")
		}
		if !(len((*value.Success).Metadata) == 1) {
			tester.Fatal("invoke-success-retains-publication-and-component.success.metadata.count")
		}
		if !((*value.Success).Metadata["result"] == "redacted") {
			tester.Fatal("invoke-success-retains-publication-and-component.success.metadata.0")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("invoke-success-retains-publication-and-component.declared_error.presence")
		}
		if !(!(value.PlatformFailure != nil)) {
			tester.Fatal("invoke-success-retains-publication-and-component.platform_failure.presence")
		}
		if !(value.Consumption != nil) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.presence")
		}
		if !((*value.Consumption).CpuFuel == uint64(18446744073709551615)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.cpu_fuel")
		}
		if !((*value.Consumption).PeakMemoryBytes == uint64(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.peak_memory_bytes")
		}
		if !((*value.Consumption).WallTimeMicros == uint64(9007199254740993)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.wall_time_micros")
		}
		if !((*value.Consumption).ChildCalls == uint32(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.child_calls")
		}
		if !((*value.Consumption).OutboundRequests == uint32(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.outbound_requests")
		}
		if !((*value.Consumption).StateReadBytes == uint64(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.state_read_bytes")
		}
		if !((*value.Consumption).StateWriteBytes == uint64(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.state_write_bytes")
		}
		if !((*value.Consumption).BlobReadBytes == uint64(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.blob_read_bytes")
		}
		if !((*value.Consumption).BlobWriteBytes == uint64(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.blob_write_bytes")
		}
		if !((*value.Consumption).LogBytes == uint64(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.log_bytes")
		}
		if !((*value.Consumption).EffectCount == uint32(0)) {
			tester.Fatal("invoke-success-retains-publication-and-component.consumption.effect_count")
		}
		if !(value.PublicationId != nil) {
			tester.Fatal("invoke-success-retains-publication-and-component.publication_id.presence")
		}
		if !((*value.PublicationId) == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111") {
			tester.Fatal("invoke-success-retains-publication-and-component.publication_id")
		}
	}
	{
		value := InvokeResponse{ActivationId: "activation-a", RevisionId: "revision-a", ReleaseDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", RouteGeneration: uint64(9223372036854775808), DeclaredError: fixturePointer(DeclaredError{Code: "uncertain", Message: "provider outcome unknown", Payload: []byte{0, 1, 2, 255}, MediaType: "application/octet-stream", Metadata: map[string]string{"contract": "latent:http/streaming@0.3.0"}}), Consumption: fixturePointer(BudgetConsumption{CpuFuel: uint64(0), PeakMemoryBytes: uint64(0), WallTimeMicros: uint64(0), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(18446744073709551615), LogBytes: uint64(0), EffectCount: uint32(0)}), PublicationId: fixturePointer("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111")}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.activation_id")
		}
		if !(value.RevisionId == "revision-a") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.revision_id")
		}
		if !(value.ReleaseDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.release_digest")
		}
		if !(value.RouteGeneration == uint64(9223372036854775808)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.route_generation")
		}
		if !(!(value.Success != nil)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.success.presence")
		}
		if !(value.DeclaredError != nil) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.presence")
		}
		if !((*value.DeclaredError).Code == "uncertain") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.code")
		}
		if !((*value.DeclaredError).Message == "provider outcome unknown") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.message")
		}
		if !(len((*value.DeclaredError).Payload) == 4) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.length")
		}
		if !((*value.DeclaredError).Payload[0] == 0) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.0")
		}
		if !((*value.DeclaredError).Payload[1] == 1) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.1")
		}
		if !((*value.DeclaredError).Payload[2] == 2) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.2")
		}
		if !((*value.DeclaredError).Payload[3] == 255) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.3")
		}
		if !((*value.DeclaredError).MediaType == "application/octet-stream") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type")
		}
		if !(len((*value.DeclaredError).Metadata) == 1) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.count")
		}
		if !((*value.DeclaredError).Metadata["contract"] == "latent:http/streaming@0.3.0") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0")
		}
		if !(!(value.PlatformFailure != nil)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.platform_failure.presence")
		}
		if !(value.Consumption != nil) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.presence")
		}
		if !((*value.Consumption).CpuFuel == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.cpu_fuel")
		}
		if !((*value.Consumption).PeakMemoryBytes == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.peak_memory_bytes")
		}
		if !((*value.Consumption).WallTimeMicros == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.wall_time_micros")
		}
		if !((*value.Consumption).ChildCalls == uint32(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.child_calls")
		}
		if !((*value.Consumption).OutboundRequests == uint32(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.outbound_requests")
		}
		if !((*value.Consumption).StateReadBytes == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.state_read_bytes")
		}
		if !((*value.Consumption).StateWriteBytes == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.state_write_bytes")
		}
		if !((*value.Consumption).BlobReadBytes == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.blob_read_bytes")
		}
		if !((*value.Consumption).BlobWriteBytes == uint64(18446744073709551615)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.blob_write_bytes")
		}
		if !((*value.Consumption).LogBytes == uint64(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.log_bytes")
		}
		if !((*value.Consumption).EffectCount == uint32(0)) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.consumption.effect_count")
		}
		if !(value.PublicationId != nil) {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.publication_id.presence")
		}
		if !((*value.PublicationId) == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111") {
			tester.Fatal("typed-declared-provider-uncertainty-retains-receipt.publication_id")
		}
	}
	{
		value := InvokeResponse{ActivationId: "activation-a", RevisionId: "", ReleaseDigest: "", RouteGeneration: uint64(0), PlatformFailure: fixturePointer(PlatformError{Code: "permission-denied", Message: "capability-provider-failed", Retryable: false, DetailItems: []ErrorDetail{ErrorDetail{Kind: "capability-observation", Fields: map[string]string{"capability": "latent:http/streaming@0.3.0", "state": "policy-revoked"}}, ErrorDetail{Kind: "future-detail", Fields: map[string]string{"bounded": "preserved"}}}}), Consumption: fixturePointer(BudgetConsumption{CpuFuel: uint64(0), PeakMemoryBytes: uint64(0), WallTimeMicros: uint64(0), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(18446744073709551615), EffectCount: uint32(0)})}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.activation_id")
		}
		if !(value.RevisionId == "") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.revision_id")
		}
		if !(value.ReleaseDigest == "") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.release_digest")
		}
		if !(value.RouteGeneration == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.route_generation")
		}
		if !(!(value.Success != nil)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.success.presence")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.declared_error.presence")
		}
		if !(value.PlatformFailure != nil) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.presence")
		}
		if !((*value.PlatformFailure).Code == "permission-denied") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.code")
		}
		if !((*value.PlatformFailure).Message == "capability-provider-failed") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.message")
		}
		if !((*value.PlatformFailure).Retryable == false) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.retryable")
		}
		if !(len((*value.PlatformFailure).DetailItems) == 2) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.count")
		}
		if !((*value.PlatformFailure).DetailItems[0].Kind == "capability-observation") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind")
		}
		if !(len((*value.PlatformFailure).DetailItems[0].Fields) == 2) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.count")
		}
		if !((*value.PlatformFailure).DetailItems[0].Fields["capability"] == "latent:http/streaming@0.3.0") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0")
		}
		if !((*value.PlatformFailure).DetailItems[0].Fields["state"] == "policy-revoked") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1")
		}
		if !((*value.PlatformFailure).DetailItems[1].Kind == "future-detail") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind")
		}
		if !(len((*value.PlatformFailure).DetailItems[1].Fields) == 1) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.count")
		}
		if !((*value.PlatformFailure).DetailItems[1].Fields["bounded"] == "preserved") {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0")
		}
		if !(value.Consumption != nil) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.presence")
		}
		if !((*value.Consumption).CpuFuel == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.cpu_fuel")
		}
		if !((*value.Consumption).PeakMemoryBytes == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.peak_memory_bytes")
		}
		if !((*value.Consumption).WallTimeMicros == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.wall_time_micros")
		}
		if !((*value.Consumption).ChildCalls == uint32(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.child_calls")
		}
		if !((*value.Consumption).OutboundRequests == uint32(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.outbound_requests")
		}
		if !((*value.Consumption).StateReadBytes == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.state_read_bytes")
		}
		if !((*value.Consumption).StateWriteBytes == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.state_write_bytes")
		}
		if !((*value.Consumption).BlobReadBytes == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.blob_read_bytes")
		}
		if !((*value.Consumption).BlobWriteBytes == uint64(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.blob_write_bytes")
		}
		if !((*value.Consumption).LogBytes == uint64(18446744073709551615)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.log_bytes")
		}
		if !((*value.Consumption).EffectCount == uint32(0)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.consumption.effect_count")
		}
		if !(!(value.PublicationId != nil)) {
			tester.Fatal("typed-platform-capability-failure-retains-detail-items.publication_id.presence")
		}
	}
	{
		value := InvokeResponse{ActivationId: "activation-a", RevisionId: "", ReleaseDigest: "", RouteGeneration: uint64(0), Success: fixturePointer(Success{Payload: []byte{}, MediaType: "", EffectIds: []string{}, Metadata: map[string]string{}}), PublicationId: fixturePointer("")}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("present-invalid-publication-not-legacy.activation_id")
		}
		if !(value.RevisionId == "") {
			tester.Fatal("present-invalid-publication-not-legacy.revision_id")
		}
		if !(value.ReleaseDigest == "") {
			tester.Fatal("present-invalid-publication-not-legacy.release_digest")
		}
		if !(value.RouteGeneration == uint64(0)) {
			tester.Fatal("present-invalid-publication-not-legacy.route_generation")
		}
		if !(value.Success != nil) {
			tester.Fatal("present-invalid-publication-not-legacy.success.presence")
		}
		if !(len((*value.Success).Payload) == 0) {
			tester.Fatal("present-invalid-publication-not-legacy.success.payload.length")
		}
		if !((*value.Success).MediaType == "") {
			tester.Fatal("present-invalid-publication-not-legacy.success.media_type")
		}
		if !(!((*value.Success).CommittedStateVersion != nil)) {
			tester.Fatal("present-invalid-publication-not-legacy.success.committed_state_version.presence")
		}
		if !(len((*value.Success).EffectIds) == 0) {
			tester.Fatal("present-invalid-publication-not-legacy.success.effect_ids.count")
		}
		if !(len((*value.Success).Metadata) == 0) {
			tester.Fatal("present-invalid-publication-not-legacy.success.metadata.count")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("present-invalid-publication-not-legacy.declared_error.presence")
		}
		if !(!(value.PlatformFailure != nil)) {
			tester.Fatal("present-invalid-publication-not-legacy.platform_failure.presence")
		}
		if !(!(value.Consumption != nil)) {
			tester.Fatal("present-invalid-publication-not-legacy.consumption.presence")
		}
		if !(value.PublicationId != nil) {
			tester.Fatal("present-invalid-publication-not-legacy.publication_id.presence")
		}
		if !((*value.PublicationId) == "") {
			tester.Fatal("present-invalid-publication-not-legacy.publication_id")
		}
	}
	{
		value := InvokeResponse{ActivationId: "activation-a", RevisionId: "", ReleaseDigest: "", RouteGeneration: uint64(0), Success: fixturePointer(Success{Payload: []byte{}, MediaType: "", EffectIds: []string{}, Metadata: map[string]string{}}), PlatformFailure: fixturePointer(PlatformError{Code: "internal", Message: "", Retryable: false, DetailItems: []ErrorDetail{}})}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("contradictory-outcome-retained-for-rejection.activation_id")
		}
		if !(value.RevisionId == "") {
			tester.Fatal("contradictory-outcome-retained-for-rejection.revision_id")
		}
		if !(value.ReleaseDigest == "") {
			tester.Fatal("contradictory-outcome-retained-for-rejection.release_digest")
		}
		if !(value.RouteGeneration == uint64(0)) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.route_generation")
		}
		if !(value.Success != nil) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.success.presence")
		}
		if !(len((*value.Success).Payload) == 0) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.success.payload.length")
		}
		if !((*value.Success).MediaType == "") {
			tester.Fatal("contradictory-outcome-retained-for-rejection.success.media_type")
		}
		if !(!((*value.Success).CommittedStateVersion != nil)) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.success.committed_state_version.presence")
		}
		if !(len((*value.Success).EffectIds) == 0) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.success.effect_ids.count")
		}
		if !(len((*value.Success).Metadata) == 0) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.success.metadata.count")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.declared_error.presence")
		}
		if !(value.PlatformFailure != nil) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.platform_failure.presence")
		}
		if !((*value.PlatformFailure).Code == "internal") {
			tester.Fatal("contradictory-outcome-retained-for-rejection.platform_failure.code")
		}
		if !((*value.PlatformFailure).Message == "") {
			tester.Fatal("contradictory-outcome-retained-for-rejection.platform_failure.message")
		}
		if !((*value.PlatformFailure).Retryable == false) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.platform_failure.retryable")
		}
		if !(len((*value.PlatformFailure).DetailItems) == 0) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.platform_failure.detail_items.count")
		}
		if !(!(value.Consumption != nil)) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.consumption.presence")
		}
		if !(!(value.PublicationId != nil)) {
			tester.Fatal("contradictory-outcome-retained-for-rejection.publication_id.presence")
		}
	}
	{
		value := CancelRequest{ActivationId: "activation-a", Reason: "caller-requested"}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("cancel-request-known-id.activation_id")
		}
		if !(value.Reason == "caller-requested") {
			tester.Fatal("cancel-request-known-id.reason")
		}
	}
	{
		value := CancelResponse{Disposition: CancelDisposition(1)}
		if !(int32(value.Disposition) == 1) {
			tester.Fatal("cancel-accepted-not-cleanup.disposition")
		}
		if !(!(value.TerminalState != nil)) {
			tester.Fatal("cancel-accepted-not-cleanup.terminal_state.presence")
		}
	}
	{
		value := CancelResponse{Disposition: CancelDisposition(2), TerminalState: fixturePointer("completed")}
		if !(int32(value.Disposition) == 2) {
			tester.Fatal("cancel-already-terminal.disposition")
		}
		if !(value.TerminalState != nil) {
			tester.Fatal("cancel-already-terminal.terminal_state.presence")
		}
		if !((*value.TerminalState) == "completed") {
			tester.Fatal("cancel-already-terminal.terminal_state")
		}
	}
	{
		value := CancelResponse{Disposition: CancelDisposition(3)}
		if !(int32(value.Disposition) == 3) {
			tester.Fatal("cancel-not-found-not-nonexecution.disposition")
		}
		if !(!(value.TerminalState != nil)) {
			tester.Fatal("cancel-not-found-not-nonexecution.terminal_state.presence")
		}
	}
	{
		value := CancelResponse{Disposition: CancelDisposition(0), TerminalState: fixturePointer("")}
		if !(int32(value.Disposition) == 0) {
			tester.Fatal("cancel-unspecified-not-accepted.disposition")
		}
		if !(value.TerminalState != nil) {
			tester.Fatal("cancel-unspecified-not-accepted.terminal_state.presence")
		}
		if !((*value.TerminalState) == "") {
			tester.Fatal("cancel-unspecified-not-accepted.terminal_state")
		}
	}
	{
		value := CancelResponse{Disposition: CancelDisposition(91), TerminalState: fixturePointer("future-terminal-state")}
		if !(int32(value.Disposition) == 91) {
			tester.Fatal("cancel-unknown-enum.disposition")
		}
		if !(value.TerminalState != nil) {
			tester.Fatal("cancel-unknown-enum.terminal_state.presence")
		}
		if !((*value.TerminalState) == "future-terminal-state") {
			tester.Fatal("cancel-unknown-enum.terminal_state")
		}
	}
	{
		value := CancelResponse{Disposition: CancelDisposition(-2147483648)}
		if !(int32(value.Disposition) == -2147483648) {
			tester.Fatal("cancel-negative-enum.disposition")
		}
		if !(!(value.TerminalState != nil)) {
			tester.Fatal("cancel-negative-enum.terminal_state.presence")
		}
	}
	{
		value := GetActivationRequest{ActivationId: "activation-a"}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("get-activation-recovery.activation_id")
		}
	}
	{
		value := ActivationStatus{ActivationId: "activation-a", Phase: "running", LastUpdatedUnixMillis: uint64(18446744073709551615), Metadata: map[string]string{}}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("activation-running-absent-terminal.activation_id")
		}
		if !(value.Phase == "running") {
			tester.Fatal("activation-running-absent-terminal.phase")
		}
		if !(!(value.TerminalState != nil)) {
			tester.Fatal("activation-running-absent-terminal.terminal_state.presence")
		}
		if !(value.LastUpdatedUnixMillis == uint64(18446744073709551615)) {
			tester.Fatal("activation-running-absent-terminal.last_updated_unix_millis")
		}
		if !(len(value.Metadata) == 0) {
			tester.Fatal("activation-running-absent-terminal.metadata.count")
		}
		if !(!(value.Succeeded != nil)) {
			tester.Fatal("activation-running-absent-terminal.succeeded.presence")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("activation-running-absent-terminal.declared_error.presence")
		}
		if !(!(value.PlatformFailure != nil)) {
			tester.Fatal("activation-running-absent-terminal.platform_failure.presence")
		}
		if !(!(value.FinalConsumption != nil)) {
			tester.Fatal("activation-running-absent-terminal.final_consumption.presence")
		}
		if !(!(value.TerminalAtUnixMillis != nil)) {
			tester.Fatal("activation-running-absent-terminal.terminal_at_unix_millis.presence")
		}
	}
	{
		value := ActivationStatus{ActivationId: "activation-a", Phase: "terminal", TerminalState: fixturePointer("failed"), LastUpdatedUnixMillis: uint64(0), Metadata: map[string]string{}, PlatformFailure: fixturePointer(PlatformError{Code: "resource-exhausted", Message: "capability-capacity", Retryable: false, DetailItems: []ErrorDetail{ErrorDetail{Kind: "budget", Fields: map[string]string{"resource": "buffer-bytes"}}}}), FinalConsumption: fixturePointer(BudgetConsumption{CpuFuel: uint64(0), PeakMemoryBytes: uint64(18446744073709551615), WallTimeMicros: uint64(0), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(0), EffectCount: uint32(0)}), TerminalAtUnixMillis: fixturePointer(uint64(0))}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("activation-terminal-typed-failure.activation_id")
		}
		if !(value.Phase == "terminal") {
			tester.Fatal("activation-terminal-typed-failure.phase")
		}
		if !(value.TerminalState != nil) {
			tester.Fatal("activation-terminal-typed-failure.terminal_state.presence")
		}
		if !((*value.TerminalState) == "failed") {
			tester.Fatal("activation-terminal-typed-failure.terminal_state")
		}
		if !(value.LastUpdatedUnixMillis == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.last_updated_unix_millis")
		}
		if !(len(value.Metadata) == 0) {
			tester.Fatal("activation-terminal-typed-failure.metadata.count")
		}
		if !(!(value.Succeeded != nil)) {
			tester.Fatal("activation-terminal-typed-failure.succeeded.presence")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("activation-terminal-typed-failure.declared_error.presence")
		}
		if !(value.PlatformFailure != nil) {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.presence")
		}
		if !((*value.PlatformFailure).Code == "resource-exhausted") {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.code")
		}
		if !((*value.PlatformFailure).Message == "capability-capacity") {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.message")
		}
		if !((*value.PlatformFailure).Retryable == false) {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.retryable")
		}
		if !(len((*value.PlatformFailure).DetailItems) == 1) {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.detail_items.count")
		}
		if !((*value.PlatformFailure).DetailItems[0].Kind == "budget") {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.detail_items.0.kind")
		}
		if !(len((*value.PlatformFailure).DetailItems[0].Fields) == 1) {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.detail_items.0.fields.count")
		}
		if !((*value.PlatformFailure).DetailItems[0].Fields["resource"] == "buffer-bytes") {
			tester.Fatal("activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0")
		}
		if !(value.FinalConsumption != nil) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.presence")
		}
		if !((*value.FinalConsumption).CpuFuel == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.cpu_fuel")
		}
		if !((*value.FinalConsumption).PeakMemoryBytes == uint64(18446744073709551615)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.peak_memory_bytes")
		}
		if !((*value.FinalConsumption).WallTimeMicros == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.wall_time_micros")
		}
		if !((*value.FinalConsumption).ChildCalls == uint32(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.child_calls")
		}
		if !((*value.FinalConsumption).OutboundRequests == uint32(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.outbound_requests")
		}
		if !((*value.FinalConsumption).StateReadBytes == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.state_read_bytes")
		}
		if !((*value.FinalConsumption).StateWriteBytes == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.state_write_bytes")
		}
		if !((*value.FinalConsumption).BlobReadBytes == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.blob_read_bytes")
		}
		if !((*value.FinalConsumption).BlobWriteBytes == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.blob_write_bytes")
		}
		if !((*value.FinalConsumption).LogBytes == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.log_bytes")
		}
		if !((*value.FinalConsumption).EffectCount == uint32(0)) {
			tester.Fatal("activation-terminal-typed-failure.final_consumption.effect_count")
		}
		if !(value.TerminalAtUnixMillis != nil) {
			tester.Fatal("activation-terminal-typed-failure.terminal_at_unix_millis.presence")
		}
		if !((*value.TerminalAtUnixMillis) == uint64(0)) {
			tester.Fatal("activation-terminal-typed-failure.terminal_at_unix_millis")
		}
	}
	{
		value := ActivationStatus{ActivationId: "activation-a", Phase: "terminal", TerminalState: fixturePointer("completed"), LastUpdatedUnixMillis: uint64(0), Metadata: map[string]string{}, Succeeded: fixturePointer(ActivationSuccessSummary{CommittedStateVersion: fixturePointer("state-a"), EffectIds: []string{"effect-a"}, Metadata: map[string]string{"retained": "true"}}), FinalConsumption: fixturePointer(BudgetConsumption{CpuFuel: uint64(0), PeakMemoryBytes: uint64(0), WallTimeMicros: uint64(0), ChildCalls: uint32(0), OutboundRequests: uint32(0), StateReadBytes: uint64(0), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(0), EffectCount: uint32(4294967295)}), TerminalAtUnixMillis: fixturePointer(uint64(18446744073709551615))}
		if !(value.ActivationId == "activation-a") {
			tester.Fatal("activation-terminal-success-summary.activation_id")
		}
		if !(value.Phase == "terminal") {
			tester.Fatal("activation-terminal-success-summary.phase")
		}
		if !(value.TerminalState != nil) {
			tester.Fatal("activation-terminal-success-summary.terminal_state.presence")
		}
		if !((*value.TerminalState) == "completed") {
			tester.Fatal("activation-terminal-success-summary.terminal_state")
		}
		if !(value.LastUpdatedUnixMillis == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.last_updated_unix_millis")
		}
		if !(len(value.Metadata) == 0) {
			tester.Fatal("activation-terminal-success-summary.metadata.count")
		}
		if !(value.Succeeded != nil) {
			tester.Fatal("activation-terminal-success-summary.succeeded.presence")
		}
		if !((*value.Succeeded).CommittedStateVersion != nil) {
			tester.Fatal("activation-terminal-success-summary.succeeded.committed_state_version.presence")
		}
		if !((*(*value.Succeeded).CommittedStateVersion) == "state-a") {
			tester.Fatal("activation-terminal-success-summary.succeeded.committed_state_version")
		}
		if !(len((*value.Succeeded).EffectIds) == 1) {
			tester.Fatal("activation-terminal-success-summary.succeeded.effect_ids.count")
		}
		if !((*value.Succeeded).EffectIds[0] == "effect-a") {
			tester.Fatal("activation-terminal-success-summary.succeeded.effect_ids.0")
		}
		if !(len((*value.Succeeded).Metadata) == 1) {
			tester.Fatal("activation-terminal-success-summary.succeeded.metadata.count")
		}
		if !((*value.Succeeded).Metadata["retained"] == "true") {
			tester.Fatal("activation-terminal-success-summary.succeeded.metadata.0")
		}
		if !(!(value.DeclaredError != nil)) {
			tester.Fatal("activation-terminal-success-summary.declared_error.presence")
		}
		if !(!(value.PlatformFailure != nil)) {
			tester.Fatal("activation-terminal-success-summary.platform_failure.presence")
		}
		if !(value.FinalConsumption != nil) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.presence")
		}
		if !((*value.FinalConsumption).CpuFuel == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.cpu_fuel")
		}
		if !((*value.FinalConsumption).PeakMemoryBytes == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.peak_memory_bytes")
		}
		if !((*value.FinalConsumption).WallTimeMicros == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.wall_time_micros")
		}
		if !((*value.FinalConsumption).ChildCalls == uint32(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.child_calls")
		}
		if !((*value.FinalConsumption).OutboundRequests == uint32(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.outbound_requests")
		}
		if !((*value.FinalConsumption).StateReadBytes == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.state_read_bytes")
		}
		if !((*value.FinalConsumption).StateWriteBytes == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.state_write_bytes")
		}
		if !((*value.FinalConsumption).BlobReadBytes == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.blob_read_bytes")
		}
		if !((*value.FinalConsumption).BlobWriteBytes == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.blob_write_bytes")
		}
		if !((*value.FinalConsumption).LogBytes == uint64(0)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.log_bytes")
		}
		if !((*value.FinalConsumption).EffectCount == uint32(4294967295)) {
			tester.Fatal("activation-terminal-success-summary.final_consumption.effect_count")
		}
		if !(value.TerminalAtUnixMillis != nil) {
			tester.Fatal("activation-terminal-success-summary.terminal_at_unix_millis.presence")
		}
		if !((*value.TerminalAtUnixMillis) == uint64(18446744073709551615)) {
			tester.Fatal("activation-terminal-success-summary.terminal_at_unix_millis")
		}
	}
	{
		value := GetPolicyResponse{}
		if !(!(value.Policy != nil)) {
			tester.Fatal("policy-absence.policy.presence")
		}
	}
	{
		value := GetPolicyRequest{Id: "policy-a", RecordKind: CapabilityPolicyRecordKind(1)}
		if !(value.Id == "policy-a") {
			tester.Fatal("policy-record-kind.id")
		}
		if !(int32(value.RecordKind) == 1) {
			tester.Fatal("policy-record-kind.record_kind")
		}
	}
	{
		value := GetPolicyRequest{Id: "binding-a", RecordKind: CapabilityPolicyRecordKind(2)}
		if !(value.Id == "binding-a") {
			tester.Fatal("provider-binding-record-kind.id")
		}
		if !(int32(value.RecordKind) == 2) {
			tester.Fatal("provider-binding-record-kind.record_kind")
		}
	}
	{
		value := Policy{Id: "future-record", Metadata: fixturePointer(ObjectMetadata{Name: "future-record", Tenant: fixturePointer(""), Namespace: fixturePointer(""), Labels: map[string]string{"sampled": "true"}, Annotations: map[string]string{"descriptive": "not-authority"}}), Document: "", Generation: uint64(18446744073709551615), Language: "", RecordKind: CapabilityPolicyRecordKind(2147483647), ContentDigest: "", Revoked: true}
		if !(value.Id == "future-record") {
			tester.Fatal("unknown-policy-kind.id")
		}
		if !(value.Metadata != nil) {
			tester.Fatal("unknown-policy-kind.metadata.presence")
		}
		if !((*value.Metadata).Name == "future-record") {
			tester.Fatal("unknown-policy-kind.metadata.name")
		}
		if !((*value.Metadata).Tenant != nil) {
			tester.Fatal("unknown-policy-kind.metadata.tenant.presence")
		}
		if !((*(*value.Metadata).Tenant) == "") {
			tester.Fatal("unknown-policy-kind.metadata.tenant")
		}
		if !((*value.Metadata).Namespace != nil) {
			tester.Fatal("unknown-policy-kind.metadata.namespace.presence")
		}
		if !((*(*value.Metadata).Namespace) == "") {
			tester.Fatal("unknown-policy-kind.metadata.namespace")
		}
		if !(len((*value.Metadata).Labels) == 1) {
			tester.Fatal("unknown-policy-kind.metadata.labels.count")
		}
		if !((*value.Metadata).Labels["sampled"] == "true") {
			tester.Fatal("unknown-policy-kind.metadata.labels.0")
		}
		if !(len((*value.Metadata).Annotations) == 1) {
			tester.Fatal("unknown-policy-kind.metadata.annotations.count")
		}
		if !((*value.Metadata).Annotations["descriptive"] == "not-authority") {
			tester.Fatal("unknown-policy-kind.metadata.annotations.0")
		}
		if !(value.Document == "") {
			tester.Fatal("unknown-policy-kind.document")
		}
		if !(value.Generation == uint64(18446744073709551615)) {
			tester.Fatal("unknown-policy-kind.generation")
		}
		if !(value.Language == "") {
			tester.Fatal("unknown-policy-kind.language")
		}
		if !(int32(value.RecordKind) == 2147483647) {
			tester.Fatal("unknown-policy-kind.record_kind")
		}
		if !(value.ContentDigest == "") {
			tester.Fatal("unknown-policy-kind.content_digest")
		}
		if !(value.Revoked == true) {
			tester.Fatal("unknown-policy-kind.revoked")
		}
	}
	{
		value := ApplyPolicyRequest{OperationId: "operation-a"}
		if !(!(value.Policy != nil)) {
			tester.Fatal("apply-missing-generation.policy.presence")
		}
		if !(!(value.ExpectedGeneration != nil)) {
			tester.Fatal("apply-missing-generation.expected_generation.presence")
		}
		if !(value.OperationId == "operation-a") {
			tester.Fatal("apply-missing-generation.operation_id")
		}
	}
	{
		value := ApplyPolicyRequest{ExpectedGeneration: fixturePointer(uint64(0)), OperationId: ""}
		if !(!(value.Policy != nil)) {
			tester.Fatal("apply-present-empty-operation.policy.presence")
		}
		if !(value.ExpectedGeneration != nil) {
			tester.Fatal("apply-present-empty-operation.expected_generation.presence")
		}
		if !((*value.ExpectedGeneration) == uint64(0)) {
			tester.Fatal("apply-present-empty-operation.expected_generation")
		}
		if !(value.OperationId == "") {
			tester.Fatal("apply-present-empty-operation.operation_id")
		}
	}
	{
		value := ApplyPolicyRequest{Policy: fixturePointer(Policy{Id: "policy-a", Metadata: fixturePointer(ObjectMetadata{Name: "policy-a", Tenant: fixturePointer("tenant-a"), Labels: map[string]string{}, Annotations: map[string]string{}}), Document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", Generation: uint64(0), Language: "lsf-capability-policy-v1", RecordKind: CapabilityPolicyRecordKind(1), ContentDigest: "", Revoked: false}), ExpectedGeneration: fixturePointer(uint64(0)), OperationId: "operation-a"}
		if !(value.Policy != nil) {
			tester.Fatal("apply-create-policy-zero-generation.policy.presence")
		}
		if !((*value.Policy).Id == "policy-a") {
			tester.Fatal("apply-create-policy-zero-generation.policy.id")
		}
		if !((*value.Policy).Metadata != nil) {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.presence")
		}
		if !((*(*value.Policy).Metadata).Name == "policy-a") {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.name")
		}
		if !((*(*value.Policy).Metadata).Tenant != nil) {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.tenant.presence")
		}
		if !((*(*(*value.Policy).Metadata).Tenant) == "tenant-a") {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.tenant")
		}
		if !(!((*(*value.Policy).Metadata).Namespace != nil)) {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.namespace.presence")
		}
		if !(len((*(*value.Policy).Metadata).Labels) == 0) {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.labels.count")
		}
		if !(len((*(*value.Policy).Metadata).Annotations) == 0) {
			tester.Fatal("apply-create-policy-zero-generation.policy.metadata.annotations.count")
		}
		if !((*value.Policy).Document == "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}") {
			tester.Fatal("apply-create-policy-zero-generation.policy.document")
		}
		if !((*value.Policy).Generation == uint64(0)) {
			tester.Fatal("apply-create-policy-zero-generation.policy.generation")
		}
		if !((*value.Policy).Language == "lsf-capability-policy-v1") {
			tester.Fatal("apply-create-policy-zero-generation.policy.language")
		}
		if !(int32((*value.Policy).RecordKind) == 1) {
			tester.Fatal("apply-create-policy-zero-generation.policy.record_kind")
		}
		if !((*value.Policy).ContentDigest == "") {
			tester.Fatal("apply-create-policy-zero-generation.policy.content_digest")
		}
		if !((*value.Policy).Revoked == false) {
			tester.Fatal("apply-create-policy-zero-generation.policy.revoked")
		}
		if !(value.ExpectedGeneration != nil) {
			tester.Fatal("apply-create-policy-zero-generation.expected_generation.presence")
		}
		if !((*value.ExpectedGeneration) == uint64(0)) {
			tester.Fatal("apply-create-policy-zero-generation.expected_generation")
		}
		if !(value.OperationId == "operation-a") {
			tester.Fatal("apply-create-policy-zero-generation.operation_id")
		}
	}
	{
		value := ApplyPolicyRequest{Policy: fixturePointer(Policy{Id: "binding-a", Metadata: fixturePointer(ObjectMetadata{Name: "binding-a", Tenant: fixturePointer("tenant-a"), Labels: map[string]string{}, Annotations: map[string]string{}}), Document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", Generation: uint64(0), Language: "lsf-provider-binding-v1", RecordKind: CapabilityPolicyRecordKind(2), ContentDigest: "", Revoked: false}), ExpectedGeneration: fixturePointer(uint64(18446744073709551615)), OperationId: "operation-binding"}
		if !(value.Policy != nil) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.presence")
		}
		if !((*value.Policy).Id == "binding-a") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.id")
		}
		if !((*value.Policy).Metadata != nil) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.presence")
		}
		if !((*(*value.Policy).Metadata).Name == "binding-a") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name")
		}
		if !((*(*value.Policy).Metadata).Tenant != nil) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.presence")
		}
		if !((*(*(*value.Policy).Metadata).Tenant) == "tenant-a") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant")
		}
		if !(!((*(*value.Policy).Metadata).Namespace != nil)) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.namespace.presence")
		}
		if !(len((*(*value.Policy).Metadata).Labels) == 0) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.labels.count")
		}
		if !(len((*(*value.Policy).Metadata).Annotations) == 0) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.annotations.count")
		}
		if !((*value.Policy).Document == "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.document")
		}
		if !((*value.Policy).Generation == uint64(0)) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.generation")
		}
		if !((*value.Policy).Language == "lsf-provider-binding-v1") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.language")
		}
		if !(int32((*value.Policy).RecordKind) == 2) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.record_kind")
		}
		if !((*value.Policy).ContentDigest == "") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.content_digest")
		}
		if !((*value.Policy).Revoked == false) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.policy.revoked")
		}
		if !(value.ExpectedGeneration != nil) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.expected_generation.presence")
		}
		if !((*value.ExpectedGeneration) == uint64(18446744073709551615)) {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.expected_generation")
		}
		if !(value.OperationId == "operation-binding") {
			tester.Fatal("apply-binding-max-precondition-and-opaque-limit-document.operation_id")
		}
	}
	{
		value := ListPoliciesRequest{RecordKind: CapabilityPolicyRecordKind(1)}
		if !(int32(value.RecordKind) == 1) {
			tester.Fatal("policy-page-absent.record_kind")
		}
		if !(!(value.Page != nil)) {
			tester.Fatal("policy-page-absent.page.presence")
		}
	}
	{
		value := ListPoliciesRequest{RecordKind: CapabilityPolicyRecordKind(2), Page: fixturePointer(PageRequest{PageSize: uint32(0)})}
		if !(int32(value.RecordKind) == 2) {
			tester.Fatal("policy-page-zero-invalid.record_kind")
		}
		if !(value.Page != nil) {
			tester.Fatal("policy-page-zero-invalid.page.presence")
		}
		if !((*value.Page).PageSize == uint32(0)) {
			tester.Fatal("policy-page-zero-invalid.page.page_size")
		}
		if !(!((*value.Page).PageToken != nil)) {
			tester.Fatal("policy-page-zero-invalid.page.page_token.presence")
		}
	}
	{
		value := ListPoliciesRequest{RecordKind: CapabilityPolicyRecordKind(1), Page: fixturePointer(PageRequest{PageSize: uint32(1), PageToken: fixturePointer("")})}
		if !(int32(value.RecordKind) == 1) {
			tester.Fatal("policy-page-empty-token-invalid.record_kind")
		}
		if !(value.Page != nil) {
			tester.Fatal("policy-page-empty-token-invalid.page.presence")
		}
		if !((*value.Page).PageSize == uint32(1)) {
			tester.Fatal("policy-page-empty-token-invalid.page.page_size")
		}
		if !((*value.Page).PageToken != nil) {
			tester.Fatal("policy-page-empty-token-invalid.page.page_token.presence")
		}
		if !((*(*value.Page).PageToken) == "") {
			tester.Fatal("policy-page-empty-token-invalid.page.page_token")
		}
	}
	{
		value := ListPoliciesResponse{Policies: []Policy{Policy{Id: "policy-a", Document: "", Generation: uint64(18446744073709551615), Language: "", RecordKind: CapabilityPolicyRecordKind(1), ContentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Revoked: true}}, CatalogGeneration: uint64(18446744073709551615), Page: fixturePointer(PageResponse{NextPageToken: fixturePointer("opaque-policy-cursor")})}
		if !(len(value.Policies) == 1) {
			tester.Fatal("policy-page-first.policies.count")
		}
		if !(value.Policies[0].Id == "policy-a") {
			tester.Fatal("policy-page-first.policies.0.id")
		}
		if !(!(value.Policies[0].Metadata != nil)) {
			tester.Fatal("policy-page-first.policies.0.metadata.presence")
		}
		if !(value.Policies[0].Document == "") {
			tester.Fatal("policy-page-first.policies.0.document")
		}
		if !(value.Policies[0].Generation == uint64(18446744073709551615)) {
			tester.Fatal("policy-page-first.policies.0.generation")
		}
		if !(value.Policies[0].Language == "") {
			tester.Fatal("policy-page-first.policies.0.language")
		}
		if !(int32(value.Policies[0].RecordKind) == 1) {
			tester.Fatal("policy-page-first.policies.0.record_kind")
		}
		if !(value.Policies[0].ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("policy-page-first.policies.0.content_digest")
		}
		if !(value.Policies[0].Revoked == true) {
			tester.Fatal("policy-page-first.policies.0.revoked")
		}
		if !(value.CatalogGeneration == uint64(18446744073709551615)) {
			tester.Fatal("policy-page-first.catalog_generation")
		}
		if !(value.Page != nil) {
			tester.Fatal("policy-page-first.page.presence")
		}
		if !((*value.Page).NextPageToken != nil) {
			tester.Fatal("policy-page-first.page.next_page_token.presence")
		}
		if !((*(*value.Page).NextPageToken) == "opaque-policy-cursor") {
			tester.Fatal("policy-page-first.page.next_page_token")
		}
	}
	{
		value := ListPoliciesResponse{Policies: []Policy{}, CatalogGeneration: uint64(18446744073709551615), Page: fixturePointer(PageResponse{})}
		if !(len(value.Policies) == 0) {
			tester.Fatal("policy-page-last.policies.count")
		}
		if !(value.CatalogGeneration == uint64(18446744073709551615)) {
			tester.Fatal("policy-page-last.catalog_generation")
		}
		if !(value.Page != nil) {
			tester.Fatal("policy-page-last.page.presence")
		}
		if !(!((*value.Page).NextPageToken != nil)) {
			tester.Fatal("policy-page-last.page.next_page_token.presence")
		}
	}
	{
		value := ListPoliciesRequest{RecordKind: CapabilityPolicyRecordKind(1), Page: fixturePointer(PageRequest{PageSize: uint32(1), PageToken: fixturePointer("opaque-policy-cursor")})}
		if !(int32(value.RecordKind) == 1) {
			tester.Fatal("policy-next-page-request.record_kind")
		}
		if !(value.Page != nil) {
			tester.Fatal("policy-next-page-request.page.presence")
		}
		if !((*value.Page).PageSize == uint32(1)) {
			tester.Fatal("policy-next-page-request.page.page_size")
		}
		if !((*value.Page).PageToken != nil) {
			tester.Fatal("policy-next-page-request.page.page_token.presence")
		}
		if !((*(*value.Page).PageToken) == "opaque-policy-cursor") {
			tester.Fatal("policy-next-page-request.page.page_token")
		}
	}
	{
		value := ApplyPolicyResponse{Policy: fixturePointer(Policy{Id: "policy-a", Document: "", Generation: uint64(18446744073709551615), Language: "", RecordKind: CapabilityPolicyRecordKind(1), ContentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Revoked: false}), Receipt: fixturePointer(CapabilityPolicyOperation{OperationId: "operation-a", Tenant: "tenant-a", Id: "policy-a", RecordKind: CapabilityPolicyRecordKind(1), Generation: uint64(18446744073709551615), ContentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Revoked: false})}
		if !(value.Policy != nil) {
			tester.Fatal("apply-retains-original-receipt.policy.presence")
		}
		if !((*value.Policy).Id == "policy-a") {
			tester.Fatal("apply-retains-original-receipt.policy.id")
		}
		if !(!((*value.Policy).Metadata != nil)) {
			tester.Fatal("apply-retains-original-receipt.policy.metadata.presence")
		}
		if !((*value.Policy).Document == "") {
			tester.Fatal("apply-retains-original-receipt.policy.document")
		}
		if !((*value.Policy).Generation == uint64(18446744073709551615)) {
			tester.Fatal("apply-retains-original-receipt.policy.generation")
		}
		if !((*value.Policy).Language == "") {
			tester.Fatal("apply-retains-original-receipt.policy.language")
		}
		if !(int32((*value.Policy).RecordKind) == 1) {
			tester.Fatal("apply-retains-original-receipt.policy.record_kind")
		}
		if !((*value.Policy).ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("apply-retains-original-receipt.policy.content_digest")
		}
		if !((*value.Policy).Revoked == false) {
			tester.Fatal("apply-retains-original-receipt.policy.revoked")
		}
		if !(value.Receipt != nil) {
			tester.Fatal("apply-retains-original-receipt.receipt.presence")
		}
		if !((*value.Receipt).OperationId == "operation-a") {
			tester.Fatal("apply-retains-original-receipt.receipt.operation_id")
		}
		if !((*value.Receipt).Tenant == "tenant-a") {
			tester.Fatal("apply-retains-original-receipt.receipt.tenant")
		}
		if !((*value.Receipt).Id == "policy-a") {
			tester.Fatal("apply-retains-original-receipt.receipt.id")
		}
		if !(int32((*value.Receipt).RecordKind) == 1) {
			tester.Fatal("apply-retains-original-receipt.receipt.record_kind")
		}
		if !((*value.Receipt).Generation == uint64(18446744073709551615)) {
			tester.Fatal("apply-retains-original-receipt.receipt.generation")
		}
		if !((*value.Receipt).ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("apply-retains-original-receipt.receipt.content_digest")
		}
		if !((*value.Receipt).Revoked == false) {
			tester.Fatal("apply-retains-original-receipt.receipt.revoked")
		}
	}
	{
		value := GetPolicyOperationRequest{OperationId: "operation-a"}
		if !(value.OperationId == "operation-a") {
			tester.Fatal("get-policy-operation-known-id.operation_id")
		}
	}
	{
		value := GetPolicyOperationResponse{}
		if !(!(value.Receipt != nil)) {
			tester.Fatal("operation-recovery-not-retained-is-unknown.receipt.presence")
		}
	}
	{
		value := GetPolicyOperationResponse{Receipt: fixturePointer(CapabilityPolicyOperation{OperationId: "operation-a", Tenant: "tenant-a", Id: "policy-a", RecordKind: CapabilityPolicyRecordKind(1), Generation: uint64(18446744073709551615), ContentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Revoked: false})}
		if !(value.Receipt != nil) {
			tester.Fatal("operation-recovery-original-receipt.receipt.presence")
		}
		if !((*value.Receipt).OperationId == "operation-a") {
			tester.Fatal("operation-recovery-original-receipt.receipt.operation_id")
		}
		if !((*value.Receipt).Tenant == "tenant-a") {
			tester.Fatal("operation-recovery-original-receipt.receipt.tenant")
		}
		if !((*value.Receipt).Id == "policy-a") {
			tester.Fatal("operation-recovery-original-receipt.receipt.id")
		}
		if !(int32((*value.Receipt).RecordKind) == 1) {
			tester.Fatal("operation-recovery-original-receipt.receipt.record_kind")
		}
		if !((*value.Receipt).Generation == uint64(18446744073709551615)) {
			tester.Fatal("operation-recovery-original-receipt.receipt.generation")
		}
		if !((*value.Receipt).ContentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("operation-recovery-original-receipt.receipt.content_digest")
		}
		if !((*value.Receipt).Revoked == false) {
			tester.Fatal("operation-recovery-original-receipt.receipt.revoked")
		}
	}
	{
		value := ListCapabilitiesRequest{DeploymentId: "deployment-a", IncludeNodeUsage: false}
		if !(!(value.ContractPrefix != nil)) {
			tester.Fatal("capabilities-absent-page-default.contract_prefix.presence")
		}
		if !(!(value.Provider != nil)) {
			tester.Fatal("capabilities-absent-page-default.provider.presence")
		}
		if !(!(value.Page != nil)) {
			tester.Fatal("capabilities-absent-page-default.page.presence")
		}
		if !(value.DeploymentId == "deployment-a") {
			tester.Fatal("capabilities-absent-page-default.deployment_id")
		}
		if !(value.IncludeNodeUsage == false) {
			tester.Fatal("capabilities-absent-page-default.include_node_usage")
		}
	}
	{
		value := ListCapabilitiesRequest{Page: fixturePointer(PageRequest{PageSize: uint32(0)}), DeploymentId: "deployment-a", IncludeNodeUsage: false}
		if !(!(value.ContractPrefix != nil)) {
			tester.Fatal("capabilities-zero-page-default.contract_prefix.presence")
		}
		if !(!(value.Provider != nil)) {
			tester.Fatal("capabilities-zero-page-default.provider.presence")
		}
		if !(value.Page != nil) {
			tester.Fatal("capabilities-zero-page-default.page.presence")
		}
		if !((*value.Page).PageSize == uint32(0)) {
			tester.Fatal("capabilities-zero-page-default.page.page_size")
		}
		if !(!((*value.Page).PageToken != nil)) {
			tester.Fatal("capabilities-zero-page-default.page.page_token.presence")
		}
		if !(value.DeploymentId == "deployment-a") {
			tester.Fatal("capabilities-zero-page-default.deployment_id")
		}
		if !(value.IncludeNodeUsage == false) {
			tester.Fatal("capabilities-zero-page-default.include_node_usage")
		}
	}
	{
		value := ListCapabilitiesRequest{ContractPrefix: fixturePointer(""), Provider: fixturePointer(""), Page: fixturePointer(PageRequest{PageSize: uint32(128)}), DeploymentId: "deployment-a", IncludeNodeUsage: true}
		if !(value.ContractPrefix != nil) {
			tester.Fatal("capabilities-present-empty-filters.contract_prefix.presence")
		}
		if !((*value.ContractPrefix) == "") {
			tester.Fatal("capabilities-present-empty-filters.contract_prefix")
		}
		if !(value.Provider != nil) {
			tester.Fatal("capabilities-present-empty-filters.provider.presence")
		}
		if !((*value.Provider) == "") {
			tester.Fatal("capabilities-present-empty-filters.provider")
		}
		if !(value.Page != nil) {
			tester.Fatal("capabilities-present-empty-filters.page.presence")
		}
		if !((*value.Page).PageSize == uint32(128)) {
			tester.Fatal("capabilities-present-empty-filters.page.page_size")
		}
		if !(!((*value.Page).PageToken != nil)) {
			tester.Fatal("capabilities-present-empty-filters.page.page_token.presence")
		}
		if !(value.DeploymentId == "deployment-a") {
			tester.Fatal("capabilities-present-empty-filters.deployment_id")
		}
		if !(value.IncludeNodeUsage == true) {
			tester.Fatal("capabilities-present-empty-filters.include_node_usage")
		}
	}
	{
		value := ListCapabilitiesRequest{Page: fixturePointer(PageRequest{PageSize: uint32(1)}), DeploymentId: "", IncludeNodeUsage: false}
		if !(!(value.ContractPrefix != nil)) {
			tester.Fatal("capabilities-explicit-deployment-required.contract_prefix.presence")
		}
		if !(!(value.Provider != nil)) {
			tester.Fatal("capabilities-explicit-deployment-required.provider.presence")
		}
		if !(value.Page != nil) {
			tester.Fatal("capabilities-explicit-deployment-required.page.presence")
		}
		if !((*value.Page).PageSize == uint32(1)) {
			tester.Fatal("capabilities-explicit-deployment-required.page.page_size")
		}
		if !(!((*value.Page).PageToken != nil)) {
			tester.Fatal("capabilities-explicit-deployment-required.page.page_token.presence")
		}
		if !(value.DeploymentId == "") {
			tester.Fatal("capabilities-explicit-deployment-required.deployment_id")
		}
		if !(value.IncludeNodeUsage == false) {
			tester.Fatal("capabilities-explicit-deployment-required.include_node_usage")
		}
	}
	{
		value := ListCapabilitiesRequest{Page: fixturePointer(PageRequest{PageSize: uint32(4294967295)}), DeploymentId: "deployment-a", IncludeNodeUsage: false}
		if !(!(value.ContractPrefix != nil)) {
			tester.Fatal("capabilities-page-too-large.contract_prefix.presence")
		}
		if !(!(value.Provider != nil)) {
			tester.Fatal("capabilities-page-too-large.provider.presence")
		}
		if !(value.Page != nil) {
			tester.Fatal("capabilities-page-too-large.page.presence")
		}
		if !((*value.Page).PageSize == uint32(4294967295)) {
			tester.Fatal("capabilities-page-too-large.page.page_size")
		}
		if !(!((*value.Page).PageToken != nil)) {
			tester.Fatal("capabilities-page-too-large.page.page_token.presence")
		}
		if !(value.DeploymentId == "deployment-a") {
			tester.Fatal("capabilities-page-too-large.deployment_id")
		}
		if !(value.IncludeNodeUsage == false) {
			tester.Fatal("capabilities-page-too-large.include_node_usage")
		}
	}
	{
		value := ListCapabilitiesResponse{Capabilities: []CapabilityDescriptor{CapabilityDescriptor{Id: "latent:secrets/reader@0.1.0", Contract: "latent:secrets/reader@0.1.0", Provider: "local-secrets-v1", Operations: []string{"read"}, Attributes: map[string]string{}, Inspection: fixturePointer(CapabilityBindingInspection{DefinitionDigest: fixturePointer(""), ProviderBinding: fixturePointer(CapabilityInspectionPolicy{Id: "binding-a", Revision: uint64(18446744073709551615), Digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}), Policies: []CapabilityInspectionPolicy{CapabilityInspectionPolicy{Id: "policy-a", Revision: uint64(9223372036854775808), Digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}, ProviderProfile: "local-secrets-v1", ProviderConfigurationDigest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", ProviderConfigurationEpoch: uint64(18446744073709551615), State: "provider-configuration-changed"})}, CapabilityDescriptor{Id: "future-capability", Contract: "future-contract", Provider: "future-provider", Operations: []string{}, Attributes: map[string]string{"descriptive": "not-authority"}}}, Page: fixturePointer(PageResponse{NextPageToken: fixturePointer("opaque-capability-cursor")}), Revision: fixturePointer(CapabilityInspectionRevision{DeploymentId: "deployment-a", RevisionId: "revision-a", ComponentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", PublicationId: fixturePointer("publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"), RouteGeneration: uint64(18446744073709551615), CatalogTransaction: uint64(9223372036854775808)}), TenantUsage: fixturePointer(CapabilityResourceUsage{Scope: "tenant", Counters: map[string]uint64{"sessions": uint64(18446744073709551615), "calls": uint64(0)}, Unavailable: []string{"fixture-owner-unavailable"}}), State: "sampled"}
		if !(len(value.Capabilities) == 2) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.count")
		}
		if !(value.Capabilities[0].Id == "latent:secrets/reader@0.1.0") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.id")
		}
		if !(value.Capabilities[0].Contract == "latent:secrets/reader@0.1.0") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.contract")
		}
		if !(value.Capabilities[0].Provider == "local-secrets-v1") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.provider")
		}
		if !(len(value.Capabilities[0].Operations) == 1) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.operations.count")
		}
		if !(value.Capabilities[0].Operations[0] == "read") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.operations.0")
		}
		if !(len(value.Capabilities[0].Attributes) == 0) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.attributes.count")
		}
		if !(value.Capabilities[0].Inspection != nil) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.presence")
		}
		if !((*value.Capabilities[0].Inspection).DefinitionDigest != nil) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.presence")
		}
		if !((*(*value.Capabilities[0].Inspection).DefinitionDigest) == "") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest")
		}
		if !((*value.Capabilities[0].Inspection).ProviderBinding != nil) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.presence")
		}
		if !((*(*value.Capabilities[0].Inspection).ProviderBinding).Id == "binding-a") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id")
		}
		if !((*(*value.Capabilities[0].Inspection).ProviderBinding).Revision == uint64(18446744073709551615)) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.revision")
		}
		if !((*(*value.Capabilities[0].Inspection).ProviderBinding).Digest == "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest")
		}
		if !(len((*value.Capabilities[0].Inspection).Policies) == 1) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.policies.count")
		}
		if !((*value.Capabilities[0].Inspection).Policies[0].Id == "policy-a") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id")
		}
		if !((*value.Capabilities[0].Inspection).Policies[0].Revision == uint64(9223372036854775808)) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.revision")
		}
		if !((*value.Capabilities[0].Inspection).Policies[0].Digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest")
		}
		if !((*value.Capabilities[0].Inspection).ProviderProfile == "local-secrets-v1") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile")
		}
		if !((*value.Capabilities[0].Inspection).ProviderConfigurationDigest == "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest")
		}
		if !((*value.Capabilities[0].Inspection).ProviderConfigurationEpoch == uint64(18446744073709551615)) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_epoch")
		}
		if !((*value.Capabilities[0].Inspection).State == "provider-configuration-changed") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.0.inspection.state")
		}
		if !(value.Capabilities[1].Id == "future-capability") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.id")
		}
		if !(value.Capabilities[1].Contract == "future-contract") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.contract")
		}
		if !(value.Capabilities[1].Provider == "future-provider") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.provider")
		}
		if !(len(value.Capabilities[1].Operations) == 0) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.operations.count")
		}
		if !(len(value.Capabilities[1].Attributes) == 1) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.attributes.count")
		}
		if !(value.Capabilities[1].Attributes["descriptive"] == "not-authority") {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.attributes.0")
		}
		if !(!(value.Capabilities[1].Inspection != nil)) {
			tester.Fatal("redacted-capability-provider-inspection.capabilities.1.inspection.presence")
		}
		if !(value.Page != nil) {
			tester.Fatal("redacted-capability-provider-inspection.page.presence")
		}
		if !((*value.Page).NextPageToken != nil) {
			tester.Fatal("redacted-capability-provider-inspection.page.next_page_token.presence")
		}
		if !((*(*value.Page).NextPageToken) == "opaque-capability-cursor") {
			tester.Fatal("redacted-capability-provider-inspection.page.next_page_token")
		}
		if !(value.Revision != nil) {
			tester.Fatal("redacted-capability-provider-inspection.revision.presence")
		}
		if !((*value.Revision).DeploymentId == "deployment-a") {
			tester.Fatal("redacted-capability-provider-inspection.revision.deployment_id")
		}
		if !((*value.Revision).RevisionId == "revision-a") {
			tester.Fatal("redacted-capability-provider-inspection.revision.revision_id")
		}
		if !((*value.Revision).ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("redacted-capability-provider-inspection.revision.component_digest")
		}
		if !((*value.Revision).PublicationId != nil) {
			tester.Fatal("redacted-capability-provider-inspection.revision.publication_id.presence")
		}
		if !((*(*value.Revision).PublicationId) == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111") {
			tester.Fatal("redacted-capability-provider-inspection.revision.publication_id")
		}
		if !((*value.Revision).RouteGeneration == uint64(18446744073709551615)) {
			tester.Fatal("redacted-capability-provider-inspection.revision.route_generation")
		}
		if !((*value.Revision).CatalogTransaction == uint64(9223372036854775808)) {
			tester.Fatal("redacted-capability-provider-inspection.revision.catalog_transaction")
		}
		if !(value.TenantUsage != nil) {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.presence")
		}
		if !((*value.TenantUsage).Scope == "tenant") {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.scope")
		}
		if !(len((*value.TenantUsage).Counters) == 2) {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.counters.count")
		}
		if !((*value.TenantUsage).Counters["sessions"] == uint64(18446744073709551615)) {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.counters.0")
		}
		if !((*value.TenantUsage).Counters["calls"] == uint64(0)) {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.counters.1")
		}
		if !(len((*value.TenantUsage).Unavailable) == 1) {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.unavailable.count")
		}
		if !((*value.TenantUsage).Unavailable[0] == "fixture-owner-unavailable") {
			tester.Fatal("redacted-capability-provider-inspection.tenant_usage.unavailable.0")
		}
		if !(!(value.NodeUsage != nil)) {
			tester.Fatal("redacted-capability-provider-inspection.node_usage.presence")
		}
		if !(value.State == "sampled") {
			tester.Fatal("redacted-capability-provider-inspection.state")
		}
	}
	{
		value := ListCapabilitiesResponse{Capabilities: []CapabilityDescriptor{}, NodeUsage: fixturePointer(CapabilityResourceUsage{Scope: "node", Counters: map[string]uint64{}, Unavailable: []string{"provider-pools-no-retained-owner", "audit-owner-not-configured"}}), State: "binding-plan-unavailable"}
		if !(len(value.Capabilities) == 0) {
			tester.Fatal("missing-provider-plan-not-zero-usage.capabilities.count")
		}
		if !(!(value.Page != nil)) {
			tester.Fatal("missing-provider-plan-not-zero-usage.page.presence")
		}
		if !(!(value.Revision != nil)) {
			tester.Fatal("missing-provider-plan-not-zero-usage.revision.presence")
		}
		if !(!(value.TenantUsage != nil)) {
			tester.Fatal("missing-provider-plan-not-zero-usage.tenant_usage.presence")
		}
		if !(value.NodeUsage != nil) {
			tester.Fatal("missing-provider-plan-not-zero-usage.node_usage.presence")
		}
		if !((*value.NodeUsage).Scope == "node") {
			tester.Fatal("missing-provider-plan-not-zero-usage.node_usage.scope")
		}
		if !(len((*value.NodeUsage).Counters) == 0) {
			tester.Fatal("missing-provider-plan-not-zero-usage.node_usage.counters.count")
		}
		if !(len((*value.NodeUsage).Unavailable) == 2) {
			tester.Fatal("missing-provider-plan-not-zero-usage.node_usage.unavailable.count")
		}
		if !((*value.NodeUsage).Unavailable[0] == "provider-pools-no-retained-owner") {
			tester.Fatal("missing-provider-plan-not-zero-usage.node_usage.unavailable.0")
		}
		if !((*value.NodeUsage).Unavailable[1] == "audit-owner-not-configured") {
			tester.Fatal("missing-provider-plan-not-zero-usage.node_usage.unavailable.1")
		}
		if !(value.State == "binding-plan-unavailable") {
			tester.Fatal("missing-provider-plan-not-zero-usage.state")
		}
	}
	{
		value := CapabilityInspectionCeiling{Operations: uint32(0), InputBytes: uint64(18446744073709551615), OutputBytes: uint64(0), WallTimeMillis: uint64(18446744073709551615)}
		if !(value.Operations == uint32(0)) {
			tester.Fatal("typed-ceiling-zero-and-max-not-grant.operations")
		}
		if !(value.InputBytes == uint64(18446744073709551615)) {
			tester.Fatal("typed-ceiling-zero-and-max-not-grant.input_bytes")
		}
		if !(value.OutputBytes == uint64(0)) {
			tester.Fatal("typed-ceiling-zero-and-max-not-grant.output_bytes")
		}
		if !(value.WallTimeMillis == uint64(18446744073709551615)) {
			tester.Fatal("typed-ceiling-zero-and-max-not-grant.wall_time_millis")
		}
	}
	{
		value := CallOptions{}
		if !(!(value.TimeoutMillis != nil)) {
			tester.Fatal("local-timeout-absent.timeout_millis.presence")
		}
	}
	{
		value := CallOptions{TimeoutMillis: fixturePointer(uint64(0))}
		if !(value.TimeoutMillis != nil) {
			tester.Fatal("local-timeout-zero.timeout_millis.presence")
		}
		if !((*value.TimeoutMillis) == uint64(0)) {
			tester.Fatal("local-timeout-zero.timeout_millis")
		}
	}
	{
		value := CallOptions{TimeoutMillis: fixturePointer(uint64(18446744073709551615))}
		if !(value.TimeoutMillis != nil) {
			tester.Fatal("local-timeout-max-not-wrapped.timeout_millis.presence")
		}
		if !((*value.TimeoutMillis) == uint64(18446744073709551615)) {
			tester.Fatal("local-timeout-max-not-wrapped.timeout_millis")
		}
	}
	{
		value := ClientFailure{Category: FailureCategory(1), Message: "local-cancelled", Dispatched: false, Outcome: OutcomeKnowledge(1), Identity: RequestIdentity{ActivationId: fixturePointer("activation-a")}}
		if !(int32(value.Category) == 1) {
			tester.Fatal("local-cancel-before-dispatch.category")
		}
		if !(value.Message == "local-cancelled") {
			tester.Fatal("local-cancel-before-dispatch.message")
		}
		if !(!(value.GrpcStatus != nil)) {
			tester.Fatal("local-cancel-before-dispatch.grpc_status.presence")
		}
		if !(!(value.PlatformError != nil)) {
			tester.Fatal("local-cancel-before-dispatch.platform_error.presence")
		}
		if !(value.Dispatched == false) {
			tester.Fatal("local-cancel-before-dispatch.dispatched")
		}
		if !(int32(value.Outcome) == 1) {
			tester.Fatal("local-cancel-before-dispatch.outcome")
		}
		if !(value.Identity.ActivationId != nil) {
			tester.Fatal("local-cancel-before-dispatch.identity.activation_id.presence")
		}
		if !((*value.Identity.ActivationId) == "activation-a") {
			tester.Fatal("local-cancel-before-dispatch.identity.activation_id")
		}
		if !(!(value.Identity.OperationId != nil)) {
			tester.Fatal("local-cancel-before-dispatch.identity.operation_id.presence")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("local-cancel-before-dispatch.audit_ack.presence")
		}
		if !(!(value.AuditStatus != nil)) {
			tester.Fatal("local-cancel-before-dispatch.audit_status.presence")
		}
		if !(!(value.UnsupportedWireValue != nil)) {
			tester.Fatal("local-cancel-before-dispatch.unsupported_wire_value.presence")
		}
		if !(!(value.AuditAttemptSequence != nil)) {
			tester.Fatal("local-cancel-before-dispatch.audit_attempt_sequence.presence")
		}
	}
	{
		value := ClientFailure{Category: FailureCategory(2), Message: "deadline", GrpcStatus: fixturePointer(int32(4)), Dispatched: true, Outcome: OutcomeKnowledge(2), Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, AuditAck: fixturePointer(AuditAck{Status: AuditAckStatus(2), AttemptSequence: fixturePointer(uint64(18446744073709551615))}), AuditStatus: fixturePointer("outcome-unknown"), AuditAttemptSequence: fixturePointer(uint64(18446744073709551615))}
		if !(int32(value.Category) == 2) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.category")
		}
		if !(value.Message == "deadline") {
			tester.Fatal("deadline-after-dispatch-is-uncertain.message")
		}
		if !(value.GrpcStatus != nil) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.grpc_status.presence")
		}
		if !((*value.GrpcStatus) == int32(4)) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.grpc_status")
		}
		if !(!(value.PlatformError != nil)) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.platform_error.presence")
		}
		if !(value.Dispatched == true) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.dispatched")
		}
		if !(int32(value.Outcome) == 2) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.outcome")
		}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("deadline-after-dispatch-is-uncertain.identity.operation_id")
		}
		if !(value.AuditAck != nil) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_ack.presence")
		}
		if !(int32((*value.AuditAck).Status) == 2) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_ack.status")
		}
		if !((*value.AuditAck).AttemptSequence != nil) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence.presence")
		}
		if !((*(*value.AuditAck).AttemptSequence) == uint64(18446744073709551615)) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence")
		}
		if !(value.AuditStatus != nil) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_status.presence")
		}
		if !((*value.AuditStatus) == "outcome-unknown") {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_status")
		}
		if !(!(value.UnsupportedWireValue != nil)) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.unsupported_wire_value.presence")
		}
		if !(value.AuditAttemptSequence != nil) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_attempt_sequence.presence")
		}
		if !((*value.AuditAttemptSequence) == uint64(18446744073709551615)) {
			tester.Fatal("deadline-after-dispatch-is-uncertain.audit_attempt_sequence")
		}
	}
	{
		value := ClientFailure{Category: FailureCategory(4), Message: "capability-policy-conflict", GrpcStatus: fixturePointer(int32(9)), PlatformError: fixturePointer(PlatformError{Code: "state-conflict", Message: "capability-policy-conflict", Retryable: false, DetailItems: []ErrorDetail{ErrorDetail{Kind: "future-detail", Fields: map[string]string{"value": "retained"}}}}), Dispatched: true, Outcome: OutcomeKnowledge(3), Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}}
		if !(int32(value.Category) == 4) {
			tester.Fatal("rpc-conflict-retains-request-identity.category")
		}
		if !(value.Message == "capability-policy-conflict") {
			tester.Fatal("rpc-conflict-retains-request-identity.message")
		}
		if !(value.GrpcStatus != nil) {
			tester.Fatal("rpc-conflict-retains-request-identity.grpc_status.presence")
		}
		if !((*value.GrpcStatus) == int32(9)) {
			tester.Fatal("rpc-conflict-retains-request-identity.grpc_status")
		}
		if !(value.PlatformError != nil) {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.presence")
		}
		if !((*value.PlatformError).Code == "state-conflict") {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.code")
		}
		if !((*value.PlatformError).Message == "capability-policy-conflict") {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.message")
		}
		if !((*value.PlatformError).Retryable == false) {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.retryable")
		}
		if !(len((*value.PlatformError).DetailItems) == 1) {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.detail_items.count")
		}
		if !((*value.PlatformError).DetailItems[0].Kind == "future-detail") {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind")
		}
		if !(len((*value.PlatformError).DetailItems[0].Fields) == 1) {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.count")
		}
		if !((*value.PlatformError).DetailItems[0].Fields["value"] == "retained") {
			tester.Fatal("rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0")
		}
		if !(value.Dispatched == true) {
			tester.Fatal("rpc-conflict-retains-request-identity.dispatched")
		}
		if !(int32(value.Outcome) == 3) {
			tester.Fatal("rpc-conflict-retains-request-identity.outcome")
		}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("rpc-conflict-retains-request-identity.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("rpc-conflict-retains-request-identity.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("rpc-conflict-retains-request-identity.identity.operation_id")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("rpc-conflict-retains-request-identity.audit_ack.presence")
		}
		if !(!(value.AuditStatus != nil)) {
			tester.Fatal("rpc-conflict-retains-request-identity.audit_status.presence")
		}
		if !(!(value.UnsupportedWireValue != nil)) {
			tester.Fatal("rpc-conflict-retains-request-identity.unsupported_wire_value.presence")
		}
		if !(!(value.AuditAttemptSequence != nil)) {
			tester.Fatal("rpc-conflict-retains-request-identity.audit_attempt_sequence.presence")
		}
	}
	{
		value := ClientFailure{Category: FailureCategory(5), Message: "invalid-response", Dispatched: true, Outcome: OutcomeKnowledge(2), Identity: RequestIdentity{ActivationId: fixturePointer("activation-a"), OperationId: fixturePointer("operation-a")}, UnsupportedWireValue: fixturePointer(UnsupportedWireValue{Field: "phase", Value: "future-phase-not-authority"})}
		if !(int32(value.Category) == 5) {
			tester.Fatal("decode-failure-retains-known-identity.category")
		}
		if !(value.Message == "invalid-response") {
			tester.Fatal("decode-failure-retains-known-identity.message")
		}
		if !(!(value.GrpcStatus != nil)) {
			tester.Fatal("decode-failure-retains-known-identity.grpc_status.presence")
		}
		if !(!(value.PlatformError != nil)) {
			tester.Fatal("decode-failure-retains-known-identity.platform_error.presence")
		}
		if !(value.Dispatched == true) {
			tester.Fatal("decode-failure-retains-known-identity.dispatched")
		}
		if !(int32(value.Outcome) == 2) {
			tester.Fatal("decode-failure-retains-known-identity.outcome")
		}
		if !(value.Identity.ActivationId != nil) {
			tester.Fatal("decode-failure-retains-known-identity.identity.activation_id.presence")
		}
		if !((*value.Identity.ActivationId) == "activation-a") {
			tester.Fatal("decode-failure-retains-known-identity.identity.activation_id")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("decode-failure-retains-known-identity.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("decode-failure-retains-known-identity.identity.operation_id")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("decode-failure-retains-known-identity.audit_ack.presence")
		}
		if !(!(value.AuditStatus != nil)) {
			tester.Fatal("decode-failure-retains-known-identity.audit_status.presence")
		}
		if !(value.UnsupportedWireValue != nil) {
			tester.Fatal("decode-failure-retains-known-identity.unsupported_wire_value.presence")
		}
		if !((*value.UnsupportedWireValue).Field == "phase") {
			tester.Fatal("decode-failure-retains-known-identity.unsupported_wire_value.field")
		}
		if !((*value.UnsupportedWireValue).Value == "future-phase-not-authority") {
			tester.Fatal("decode-failure-retains-known-identity.unsupported_wire_value.value")
		}
		if !(!(value.AuditAttemptSequence != nil)) {
			tester.Fatal("decode-failure-retains-known-identity.audit_attempt_sequence.presence")
		}
	}
	{
		value := ResponseMetadata{Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, Outcome: OutcomeKnowledge(3), AuditAck: fixturePointer(AuditAck{Status: AuditAckStatus(2), AttemptSequence: fixturePointer(uint64(18446744073709551615))}), AuditStatus: fixturePointer("outcome-unknown"), AuditAttemptSequence: fixturePointer(uint64(18446744073709551615))}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("observed-receipt-audit-outcome-independent.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("observed-receipt-audit-outcome-independent.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("observed-receipt-audit-outcome-independent.identity.operation_id")
		}
		if !(int32(value.Outcome) == 3) {
			tester.Fatal("observed-receipt-audit-outcome-independent.outcome")
		}
		if !(value.AuditAck != nil) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_ack.presence")
		}
		if !(int32((*value.AuditAck).Status) == 2) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_ack.status")
		}
		if !((*value.AuditAck).AttemptSequence != nil) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence.presence")
		}
		if !((*(*value.AuditAck).AttemptSequence) == uint64(18446744073709551615)) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence")
		}
		if !(value.AuditStatus != nil) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_status.presence")
		}
		if !((*value.AuditStatus) == "outcome-unknown") {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_status")
		}
		if !(value.AuditAttemptSequence != nil) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_attempt_sequence.presence")
		}
		if !((*value.AuditAttemptSequence) == uint64(18446744073709551615)) {
			tester.Fatal("observed-receipt-audit-outcome-independent.audit_attempt_sequence")
		}
	}
	{
		value := ResponseMetadata{Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, Outcome: OutcomeKnowledge(3)}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("policy-response-has-no-fabricated-audit.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("policy-response-has-no-fabricated-audit.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("policy-response-has-no-fabricated-audit.identity.operation_id")
		}
		if !(int32(value.Outcome) == 3) {
			tester.Fatal("policy-response-has-no-fabricated-audit.outcome")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("policy-response-has-no-fabricated-audit.audit_ack.presence")
		}
		if !(!(value.AuditStatus != nil)) {
			tester.Fatal("policy-response-has-no-fabricated-audit.audit_status.presence")
		}
		if !(!(value.AuditAttemptSequence != nil)) {
			tester.Fatal("policy-response-has-no-fabricated-audit.audit_attempt_sequence.presence")
		}
	}
	{
		value := ResponseMetadata{Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, Outcome: OutcomeKnowledge(2)}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.identity.operation_id")
		}
		if !(int32(value.Outcome) == 2) {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.outcome")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.audit_ack.presence")
		}
		if !(!(value.AuditStatus != nil)) {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.audit_status.presence")
		}
		if !(!(value.AuditAttemptSequence != nil)) {
			tester.Fatal("missing-recovery-keeps-outcome-unknown.audit_attempt_sequence.presence")
		}
	}
	{
		value := ResponseMetadata{Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, Outcome: OutcomeKnowledge(91), AuditAck: fixturePointer(AuditAck{Status: AuditAckStatus(91), AttemptSequence: fixturePointer(uint64(0))}), AuditStatus: fixturePointer("future-audit-status"), AuditAttemptSequence: fixturePointer(uint64(0))}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("unknown-audit-enum-and-status.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("unknown-audit-enum-and-status.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("unknown-audit-enum-and-status.identity.operation_id")
		}
		if !(int32(value.Outcome) == 91) {
			tester.Fatal("unknown-audit-enum-and-status.outcome")
		}
		if !(value.AuditAck != nil) {
			tester.Fatal("unknown-audit-enum-and-status.audit_ack.presence")
		}
		if !(int32((*value.AuditAck).Status) == 91) {
			tester.Fatal("unknown-audit-enum-and-status.audit_ack.status")
		}
		if !((*value.AuditAck).AttemptSequence != nil) {
			tester.Fatal("unknown-audit-enum-and-status.audit_ack.attempt_sequence.presence")
		}
		if !((*(*value.AuditAck).AttemptSequence) == uint64(0)) {
			tester.Fatal("unknown-audit-enum-and-status.audit_ack.attempt_sequence")
		}
		if !(value.AuditStatus != nil) {
			tester.Fatal("unknown-audit-enum-and-status.audit_status.presence")
		}
		if !((*value.AuditStatus) == "future-audit-status") {
			tester.Fatal("unknown-audit-enum-and-status.audit_status")
		}
		if !(value.AuditAttemptSequence != nil) {
			tester.Fatal("unknown-audit-enum-and-status.audit_attempt_sequence.presence")
		}
		if !((*value.AuditAttemptSequence) == uint64(0)) {
			tester.Fatal("unknown-audit-enum-and-status.audit_attempt_sequence")
		}
	}
	{
		value := ResponseMetadata{Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, Outcome: OutcomeKnowledge(3), AuditStatus: fixturePointer("future-state"), AuditAttemptSequence: fixturePointer(uint64(18446744073709551615))}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("unknown-audit-header-and-max-attempt.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("unknown-audit-header-and-max-attempt.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("unknown-audit-header-and-max-attempt.identity.operation_id")
		}
		if !(int32(value.Outcome) == 3) {
			tester.Fatal("unknown-audit-header-and-max-attempt.outcome")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("unknown-audit-header-and-max-attempt.audit_ack.presence")
		}
		if !(value.AuditStatus != nil) {
			tester.Fatal("unknown-audit-header-and-max-attempt.audit_status.presence")
		}
		if !((*value.AuditStatus) == "future-state") {
			tester.Fatal("unknown-audit-header-and-max-attempt.audit_status")
		}
		if !(value.AuditAttemptSequence != nil) {
			tester.Fatal("unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence")
		}
		if !((*value.AuditAttemptSequence) == uint64(18446744073709551615)) {
			tester.Fatal("unknown-audit-header-and-max-attempt.audit_attempt_sequence")
		}
	}
	{
		value := ClientFailure{Category: FailureCategory(4), Message: "rpc-failure", GrpcStatus: fixturePointer(int32(13)), Dispatched: true, Outcome: OutcomeKnowledge(2), Identity: RequestIdentity{OperationId: fixturePointer("operation-a")}, AuditStatus: fixturePointer("future-state"), AuditAttemptSequence: fixturePointer(uint64(18446744073709551615))}
		if !(int32(value.Category) == 4) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.category")
		}
		if !(value.Message == "rpc-failure") {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.message")
		}
		if !(value.GrpcStatus != nil) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.grpc_status.presence")
		}
		if !((*value.GrpcStatus) == int32(13)) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.grpc_status")
		}
		if !(!(value.PlatformError != nil)) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.platform_error.presence")
		}
		if !(value.Dispatched == true) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.dispatched")
		}
		if !(int32(value.Outcome) == 2) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.outcome")
		}
		if !(!(value.Identity.ActivationId != nil)) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.identity.activation_id.presence")
		}
		if !(value.Identity.OperationId != nil) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.presence")
		}
		if !((*value.Identity.OperationId) == "operation-a") {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id")
		}
		if !(!(value.AuditAck != nil)) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.audit_ack.presence")
		}
		if !(value.AuditStatus != nil) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.audit_status.presence")
		}
		if !((*value.AuditStatus) == "future-state") {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.audit_status")
		}
		if !(!(value.UnsupportedWireValue != nil)) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.unsupported_wire_value.presence")
		}
		if !(value.AuditAttemptSequence != nil) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence")
		}
		if !((*value.AuditAttemptSequence) == uint64(18446744073709551615)) {
			tester.Fatal("failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence")
		}
	}
	{
		value := AuditAck{Status: AuditAckStatus(1)}
		if !(int32(value.Status) == 1) {
			tester.Fatal("audit-durable-attempt-absent.status")
		}
		if !(!(value.AttemptSequence != nil)) {
			tester.Fatal("audit-durable-attempt-absent.attempt_sequence.presence")
		}
	}
	{
		value := AuditAck{Status: AuditAckStatus(3), AttemptSequence: fixturePointer(uint64(0))}
		if !(int32(value.Status) == 3) {
			tester.Fatal("audit-unavailable-attempt-zero.status")
		}
		if !(value.AttemptSequence != nil) {
			tester.Fatal("audit-unavailable-attempt-zero.attempt_sequence.presence")
		}
		if !((*value.AttemptSequence) == uint64(0)) {
			tester.Fatal("audit-unavailable-attempt-zero.attempt_sequence")
		}
	}
	{
		value := AuditAck{Status: AuditAckStatus(4)}
		if !(int32(value.Status) == 4) {
			tester.Fatal("audit-disabled-distinct-from-absence.status")
		}
		if !(!(value.AttemptSequence != nil)) {
			tester.Fatal("audit-disabled-distinct-from-absence.attempt_sequence.presence")
		}
	}
	{
		value := PublicationRef{Id: "", Tenant: "tenant-a"}
		if !(value.Id == "") {
			tester.Fatal("publication-reference-invalid-id.id")
		}
		if !(value.Tenant == "tenant-a") {
			tester.Fatal("publication-reference-invalid-id.tenant")
		}
	}
	{
		value := PublicationRef{Id: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", Tenant: "tenant-b"}
		if !(value.Id == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111") {
			tester.Fatal("publication-reference-tenant-scope.id")
		}
		if !(value.Tenant == "tenant-b") {
			tester.Fatal("publication-reference-tenant-scope.tenant")
		}
	}
	{
		value := PublicationIdentity{Publication: PublicationRef{Id: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", Tenant: "tenant-a"}, ComponentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", PackageDigest: "sha256:1111111111111111111111111111111111111111111111111111111111111111"}
		if !(value.Publication.Id == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111") {
			tester.Fatal("publication-original-package.publication.id")
		}
		if !(value.Publication.Tenant == "tenant-a") {
			tester.Fatal("publication-original-package.publication.tenant")
		}
		if !(value.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("publication-original-package.component_digest")
		}
		if !(value.PackageDigest == "sha256:1111111111111111111111111111111111111111111111111111111111111111") {
			tester.Fatal("publication-original-package.package_digest")
		}
	}
	{
		value := PublicationIdentity{Publication: PublicationRef{Id: "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", Tenant: "tenant-a"}, ComponentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", PackageDigest: "sha256:2222222222222222222222222222222222222222222222222222222222222222"}
		if !(value.Publication.Id == "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222") {
			tester.Fatal("publication-corrected-package-same-component.publication.id")
		}
		if !(value.Publication.Tenant == "tenant-a") {
			tester.Fatal("publication-corrected-package-same-component.publication.tenant")
		}
		if !(value.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("publication-corrected-package-same-component.component_digest")
		}
		if !(value.PackageDigest == "sha256:2222222222222222222222222222222222222222222222222222222222222222") {
			tester.Fatal("publication-corrected-package-same-component.package_digest")
		}
	}
	{
		value := PublicationIdentity{Publication: PublicationRef{Id: "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", Tenant: "tenant-b"}, ComponentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", PackageDigest: "sha256:2222222222222222222222222222222222222222222222222222222222222222"}
		if !(value.Publication.Id == "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333") {
			tester.Fatal("publication-other-tenant-same-package.publication.id")
		}
		if !(value.Publication.Tenant == "tenant-b") {
			tester.Fatal("publication-other-tenant-same-package.publication.tenant")
		}
		if !(value.ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("publication-other-tenant-same-package.component_digest")
		}
		if !(value.PackageDigest == "sha256:2222222222222222222222222222222222222222222222222222222222222222") {
			tester.Fatal("publication-other-tenant-same-package.package_digest")
		}
	}
	{
		value := InspectHttpTargetRequest{Service: "service-a", Contract: "latent:web/application@0.1.0", Function: "handle", Route: fixturePointer("web"), RevisionId: fixturePointer("revision-a"), Publication: fixturePointer(PublicationRef{Id: "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Tenant: "tenant-a"}), RoutingKey: fixturePointer("reviewed-key"), IncludePreparation: true, MaximumWaitMillis: uint64(30000)}
		if !(value.Service == "service-a") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.service")
		}
		if !(value.Contract == "latent:web/application@0.1.0") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.contract")
		}
		if !(value.Function == "handle") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.function")
		}
		if !(value.Route != nil) {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.route.presence")
		}
		if !((*value.Route) == "web") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.route")
		}
		if !(value.RevisionId != nil) {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.revision_id.presence")
		}
		if !((*value.RevisionId) == "revision-a") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.revision_id")
		}
		if !(value.Publication != nil) {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.publication.presence")
		}
		if !((*value.Publication).Id == "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.publication.id")
		}
		if !((*value.Publication).Tenant == "tenant-a") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.publication.tenant")
		}
		if !(value.RoutingKey != nil) {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.routing_key.presence")
		}
		if !((*value.RoutingKey) == "reviewed-key") {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.routing_key")
		}
		if !(value.IncludePreparation == true) {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.include_preparation")
		}
		if !(value.MaximumWaitMillis == uint64(30000)) {
			tester.Fatal("target-inspection-exact-bounded-publication-selector.maximum_wait_millis")
		}
	}
	{
		value := InspectHttpTargetResponse{SchemaVersion: uint32(1), Tenant: "tenant-a", Service: "service-a", Contract: "latent:web/application@0.1.0", Function: "handle", Route: "web", State: TargetObservationState(1), CatalogTransaction: uint64(18446744073709551615), RouteGeneration: uint64(18446744073709551615), BindingGeneration: uint64(18446744073709551615), PolicyStoreGeneration: fixturePointer(uint64(0)), Candidates: []TargetCandidate{TargetCandidate{DeploymentId: "deployment-a", DeploymentGeneration: uint64(18446744073709551615), RevisionId: "revision-a", ComponentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Publication: fixturePointer(PublicationRef{Id: "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Tenant: "tenant-a"}), RequestedPublication: fixturePointer(PublicationRef{Id: "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", Tenant: "tenant-a"}), PackageDigest: fixturePointer("sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), PublicationGeneration: fixturePointer(uint64(18446744073709551615)), RoutingWeight: uint32(100), ExportCompatible: true, HttpCompatible: true, Eligible: true, Reasons: []TargetReason{TargetReason(1)}, Dependencies: []TargetDependency{TargetDependency{Capability: "latent:runtime/clocks@0.1.0", State: "configured-current", PolicyIdentityDigest: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", ProviderConfigurationEpoch: uint64(18446744073709551615), Binding: fixturePointer(TargetDependencyRevision{Id: "binding-a", Digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Revision: uint64(18446744073709551615)}), Policies: []TargetDependencyRevision{TargetDependencyRevision{Id: "policy-a", Digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", Revision: uint64(0)}}, ProviderProfile: "host-runtime-v1", ConfigurationDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}, Preparation: fixturePointer(TargetPreparation{State: TargetPreparationState(1), Profile: fixturePointer(DiagnosticProfile(2)), EngineVersion: fixturePointer("wasmtime-42"), EngineConfigurationDigest: fixturePointer("blake3:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"), TargetTriple: fixturePointer("x86_64-unknown-linux-gnu"), CpuFeatureSet: fixturePointer("baseline"), SealedMetadataFingerprint: fixturePointer("dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"), ImportCount: fixturePointer(uint64(2)), FunctionCount: fixturePointer(uint64(1)), HostcallFuel: fixturePointer(uint64(18446744073709551615)), MaximumLiftedBytes: fixturePointer(uint64(67108864)), MaximumTypeNodes: fixturePointer(uint64(65536)), DeclaredBudget: fixturePointer(ResourceBudget{CpuFuel: uint64(18446744073709551615), MemoryBytes: uint64(18446744073709551615), ChildCalls: uint32(4294967295), OutboundRequests: uint32(0), StateReadBytes: uint64(18446744073709551615), StateWriteBytes: uint64(0), BlobReadBytes: uint64(0), BlobWriteBytes: uint64(0), LogBytes: uint64(0), EffectCount: uint32(0), WallTimeLimitMillis: fixturePointer(uint64(0))}), Imports: []string{"latent:runtime/clocks@0.1.0"}, Exports: []PreparedTargetExport{PreparedTargetExport{Contract: "latent:web/application@0.1.0", Function: "handle"}}, TypeImports: []string{"examples:java-http-domain/types@1.0.0"}}), PublicationKind: fixturePointer("capsule"), HttpBindings: []InspectedHttpBinding{InspectedHttpBinding{Id: "trigger-a", Generation: uint64(18446744073709551615), SelectedDeploymentGeneration: uint64(18446744073709551615), State: "configured-current"}}}}, SelectedRevisionId: fixturePointer("revision-a"), LiveGrantsChecked: false}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.schema_version")
		}
		if !(value.Tenant == "tenant-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.tenant")
		}
		if !(value.Service == "service-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.service")
		}
		if !(value.Contract == "latent:web/application@0.1.0") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.contract")
		}
		if !(value.Function == "handle") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.function")
		}
		if !(value.Route == "web") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.route")
		}
		if !(int32(value.State) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.state")
		}
		if !(value.CatalogTransaction == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.catalog_transaction")
		}
		if !(value.RouteGeneration == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.route_generation")
		}
		if !(value.BindingGeneration == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.binding_generation")
		}
		if !(value.PolicyStoreGeneration != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.policy_store_generation.presence")
		}
		if !((*value.PolicyStoreGeneration) == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.policy_store_generation")
		}
		if !(len(value.Candidates) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.count")
		}
		if !(value.Candidates[0].DeploymentId == "deployment-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.deployment_id")
		}
		if !(value.Candidates[0].DeploymentGeneration == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.deployment_generation")
		}
		if !(value.Candidates[0].RevisionId == "revision-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.revision_id")
		}
		if !(value.Candidates[0].ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.component_digest")
		}
		if !(value.Candidates[0].Publication != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication.presence")
		}
		if !((*value.Candidates[0].Publication).Id == "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication.id")
		}
		if !((*value.Candidates[0].Publication).Tenant == "tenant-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication.tenant")
		}
		if !(value.Candidates[0].RequestedPublication != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.requested_publication.presence")
		}
		if !((*value.Candidates[0].RequestedPublication).Id == "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.requested_publication.id")
		}
		if !((*value.Candidates[0].RequestedPublication).Tenant == "tenant-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.requested_publication.tenant")
		}
		if !(value.Candidates[0].PackageDigest != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.package_digest.presence")
		}
		if !((*value.Candidates[0].PackageDigest) == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.package_digest")
		}
		if !(value.Candidates[0].PublicationGeneration != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_generation.presence")
		}
		if !((*value.Candidates[0].PublicationGeneration) == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_generation")
		}
		if !(value.Candidates[0].RoutingWeight == uint32(100)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.routing_weight")
		}
		if !(value.Candidates[0].ExportCompatible == true) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.export_compatible")
		}
		if !(value.Candidates[0].HttpCompatible == true) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_compatible")
		}
		if !(value.Candidates[0].Eligible == true) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.eligible")
		}
		if !(len(value.Candidates[0].Reasons) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.reasons.count")
		}
		if !(int32(value.Candidates[0].Reasons[0]) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.reasons.0")
		}
		if !(len(value.Candidates[0].Dependencies) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.count")
		}
		if !(value.Candidates[0].Dependencies[0].Capability == "latent:runtime/clocks@0.1.0") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.capability")
		}
		if !(value.Candidates[0].Dependencies[0].State == "configured-current") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.state")
		}
		if !(value.Candidates[0].Dependencies[0].PolicyIdentityDigest == "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policy_identity_digest")
		}
		if !(value.Candidates[0].Dependencies[0].ProviderConfigurationEpoch == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.provider_configuration_epoch")
		}
		if !(value.Candidates[0].Dependencies[0].Binding != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.presence")
		}
		if !((*value.Candidates[0].Dependencies[0].Binding).Id == "binding-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.id")
		}
		if !((*value.Candidates[0].Dependencies[0].Binding).Digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.digest")
		}
		if !((*value.Candidates[0].Dependencies[0].Binding).Revision == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.revision")
		}
		if !(len(value.Candidates[0].Dependencies[0].Policies) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.count")
		}
		if !(value.Candidates[0].Dependencies[0].Policies[0].Id == "policy-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.0.id")
		}
		if !(value.Candidates[0].Dependencies[0].Policies[0].Digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.0.digest")
		}
		if !(value.Candidates[0].Dependencies[0].Policies[0].Revision == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.0.revision")
		}
		if !(value.Candidates[0].Dependencies[0].ProviderProfile == "host-runtime-v1") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.provider_profile")
		}
		if !(value.Candidates[0].Dependencies[0].ConfigurationDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.configuration_digest")
		}
		if !(value.Candidates[0].Preparation != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.presence")
		}
		if !(int32((*value.Candidates[0].Preparation).State) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.state")
		}
		if !(!((*value.Candidates[0].Preparation).Diagnostic != nil)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.diagnostic.presence")
		}
		if !((*value.Candidates[0].Preparation).Profile != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.profile.presence")
		}
		if !(int32((*(*value.Candidates[0].Preparation).Profile)) == 2) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.profile")
		}
		if !((*value.Candidates[0].Preparation).EngineVersion != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_version.presence")
		}
		if !((*(*value.Candidates[0].Preparation).EngineVersion) == "wasmtime-42") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_version")
		}
		if !((*value.Candidates[0].Preparation).EngineConfigurationDigest != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_configuration_digest.presence")
		}
		if !((*(*value.Candidates[0].Preparation).EngineConfigurationDigest) == "blake3:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_configuration_digest")
		}
		if !((*value.Candidates[0].Preparation).TargetTriple != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.target_triple.presence")
		}
		if !((*(*value.Candidates[0].Preparation).TargetTriple) == "x86_64-unknown-linux-gnu") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.target_triple")
		}
		if !((*value.Candidates[0].Preparation).CpuFeatureSet != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.cpu_feature_set.presence")
		}
		if !((*(*value.Candidates[0].Preparation).CpuFeatureSet) == "baseline") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.cpu_feature_set")
		}
		if !((*value.Candidates[0].Preparation).SealedMetadataFingerprint != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.sealed_metadata_fingerprint.presence")
		}
		if !((*(*value.Candidates[0].Preparation).SealedMetadataFingerprint) == "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.sealed_metadata_fingerprint")
		}
		if !((*value.Candidates[0].Preparation).ImportCount != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.import_count.presence")
		}
		if !((*(*value.Candidates[0].Preparation).ImportCount) == uint64(2)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.import_count")
		}
		if !((*value.Candidates[0].Preparation).FunctionCount != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.function_count.presence")
		}
		if !((*(*value.Candidates[0].Preparation).FunctionCount) == uint64(1)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.function_count")
		}
		if !((*value.Candidates[0].Preparation).HostcallFuel != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.hostcall_fuel.presence")
		}
		if !((*(*value.Candidates[0].Preparation).HostcallFuel) == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.hostcall_fuel")
		}
		if !((*value.Candidates[0].Preparation).MaximumLiftedBytes != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_lifted_bytes.presence")
		}
		if !((*(*value.Candidates[0].Preparation).MaximumLiftedBytes) == uint64(67108864)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_lifted_bytes")
		}
		if !((*value.Candidates[0].Preparation).MaximumTypeNodes != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_type_nodes.presence")
		}
		if !((*(*value.Candidates[0].Preparation).MaximumTypeNodes) == uint64(65536)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_type_nodes")
		}
		if !((*value.Candidates[0].Preparation).DeclaredBudget != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.presence")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).CpuFuel == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.cpu_fuel")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).MemoryBytes == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.memory_bytes")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).ChildCalls == uint32(4294967295)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.child_calls")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).OutboundRequests == uint32(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.outbound_requests")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).StateReadBytes == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.state_read_bytes")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).StateWriteBytes == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.state_write_bytes")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).BlobReadBytes == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.blob_read_bytes")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).BlobWriteBytes == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.blob_write_bytes")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).LogBytes == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.log_bytes")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).EffectCount == uint32(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.effect_count")
		}
		if !((*(*value.Candidates[0].Preparation).DeclaredBudget).WallTimeLimitMillis != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.wall_time_limit_millis.presence")
		}
		if !((*(*(*value.Candidates[0].Preparation).DeclaredBudget).WallTimeLimitMillis) == uint64(0)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.wall_time_limit_millis")
		}
		if !(len((*value.Candidates[0].Preparation).Imports) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.imports.count")
		}
		if !((*value.Candidates[0].Preparation).Imports[0] == "latent:runtime/clocks@0.1.0") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.imports.0")
		}
		if !(len((*value.Candidates[0].Preparation).Exports) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.exports.count")
		}
		if !((*value.Candidates[0].Preparation).Exports[0].Contract == "latent:web/application@0.1.0") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.exports.0.contract")
		}
		if !((*value.Candidates[0].Preparation).Exports[0].Function == "handle") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.exports.0.function")
		}
		if !(len((*value.Candidates[0].Preparation).TypeImports) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.type_imports.count")
		}
		if !((*value.Candidates[0].Preparation).TypeImports[0] == "examples:java-http-domain/types@1.0.0") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.type_imports.0")
		}
		if !(value.Candidates[0].PublicationKind != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_kind.presence")
		}
		if !((*value.Candidates[0].PublicationKind) == "capsule") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_kind")
		}
		if !(len(value.Candidates[0].HttpBindings) == 1) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.count")
		}
		if !(value.Candidates[0].HttpBindings[0].Id == "trigger-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.id")
		}
		if !(value.Candidates[0].HttpBindings[0].Generation == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.generation")
		}
		if !(value.Candidates[0].HttpBindings[0].SelectedDeploymentGeneration == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.selected_deployment_generation")
		}
		if !(value.Candidates[0].HttpBindings[0].State == "configured-current") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.state")
		}
		if !(value.SelectedRevisionId != nil) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.selected_revision_id.presence")
		}
		if !((*value.SelectedRevisionId) == "revision-a") {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.selected_revision_id")
		}
		if !(value.LiveGrantsChecked == false) {
			tester.Fatal("target-inspection-ready-keeps-full-width-owner-identities.live_grants_checked")
		}
	}
	{
		value := InspectHttpTargetResponse{SchemaVersion: uint32(1), Tenant: "tenant-a", Service: "service-a", Contract: "domain:application/api@1.0.0", Function: "get", Route: "domain", State: TargetObservationState(777), CatalogTransaction: uint64(0), RouteGeneration: uint64(0), BindingGeneration: uint64(0), Candidates: []TargetCandidate{TargetCandidate{DeploymentId: "deployment-a", DeploymentGeneration: uint64(0), RevisionId: "revision-a", ComponentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", RoutingWeight: uint32(0), ExportCompatible: false, HttpCompatible: false, Eligible: false, Reasons: []TargetReason{TargetReason(-2147483648), TargetReason(778)}, Dependencies: []TargetDependency{}, Preparation: fixturePointer(TargetPreparation{State: TargetPreparationState(779), Diagnostic: fixturePointer(ActivationDiagnostic{SchemaVersion: uint32(1), Stage: DiagnosticStage(780), Reason: DiagnosticReason(781), ConfiguredBound: fixturePointer(uint64(0)), CalculatedRequirement: fixturePointer(uint64(18446744073709551615))}), Imports: []string{}, Exports: []PreparedTargetExport{}, TypeImports: []string{}}), HttpBindings: []InspectedHttpBinding{}}}, LiveGrantsChecked: false}
		if !(value.SchemaVersion == uint32(1)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.schema_version")
		}
		if !(value.Tenant == "tenant-a") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.tenant")
		}
		if !(value.Service == "service-a") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.service")
		}
		if !(value.Contract == "domain:application/api@1.0.0") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.contract")
		}
		if !(value.Function == "get") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.function")
		}
		if !(value.Route == "domain") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.route")
		}
		if !(int32(value.State) == 777) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.state")
		}
		if !(value.CatalogTransaction == uint64(0)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.catalog_transaction")
		}
		if !(value.RouteGeneration == uint64(0)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.route_generation")
		}
		if !(value.BindingGeneration == uint64(0)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.binding_generation")
		}
		if !(!(value.PolicyStoreGeneration != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.policy_store_generation.presence")
		}
		if !(len(value.Candidates) == 1) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.count")
		}
		if !(value.Candidates[0].DeploymentId == "deployment-a") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.deployment_id")
		}
		if !(value.Candidates[0].DeploymentGeneration == uint64(0)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.deployment_generation")
		}
		if !(value.Candidates[0].RevisionId == "revision-a") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.revision_id")
		}
		if !(value.Candidates[0].ComponentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.component_digest")
		}
		if !(!(value.Candidates[0].Publication != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.publication.presence")
		}
		if !(!(value.Candidates[0].RequestedPublication != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.requested_publication.presence")
		}
		if !(!(value.Candidates[0].PackageDigest != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.package_digest.presence")
		}
		if !(!(value.Candidates[0].PublicationGeneration != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.publication_generation.presence")
		}
		if !(value.Candidates[0].RoutingWeight == uint32(0)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.routing_weight")
		}
		if !(value.Candidates[0].ExportCompatible == false) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.export_compatible")
		}
		if !(value.Candidates[0].HttpCompatible == false) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.http_compatible")
		}
		if !(value.Candidates[0].Eligible == false) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.eligible")
		}
		if !(len(value.Candidates[0].Reasons) == 2) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.reasons.count")
		}
		if !(int32(value.Candidates[0].Reasons[0]) == -2147483648) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.reasons.0")
		}
		if !(int32(value.Candidates[0].Reasons[1]) == 778) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.reasons.1")
		}
		if !(len(value.Candidates[0].Dependencies) == 0) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.dependencies.count")
		}
		if !(value.Candidates[0].Preparation != nil) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.presence")
		}
		if !(int32((*value.Candidates[0].Preparation).State) == 779) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.state")
		}
		if !((*value.Candidates[0].Preparation).Diagnostic != nil) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.presence")
		}
		if !((*(*value.Candidates[0].Preparation).Diagnostic).SchemaVersion == uint32(1)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.schema_version")
		}
		if !(int32((*(*value.Candidates[0].Preparation).Diagnostic).Stage) == 780) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.stage")
		}
		if !(int32((*(*value.Candidates[0].Preparation).Diagnostic).Reason) == 781) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.reason")
		}
		if !(!((*(*value.Candidates[0].Preparation).Diagnostic).Profile != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.profile.presence")
		}
		if !(!((*(*value.Candidates[0].Preparation).Diagnostic).ProfileDigest != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.profile_digest.presence")
		}
		if !((*(*value.Candidates[0].Preparation).Diagnostic).ConfiguredBound != nil) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.configured_bound.presence")
		}
		if !((*(*(*value.Candidates[0].Preparation).Diagnostic).ConfiguredBound) == uint64(0)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.configured_bound")
		}
		if !((*(*value.Candidates[0].Preparation).Diagnostic).CalculatedRequirement != nil) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.calculated_requirement.presence")
		}
		if !((*(*(*value.Candidates[0].Preparation).Diagnostic).CalculatedRequirement) == uint64(18446744073709551615)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.calculated_requirement")
		}
		if !(!((*(*value.Candidates[0].Preparation).Diagnostic).FixedBytes != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.fixed_bytes.presence")
		}
		if !(!((*(*value.Candidates[0].Preparation).Diagnostic).LiftingFuel != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.lifting_fuel.presence")
		}
		if !(!((*(*value.Candidates[0].Preparation).Diagnostic).LiftMultiplier != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.lift_multiplier.presence")
		}
		if !(!((*value.Candidates[0].Preparation).Profile != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.profile.presence")
		}
		if !(!((*value.Candidates[0].Preparation).EngineVersion != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.engine_version.presence")
		}
		if !(!((*value.Candidates[0].Preparation).EngineConfigurationDigest != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.engine_configuration_digest.presence")
		}
		if !(!((*value.Candidates[0].Preparation).TargetTriple != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.target_triple.presence")
		}
		if !(!((*value.Candidates[0].Preparation).CpuFeatureSet != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.cpu_feature_set.presence")
		}
		if !(!((*value.Candidates[0].Preparation).SealedMetadataFingerprint != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.sealed_metadata_fingerprint.presence")
		}
		if !(!((*value.Candidates[0].Preparation).ImportCount != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.import_count.presence")
		}
		if !(!((*value.Candidates[0].Preparation).FunctionCount != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.function_count.presence")
		}
		if !(!((*value.Candidates[0].Preparation).HostcallFuel != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.hostcall_fuel.presence")
		}
		if !(!((*value.Candidates[0].Preparation).MaximumLiftedBytes != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.maximum_lifted_bytes.presence")
		}
		if !(!((*value.Candidates[0].Preparation).MaximumTypeNodes != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.maximum_type_nodes.presence")
		}
		if !(!((*value.Candidates[0].Preparation).DeclaredBudget != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.declared_budget.presence")
		}
		if !(len((*value.Candidates[0].Preparation).Imports) == 0) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.imports.count")
		}
		if !(len((*value.Candidates[0].Preparation).Exports) == 0) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.exports.count")
		}
		if !(len((*value.Candidates[0].Preparation).TypeImports) == 0) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.preparation.type_imports.count")
		}
		if !(!(value.Candidates[0].PublicationKind != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.publication_kind.presence")
		}
		if !(len(value.Candidates[0].HttpBindings) == 0) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.candidates.0.http_bindings.count")
		}
		if !(!(value.SelectedRevisionId != nil)) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.selected_revision_id.presence")
		}
		if !(value.LiveGrantsChecked == false) {
			tester.Fatal("target-inspection-future-states-remain-descriptive.live_grants_checked")
		}
	}
	{
		parsed, valid := ParseU64Decimal("0")
		_ = parsed
		if !(valid == true) {
			tester.Fatal("uint64 decimal")
		}
		if !(strconv.FormatUint(parsed, 10) == "0") {
			tester.Fatal("uint64 roundtrip")
		}
	}
	{
		parsed, valid := ParseU64Decimal("9007199254740993")
		_ = parsed
		if !(valid == true) {
			tester.Fatal("uint64 decimal")
		}
		if !(strconv.FormatUint(parsed, 10) == "9007199254740993") {
			tester.Fatal("uint64 roundtrip")
		}
	}
	{
		parsed, valid := ParseU64Decimal("9223372036854775808")
		_ = parsed
		if !(valid == true) {
			tester.Fatal("uint64 decimal")
		}
		if !(strconv.FormatUint(parsed, 10) == "9223372036854775808") {
			tester.Fatal("uint64 roundtrip")
		}
	}
	{
		parsed, valid := ParseU64Decimal("18446744073709551615")
		_ = parsed
		if !(valid == true) {
			tester.Fatal("uint64 decimal")
		}
		if !(strconv.FormatUint(parsed, 10) == "18446744073709551615") {
			tester.Fatal("uint64 roundtrip")
		}
	}
	{
		parsed, valid := ParseU64Decimal("18446744073709551616")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("-1")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("+1")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("01")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal(" 1")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("1 ")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("1.0")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("1e3")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("1\u0000")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("1\n")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
	{
		parsed, valid := ParseU64Decimal("1\r\n")
		_ = parsed
		if !(valid == false) {
			tester.Fatal("uint64 decimal")
		}
	}
}
