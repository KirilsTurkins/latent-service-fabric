import { profile as Profile } from "../src/index.js";

function check(value: boolean, message: string): asserts value {
  if (!value) throw new Error(message);
}

function rejects(action: () => unknown): void {
  try { action(); } catch (failure) {
    if (failure instanceof RangeError) return;
    throw failure;
  }
  throw new Error("unsigned input must be rejected");
}

{
    const value: Profile.ActivationDiagnostic = {schemaVersion: 1, stage: 3, reason: 1};
    check(value.schemaVersion == 1, "diagnostic-absent-profile-and-bound.schema_version");
    check(value.stage == 3, "diagnostic-absent-profile-and-bound.stage");
    check(value.reason == 1, "diagnostic-absent-profile-and-bound.reason");
    check(!(value.profile !== undefined), "diagnostic-absent-profile-and-bound.profile.presence");
    check(!(value.profileDigest !== undefined), "diagnostic-absent-profile-and-bound.profile_digest.presence");
    check(!(value.configuredBound !== undefined), "diagnostic-absent-profile-and-bound.configured_bound.presence");
    check(!(value.calculatedRequirement !== undefined), "diagnostic-absent-profile-and-bound.calculated_requirement.presence");
    check(!(value.fixedBytes !== undefined), "diagnostic-absent-profile-and-bound.fixed_bytes.presence");
    check(!(value.liftingFuel !== undefined), "diagnostic-absent-profile-and-bound.lifting_fuel.presence");
    check(!(value.liftMultiplier !== undefined), "diagnostic-absent-profile-and-bound.lift_multiplier.presence");
}
{
    const value: Profile.ActivationDiagnostic = {schemaVersion: 1, stage: 2147483647, reason: -1, profile: 999, profileDigest: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", configuredBound: 0n, calculatedRequirement: 18446744073709551615n, fixedBytes: 9223372036854775808n, liftingFuel: 0n, liftMultiplier: 18446744073709551615n};
    check(value.schemaVersion == 1, "diagnostic-unknown-enums-and-present-zero.schema_version");
    check(value.stage == 2147483647, "diagnostic-unknown-enums-and-present-zero.stage");
    check(value.reason == -1, "diagnostic-unknown-enums-and-present-zero.reason");
    check(value.profile !== undefined, "diagnostic-unknown-enums-and-present-zero.profile.presence");
    check(value.profile! == 999, "diagnostic-unknown-enums-and-present-zero.profile");
    check(value.profileDigest !== undefined, "diagnostic-unknown-enums-and-present-zero.profile_digest.presence");
    check(value.profileDigest! == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "diagnostic-unknown-enums-and-present-zero.profile_digest");
    check(value.configuredBound !== undefined, "diagnostic-unknown-enums-and-present-zero.configured_bound.presence");
    check(value.configuredBound! == 0n, "diagnostic-unknown-enums-and-present-zero.configured_bound");
    check(value.calculatedRequirement !== undefined, "diagnostic-unknown-enums-and-present-zero.calculated_requirement.presence");
    check(value.calculatedRequirement! == 18446744073709551615n, "diagnostic-unknown-enums-and-present-zero.calculated_requirement");
    check(value.fixedBytes !== undefined, "diagnostic-unknown-enums-and-present-zero.fixed_bytes.presence");
    check(value.fixedBytes! == 9223372036854775808n, "diagnostic-unknown-enums-and-present-zero.fixed_bytes");
    check(value.liftingFuel !== undefined, "diagnostic-unknown-enums-and-present-zero.lifting_fuel.presence");
    check(value.liftingFuel! == 0n, "diagnostic-unknown-enums-and-present-zero.lifting_fuel");
    check(value.liftMultiplier !== undefined, "diagnostic-unknown-enums-and-present-zero.lift_multiplier.presence");
    check(value.liftMultiplier! == 18446744073709551615n, "diagnostic-unknown-enums-and-present-zero.lift_multiplier");
}
{
    const value: Profile.InspectActivationTreeRequest = {activationId: "activation-a"};
    check(value.activationId == "activation-a", "activation-tree-default-page.activation_id");
    check(!(value.page !== undefined), "activation-tree-default-page.page.presence");
    check(!(value.service !== undefined), "activation-tree-default-page.service.presence");
    check(!(value.fromUnixMillis !== undefined), "activation-tree-default-page.from_unix_millis.presence");
}
{
    const value: Profile.InspectActivationTreeRequest = {activationId: "", page: {pageSize: 128}, service: "examples/java-http-adapter", fromUnixMillis: 18446744073709551615n};
    check(value.activationId == "", "activation-roots-service-time-selector.activation_id");
    check(value.page !== undefined, "activation-roots-service-time-selector.page.presence");
    check(value.page!.pageSize == 128, "activation-roots-service-time-selector.page.page_size");
    check(!(value.page!.pageToken !== undefined), "activation-roots-service-time-selector.page.page_token.presence");
    check(value.service !== undefined, "activation-roots-service-time-selector.service.presence");
    check(value.service! == "examples/java-http-adapter", "activation-roots-service-time-selector.service");
    check(value.fromUnixMillis !== undefined, "activation-roots-service-time-selector.from_unix_millis.presence");
    check(value.fromUnixMillis! == 18446744073709551615n, "activation-roots-service-time-selector.from_unix_millis");
}
{
    const value: Profile.InspectActivationTreeResponse = {schemaVersion: 1, nodes: [{activationId: "host-generated-root", rootActivationId: "host-generated-root", phase: "running", lastUpdatedUnixMillis: 0n, principalKind: "trigger", diagnosticIsTerminal: false, targetService: "examples/java-http-adapter", receivedAtUnixMillis: 18446744073709551615n}], page: {}, historyAvailable: true, cursorExpired: false, retainedHistoryOnly: true};
    check(value.schemaVersion == 1, "activation-root-real-ingress-identity.schema_version");
    check(value.nodes.length == 1, "activation-root-real-ingress-identity.nodes.count");
    check(value.nodes[0]!.activationId == "host-generated-root", "activation-root-real-ingress-identity.nodes.0.activation_id");
    check(!(value.nodes[0]!.parentActivationId !== undefined), "activation-root-real-ingress-identity.nodes.0.parent_activation_id.presence");
    check(value.nodes[0]!.rootActivationId == "host-generated-root", "activation-root-real-ingress-identity.nodes.0.root_activation_id");
    check(value.nodes[0]!.phase == "running", "activation-root-real-ingress-identity.nodes.0.phase");
    check(!(value.nodes[0]!.terminalState !== undefined), "activation-root-real-ingress-identity.nodes.0.terminal_state.presence");
    check(value.nodes[0]!.lastUpdatedUnixMillis == 0n, "activation-root-real-ingress-identity.nodes.0.last_updated_unix_millis");
    check(!(value.nodes[0]!.diagnostic !== undefined), "activation-root-real-ingress-identity.nodes.0.diagnostic.presence");
    check(value.nodes[0]!.principalKind == "trigger", "activation-root-real-ingress-identity.nodes.0.principal_kind");
    check(!(value.nodes[0]!.callerService !== undefined), "activation-root-real-ingress-identity.nodes.0.caller_service.presence");
    check(!(value.nodes[0]!.grantedBudget !== undefined), "activation-root-real-ingress-identity.nodes.0.granted_budget.presence");
    check(!(value.nodes[0]!.effectiveDeadlineUnixMillis !== undefined), "activation-root-real-ingress-identity.nodes.0.effective_deadline_unix_millis.presence");
    check(value.nodes[0]!.diagnosticIsTerminal == false, "activation-root-real-ingress-identity.nodes.0.diagnostic_is_terminal");
    check(value.nodes[0]!.targetService == "examples/java-http-adapter", "activation-root-real-ingress-identity.nodes.0.target_service");
    check(value.nodes[0]!.receivedAtUnixMillis == 18446744073709551615n, "activation-root-real-ingress-identity.nodes.0.received_at_unix_millis");
    check(value.page !== undefined, "activation-root-real-ingress-identity.page.presence");
    check(!(value.page!.nextPageToken !== undefined), "activation-root-real-ingress-identity.page.next_page_token.presence");
    check(value.historyAvailable == true, "activation-root-real-ingress-identity.history_available");
    check(value.cursorExpired == false, "activation-root-real-ingress-identity.cursor_expired");
    check(value.retainedHistoryOnly == true, "activation-root-real-ingress-identity.retained_history_only");
}
{
    const value: Profile.InspectActivationTreeResponse = {schemaVersion: 1, nodes: [], page: {}, historyAvailable: false, cursorExpired: true, retainedHistoryOnly: true};
    check(value.schemaVersion == 1, "activation-tree-expired-is-not-absence-proof.schema_version");
    check(value.nodes.length == 0, "activation-tree-expired-is-not-absence-proof.nodes.count");
    check(value.page !== undefined, "activation-tree-expired-is-not-absence-proof.page.presence");
    check(!(value.page!.nextPageToken !== undefined), "activation-tree-expired-is-not-absence-proof.page.next_page_token.presence");
    check(value.historyAvailable == false, "activation-tree-expired-is-not-absence-proof.history_available");
    check(value.cursorExpired == true, "activation-tree-expired-is-not-absence-proof.cursor_expired");
    check(value.retainedHistoryOnly == true, "activation-tree-expired-is-not-absence-proof.retained_history_only");
}
{
    const value: Profile.InspectActivationTreeResponse = {schemaVersion: 1, nodes: [{activationId: "child-a", parentActivationId: "root-a", rootActivationId: "root-a", phase: "received", terminalState: "resource_exhausted", lastUpdatedUnixMillis: 18446744073709551615n, diagnostic: {schemaVersion: 1, stage: 3, reason: 1, profile: 1, configuredBound: 16777216n, calculatedRequirement: 67108864n}, principalKind: "service", callerService: "adapter", diagnosticIsTerminal: true, targetService: "", receivedAtUnixMillis: 0n}], page: {nextPageToken: "opaque-scoped-cursor"}, historyAvailable: true, cursorExpired: false, retainedHistoryOnly: true};
    check(value.schemaVersion == 1, "activation-tree-failed-preparation-before-guest.schema_version");
    check(value.nodes.length == 1, "activation-tree-failed-preparation-before-guest.nodes.count");
    check(value.nodes[0]!.activationId == "child-a", "activation-tree-failed-preparation-before-guest.nodes.0.activation_id");
    check(value.nodes[0]!.parentActivationId !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.parent_activation_id.presence");
    check(value.nodes[0]!.parentActivationId! == "root-a", "activation-tree-failed-preparation-before-guest.nodes.0.parent_activation_id");
    check(value.nodes[0]!.rootActivationId == "root-a", "activation-tree-failed-preparation-before-guest.nodes.0.root_activation_id");
    check(value.nodes[0]!.phase == "received", "activation-tree-failed-preparation-before-guest.nodes.0.phase");
    check(value.nodes[0]!.terminalState !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.terminal_state.presence");
    check(value.nodes[0]!.terminalState! == "resource_exhausted", "activation-tree-failed-preparation-before-guest.nodes.0.terminal_state");
    check(value.nodes[0]!.lastUpdatedUnixMillis == 18446744073709551615n, "activation-tree-failed-preparation-before-guest.nodes.0.last_updated_unix_millis");
    check(value.nodes[0]!.diagnostic !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.presence");
    check(value.nodes[0]!.diagnostic!.schemaVersion == 1, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.schema_version");
    check(value.nodes[0]!.diagnostic!.stage == 3, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.stage");
    check(value.nodes[0]!.diagnostic!.reason == 1, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.reason");
    check(value.nodes[0]!.diagnostic!.profile !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.profile.presence");
    check(value.nodes[0]!.diagnostic!.profile! == 1, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.profile");
    check(!(value.nodes[0]!.diagnostic!.profileDigest !== undefined), "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.profile_digest.presence");
    check(value.nodes[0]!.diagnostic!.configuredBound !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.configured_bound.presence");
    check(value.nodes[0]!.diagnostic!.configuredBound! == 16777216n, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.configured_bound");
    check(value.nodes[0]!.diagnostic!.calculatedRequirement !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.calculated_requirement.presence");
    check(value.nodes[0]!.diagnostic!.calculatedRequirement! == 67108864n, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.calculated_requirement");
    check(!(value.nodes[0]!.diagnostic!.fixedBytes !== undefined), "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.fixed_bytes.presence");
    check(!(value.nodes[0]!.diagnostic!.liftingFuel !== undefined), "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.lifting_fuel.presence");
    check(!(value.nodes[0]!.diagnostic!.liftMultiplier !== undefined), "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic.lift_multiplier.presence");
    check(value.nodes[0]!.principalKind == "service", "activation-tree-failed-preparation-before-guest.nodes.0.principal_kind");
    check(value.nodes[0]!.callerService !== undefined, "activation-tree-failed-preparation-before-guest.nodes.0.caller_service.presence");
    check(value.nodes[0]!.callerService! == "adapter", "activation-tree-failed-preparation-before-guest.nodes.0.caller_service");
    check(!(value.nodes[0]!.grantedBudget !== undefined), "activation-tree-failed-preparation-before-guest.nodes.0.granted_budget.presence");
    check(!(value.nodes[0]!.effectiveDeadlineUnixMillis !== undefined), "activation-tree-failed-preparation-before-guest.nodes.0.effective_deadline_unix_millis.presence");
    check(value.nodes[0]!.diagnosticIsTerminal == true, "activation-tree-failed-preparation-before-guest.nodes.0.diagnostic_is_terminal");
    check(value.nodes[0]!.targetService == "", "activation-tree-failed-preparation-before-guest.nodes.0.target_service");
    check(value.nodes[0]!.receivedAtUnixMillis == 0n, "activation-tree-failed-preparation-before-guest.nodes.0.received_at_unix_millis");
    check(value.page !== undefined, "activation-tree-failed-preparation-before-guest.page.presence");
    check(value.page!.nextPageToken !== undefined, "activation-tree-failed-preparation-before-guest.page.next_page_token.presence");
    check(value.page!.nextPageToken! == "opaque-scoped-cursor", "activation-tree-failed-preparation-before-guest.page.next_page_token");
    check(value.historyAvailable == true, "activation-tree-failed-preparation-before-guest.history_available");
    check(value.cursorExpired == false, "activation-tree-failed-preparation-before-guest.cursor_expired");
    check(value.retainedHistoryOnly == true, "activation-tree-failed-preparation-before-guest.retained_history_only");
}
{
    const value: Profile.InvokeRequest = {target: {tenant: "tenant-a", service: "echo", contract: "example:echo/api@1.0.0", function: "echo"}, payload: new Uint8Array([0, 1, 2, 255]), mediaType: "application/octet-stream", priority: 0, budget: {cpuFuel: 18446744073709551615n, memoryBytes: 9223372036854775808n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0}, metadata: {"trace": "redacted"}};
    check(!(value.activationId !== undefined), "invoke-absent-identity-and-deadlines.activation_id.presence");
    check(!(value.parentActivationId !== undefined), "invoke-absent-identity-and-deadlines.parent_activation_id.presence");
    check(!(value.rootActivationId !== undefined), "invoke-absent-identity-and-deadlines.root_activation_id.presence");
    check(value.target !== undefined, "invoke-absent-identity-and-deadlines.target.presence");
    check(value.target!.tenant == "tenant-a", "invoke-absent-identity-and-deadlines.target.tenant");
    check(value.target!.service == "echo", "invoke-absent-identity-and-deadlines.target.service");
    check(value.target!.contract == "example:echo/api@1.0.0", "invoke-absent-identity-and-deadlines.target.contract");
    check(value.target!.function == "echo", "invoke-absent-identity-and-deadlines.target.function");
    check(!(value.target!.route !== undefined), "invoke-absent-identity-and-deadlines.target.route.presence");
    check(value.payload.length == 4, "invoke-absent-identity-and-deadlines.payload.length");
    check(value.payload[0] == 0, "invoke-absent-identity-and-deadlines.payload.0");
    check(value.payload[1] == 1, "invoke-absent-identity-and-deadlines.payload.1");
    check(value.payload[2] == 2, "invoke-absent-identity-and-deadlines.payload.2");
    check(value.payload[3] == 255, "invoke-absent-identity-and-deadlines.payload.3");
    check(value.mediaType == "application/octet-stream", "invoke-absent-identity-and-deadlines.media_type");
    check(!(value.deadlineUnixMillis !== undefined), "invoke-absent-identity-and-deadlines.deadline_unix_millis.presence");
    check(value.priority == 0, "invoke-absent-identity-and-deadlines.priority");
    check(!(value.idempotencyKey !== undefined), "invoke-absent-identity-and-deadlines.idempotency_key.presence");
    check(value.budget !== undefined, "invoke-absent-identity-and-deadlines.budget.presence");
    check(value.budget!.cpuFuel == 18446744073709551615n, "invoke-absent-identity-and-deadlines.budget.cpu_fuel");
    check(value.budget!.memoryBytes == 9223372036854775808n, "invoke-absent-identity-and-deadlines.budget.memory_bytes");
    check(value.budget!.childCalls == 0, "invoke-absent-identity-and-deadlines.budget.child_calls");
    check(value.budget!.outboundRequests == 0, "invoke-absent-identity-and-deadlines.budget.outbound_requests");
    check(value.budget!.stateReadBytes == 0n, "invoke-absent-identity-and-deadlines.budget.state_read_bytes");
    check(value.budget!.stateWriteBytes == 0n, "invoke-absent-identity-and-deadlines.budget.state_write_bytes");
    check(value.budget!.blobReadBytes == 0n, "invoke-absent-identity-and-deadlines.budget.blob_read_bytes");
    check(value.budget!.blobWriteBytes == 0n, "invoke-absent-identity-and-deadlines.budget.blob_write_bytes");
    check(value.budget!.logBytes == 0n, "invoke-absent-identity-and-deadlines.budget.log_bytes");
    check(value.budget!.effectCount == 0, "invoke-absent-identity-and-deadlines.budget.effect_count");
    check(!(value.budget!.wallTimeLimitMillis !== undefined), "invoke-absent-identity-and-deadlines.budget.wall_time_limit_millis.presence");
    check(Object.keys(value.metadata).length == 1, "invoke-absent-identity-and-deadlines.metadata.count");
    check(value.metadata["trace"]! == "redacted", "invoke-absent-identity-and-deadlines.metadata.0");
}
{
    const value: Profile.InvokeRequest = {activationId: "", parentActivationId: "parent-a", rootActivationId: "", target: {tenant: "", service: "", contract: "", function: "", route: ""}, payload: new Uint8Array([]), mediaType: "", deadlineUnixMillis: 0n, priority: 0, idempotencyKey: "", budget: {cpuFuel: 0n, memoryBytes: 0n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0, wallTimeLimitMillis: 0n}, metadata: {}};
    check(value.activationId !== undefined, "invoke-present-invalid-and-zero-not-absence.activation_id.presence");
    check(value.activationId! == "", "invoke-present-invalid-and-zero-not-absence.activation_id");
    check(value.parentActivationId !== undefined, "invoke-present-invalid-and-zero-not-absence.parent_activation_id.presence");
    check(value.parentActivationId! == "parent-a", "invoke-present-invalid-and-zero-not-absence.parent_activation_id");
    check(value.rootActivationId !== undefined, "invoke-present-invalid-and-zero-not-absence.root_activation_id.presence");
    check(value.rootActivationId! == "", "invoke-present-invalid-and-zero-not-absence.root_activation_id");
    check(value.target !== undefined, "invoke-present-invalid-and-zero-not-absence.target.presence");
    check(value.target!.tenant == "", "invoke-present-invalid-and-zero-not-absence.target.tenant");
    check(value.target!.service == "", "invoke-present-invalid-and-zero-not-absence.target.service");
    check(value.target!.contract == "", "invoke-present-invalid-and-zero-not-absence.target.contract");
    check(value.target!.function == "", "invoke-present-invalid-and-zero-not-absence.target.function");
    check(value.target!.route !== undefined, "invoke-present-invalid-and-zero-not-absence.target.route.presence");
    check(value.target!.route! == "", "invoke-present-invalid-and-zero-not-absence.target.route");
    check(value.payload.length == 0, "invoke-present-invalid-and-zero-not-absence.payload.length");
    check(value.mediaType == "", "invoke-present-invalid-and-zero-not-absence.media_type");
    check(value.deadlineUnixMillis !== undefined, "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis.presence");
    check(value.deadlineUnixMillis! == 0n, "invoke-present-invalid-and-zero-not-absence.deadline_unix_millis");
    check(value.priority == 0, "invoke-present-invalid-and-zero-not-absence.priority");
    check(value.idempotencyKey !== undefined, "invoke-present-invalid-and-zero-not-absence.idempotency_key.presence");
    check(value.idempotencyKey! == "", "invoke-present-invalid-and-zero-not-absence.idempotency_key");
    check(value.budget !== undefined, "invoke-present-invalid-and-zero-not-absence.budget.presence");
    check(value.budget!.cpuFuel == 0n, "invoke-present-invalid-and-zero-not-absence.budget.cpu_fuel");
    check(value.budget!.memoryBytes == 0n, "invoke-present-invalid-and-zero-not-absence.budget.memory_bytes");
    check(value.budget!.childCalls == 0, "invoke-present-invalid-and-zero-not-absence.budget.child_calls");
    check(value.budget!.outboundRequests == 0, "invoke-present-invalid-and-zero-not-absence.budget.outbound_requests");
    check(value.budget!.stateReadBytes == 0n, "invoke-present-invalid-and-zero-not-absence.budget.state_read_bytes");
    check(value.budget!.stateWriteBytes == 0n, "invoke-present-invalid-and-zero-not-absence.budget.state_write_bytes");
    check(value.budget!.blobReadBytes == 0n, "invoke-present-invalid-and-zero-not-absence.budget.blob_read_bytes");
    check(value.budget!.blobWriteBytes == 0n, "invoke-present-invalid-and-zero-not-absence.budget.blob_write_bytes");
    check(value.budget!.logBytes == 0n, "invoke-present-invalid-and-zero-not-absence.budget.log_bytes");
    check(value.budget!.effectCount == 0, "invoke-present-invalid-and-zero-not-absence.budget.effect_count");
    check(value.budget!.wallTimeLimitMillis !== undefined, "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis.presence");
    check(value.budget!.wallTimeLimitMillis! == 0n, "invoke-present-invalid-and-zero-not-absence.budget.wall_time_limit_millis");
    check(Object.keys(value.metadata).length == 0, "invoke-present-invalid-and-zero-not-absence.metadata.count");
}
{
    const value: Profile.InvokeRequest = {activationId: "activation-a", parentActivationId: "parent-a", rootActivationId: "root-a", payload: new Uint8Array([]), mediaType: "", deadlineUnixMillis: 18446744073709551615n, priority: 4294967295, idempotencyKey: "not-an-authority-or-retry-key", metadata: {}};
    check(value.activationId !== undefined, "invoke-known-identity-full-width-deadline-and-priority.activation_id.presence");
    check(value.activationId! == "activation-a", "invoke-known-identity-full-width-deadline-and-priority.activation_id");
    check(value.parentActivationId !== undefined, "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id.presence");
    check(value.parentActivationId! == "parent-a", "invoke-known-identity-full-width-deadline-and-priority.parent_activation_id");
    check(value.rootActivationId !== undefined, "invoke-known-identity-full-width-deadline-and-priority.root_activation_id.presence");
    check(value.rootActivationId! == "root-a", "invoke-known-identity-full-width-deadline-and-priority.root_activation_id");
    check(!(value.target !== undefined), "invoke-known-identity-full-width-deadline-and-priority.target.presence");
    check(value.payload.length == 0, "invoke-known-identity-full-width-deadline-and-priority.payload.length");
    check(value.mediaType == "", "invoke-known-identity-full-width-deadline-and-priority.media_type");
    check(value.deadlineUnixMillis !== undefined, "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis.presence");
    check(value.deadlineUnixMillis! == 18446744073709551615n, "invoke-known-identity-full-width-deadline-and-priority.deadline_unix_millis");
    check(value.priority == 4294967295, "invoke-known-identity-full-width-deadline-and-priority.priority");
    check(value.idempotencyKey !== undefined, "invoke-known-identity-full-width-deadline-and-priority.idempotency_key.presence");
    check(value.idempotencyKey! == "not-an-authority-or-retry-key", "invoke-known-identity-full-width-deadline-and-priority.idempotency_key");
    check(!(value.budget !== undefined), "invoke-known-identity-full-width-deadline-and-priority.budget.presence");
    check(Object.keys(value.metadata).length == 0, "invoke-known-identity-full-width-deadline-and-priority.metadata.count");
}
{
    const value: Profile.ResourceBudget = {cpuFuel: 18446744073709551615n, memoryBytes: 18446744073709551615n, childCalls: 4294967295, outboundRequests: 4294967295, stateReadBytes: 18446744073709551615n, stateWriteBytes: 18446744073709551615n, blobReadBytes: 18446744073709551615n, blobWriteBytes: 18446744073709551615n, logBytes: 18446744073709551615n, effectCount: 4294967295, wallTimeLimitMillis: 18446744073709551615n};
    check(value.cpuFuel == 18446744073709551615n, "full-resource-budget.cpu_fuel");
    check(value.memoryBytes == 18446744073709551615n, "full-resource-budget.memory_bytes");
    check(value.childCalls == 4294967295, "full-resource-budget.child_calls");
    check(value.outboundRequests == 4294967295, "full-resource-budget.outbound_requests");
    check(value.stateReadBytes == 18446744073709551615n, "full-resource-budget.state_read_bytes");
    check(value.stateWriteBytes == 18446744073709551615n, "full-resource-budget.state_write_bytes");
    check(value.blobReadBytes == 18446744073709551615n, "full-resource-budget.blob_read_bytes");
    check(value.blobWriteBytes == 18446744073709551615n, "full-resource-budget.blob_write_bytes");
    check(value.logBytes == 18446744073709551615n, "full-resource-budget.log_bytes");
    check(value.effectCount == 4294967295, "full-resource-budget.effect_count");
    check(value.wallTimeLimitMillis !== undefined, "full-resource-budget.wall_time_limit_millis.presence");
    check(value.wallTimeLimitMillis! == 18446744073709551615n, "full-resource-budget.wall_time_limit_millis");
}
{
    const value: Profile.InvokeResponse = {activationId: "activation-a", revisionId: "revision-a", releaseDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", routeGeneration: 18446744073709551615n, success: {payload: new Uint8Array([0, 1, 2, 255]), mediaType: "application/octet-stream", committedStateVersion: "", effectIds: ["effect-a", "effect-b"], metadata: {"result": "redacted"}}, consumption: {cpuFuel: 18446744073709551615n, peakMemoryBytes: 0n, wallTimeMicros: 9007199254740993n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0}, publicationId: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"};
    check(value.activationId == "activation-a", "invoke-success-retains-publication-and-component.activation_id");
    check(value.revisionId == "revision-a", "invoke-success-retains-publication-and-component.revision_id");
    check(value.releaseDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "invoke-success-retains-publication-and-component.release_digest");
    check(value.routeGeneration == 18446744073709551615n, "invoke-success-retains-publication-and-component.route_generation");
    check(value.success !== undefined, "invoke-success-retains-publication-and-component.success.presence");
    check(value.success!.payload.length == 4, "invoke-success-retains-publication-and-component.success.payload.length");
    check(value.success!.payload[0] == 0, "invoke-success-retains-publication-and-component.success.payload.0");
    check(value.success!.payload[1] == 1, "invoke-success-retains-publication-and-component.success.payload.1");
    check(value.success!.payload[2] == 2, "invoke-success-retains-publication-and-component.success.payload.2");
    check(value.success!.payload[3] == 255, "invoke-success-retains-publication-and-component.success.payload.3");
    check(value.success!.mediaType == "application/octet-stream", "invoke-success-retains-publication-and-component.success.media_type");
    check(value.success!.committedStateVersion !== undefined, "invoke-success-retains-publication-and-component.success.committed_state_version.presence");
    check(value.success!.committedStateVersion! == "", "invoke-success-retains-publication-and-component.success.committed_state_version");
    check(value.success!.effectIds.length == 2, "invoke-success-retains-publication-and-component.success.effect_ids.count");
    check(value.success!.effectIds[0]! == "effect-a", "invoke-success-retains-publication-and-component.success.effect_ids.0");
    check(value.success!.effectIds[1]! == "effect-b", "invoke-success-retains-publication-and-component.success.effect_ids.1");
    check(Object.keys(value.success!.metadata).length == 1, "invoke-success-retains-publication-and-component.success.metadata.count");
    check(value.success!.metadata["result"]! == "redacted", "invoke-success-retains-publication-and-component.success.metadata.0");
    check(!(value.declaredError !== undefined), "invoke-success-retains-publication-and-component.declared_error.presence");
    check(!(value.platformFailure !== undefined), "invoke-success-retains-publication-and-component.platform_failure.presence");
    check(value.consumption !== undefined, "invoke-success-retains-publication-and-component.consumption.presence");
    check(value.consumption!.cpuFuel == 18446744073709551615n, "invoke-success-retains-publication-and-component.consumption.cpu_fuel");
    check(value.consumption!.peakMemoryBytes == 0n, "invoke-success-retains-publication-and-component.consumption.peak_memory_bytes");
    check(value.consumption!.wallTimeMicros == 9007199254740993n, "invoke-success-retains-publication-and-component.consumption.wall_time_micros");
    check(value.consumption!.childCalls == 0, "invoke-success-retains-publication-and-component.consumption.child_calls");
    check(value.consumption!.outboundRequests == 0, "invoke-success-retains-publication-and-component.consumption.outbound_requests");
    check(value.consumption!.stateReadBytes == 0n, "invoke-success-retains-publication-and-component.consumption.state_read_bytes");
    check(value.consumption!.stateWriteBytes == 0n, "invoke-success-retains-publication-and-component.consumption.state_write_bytes");
    check(value.consumption!.blobReadBytes == 0n, "invoke-success-retains-publication-and-component.consumption.blob_read_bytes");
    check(value.consumption!.blobWriteBytes == 0n, "invoke-success-retains-publication-and-component.consumption.blob_write_bytes");
    check(value.consumption!.logBytes == 0n, "invoke-success-retains-publication-and-component.consumption.log_bytes");
    check(value.consumption!.effectCount == 0, "invoke-success-retains-publication-and-component.consumption.effect_count");
    check(value.publicationId !== undefined, "invoke-success-retains-publication-and-component.publication_id.presence");
    check(value.publicationId! == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "invoke-success-retains-publication-and-component.publication_id");
}
{
    const value: Profile.InvokeResponse = {activationId: "activation-a", revisionId: "revision-a", releaseDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", routeGeneration: 9223372036854775808n, declaredError: {code: "uncertain", message: "provider outcome unknown", payload: new Uint8Array([0, 1, 2, 255]), mediaType: "application/octet-stream", metadata: {"contract": "latent:http/streaming@0.3.0"}}, consumption: {cpuFuel: 0n, peakMemoryBytes: 0n, wallTimeMicros: 0n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 18446744073709551615n, logBytes: 0n, effectCount: 0}, publicationId: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111"};
    check(value.activationId == "activation-a", "typed-declared-provider-uncertainty-retains-receipt.activation_id");
    check(value.revisionId == "revision-a", "typed-declared-provider-uncertainty-retains-receipt.revision_id");
    check(value.releaseDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "typed-declared-provider-uncertainty-retains-receipt.release_digest");
    check(value.routeGeneration == 9223372036854775808n, "typed-declared-provider-uncertainty-retains-receipt.route_generation");
    check(!(value.success !== undefined), "typed-declared-provider-uncertainty-retains-receipt.success.presence");
    check(value.declaredError !== undefined, "typed-declared-provider-uncertainty-retains-receipt.declared_error.presence");
    check(value.declaredError!.code == "uncertain", "typed-declared-provider-uncertainty-retains-receipt.declared_error.code");
    check(value.declaredError!.message == "provider outcome unknown", "typed-declared-provider-uncertainty-retains-receipt.declared_error.message");
    check(value.declaredError!.payload.length == 4, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.length");
    check(value.declaredError!.payload[0] == 0, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.0");
    check(value.declaredError!.payload[1] == 1, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.1");
    check(value.declaredError!.payload[2] == 2, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.2");
    check(value.declaredError!.payload[3] == 255, "typed-declared-provider-uncertainty-retains-receipt.declared_error.payload.3");
    check(value.declaredError!.mediaType == "application/octet-stream", "typed-declared-provider-uncertainty-retains-receipt.declared_error.media_type");
    check(Object.keys(value.declaredError!.metadata).length == 1, "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.count");
    check(value.declaredError!.metadata["contract"]! == "latent:http/streaming@0.3.0", "typed-declared-provider-uncertainty-retains-receipt.declared_error.metadata.0");
    check(!(value.platformFailure !== undefined), "typed-declared-provider-uncertainty-retains-receipt.platform_failure.presence");
    check(value.consumption !== undefined, "typed-declared-provider-uncertainty-retains-receipt.consumption.presence");
    check(value.consumption!.cpuFuel == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.cpu_fuel");
    check(value.consumption!.peakMemoryBytes == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.peak_memory_bytes");
    check(value.consumption!.wallTimeMicros == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.wall_time_micros");
    check(value.consumption!.childCalls == 0, "typed-declared-provider-uncertainty-retains-receipt.consumption.child_calls");
    check(value.consumption!.outboundRequests == 0, "typed-declared-provider-uncertainty-retains-receipt.consumption.outbound_requests");
    check(value.consumption!.stateReadBytes == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.state_read_bytes");
    check(value.consumption!.stateWriteBytes == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.state_write_bytes");
    check(value.consumption!.blobReadBytes == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_read_bytes");
    check(value.consumption!.blobWriteBytes == 18446744073709551615n, "typed-declared-provider-uncertainty-retains-receipt.consumption.blob_write_bytes");
    check(value.consumption!.logBytes == 0n, "typed-declared-provider-uncertainty-retains-receipt.consumption.log_bytes");
    check(value.consumption!.effectCount == 0, "typed-declared-provider-uncertainty-retains-receipt.consumption.effect_count");
    check(value.publicationId !== undefined, "typed-declared-provider-uncertainty-retains-receipt.publication_id.presence");
    check(value.publicationId! == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "typed-declared-provider-uncertainty-retains-receipt.publication_id");
}
{
    const value: Profile.InvokeResponse = {activationId: "activation-a", revisionId: "", releaseDigest: "", routeGeneration: 0n, platformFailure: {code: "permission-denied", message: "capability-provider-failed", retryable: false, detailItems: [{kind: "capability-observation", fields: {"capability": "latent:http/streaming@0.3.0", "state": "policy-revoked"}}, {kind: "future-detail", fields: {"bounded": "preserved"}}]}, consumption: {cpuFuel: 0n, peakMemoryBytes: 0n, wallTimeMicros: 0n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 18446744073709551615n, effectCount: 0}};
    check(value.activationId == "activation-a", "typed-platform-capability-failure-retains-detail-items.activation_id");
    check(value.revisionId == "", "typed-platform-capability-failure-retains-detail-items.revision_id");
    check(value.releaseDigest == "", "typed-platform-capability-failure-retains-detail-items.release_digest");
    check(value.routeGeneration == 0n, "typed-platform-capability-failure-retains-detail-items.route_generation");
    check(!(value.success !== undefined), "typed-platform-capability-failure-retains-detail-items.success.presence");
    check(!(value.declaredError !== undefined), "typed-platform-capability-failure-retains-detail-items.declared_error.presence");
    check(value.platformFailure !== undefined, "typed-platform-capability-failure-retains-detail-items.platform_failure.presence");
    check(value.platformFailure!.code == "permission-denied", "typed-platform-capability-failure-retains-detail-items.platform_failure.code");
    check(value.platformFailure!.message == "capability-provider-failed", "typed-platform-capability-failure-retains-detail-items.platform_failure.message");
    check(value.platformFailure!.retryable == false, "typed-platform-capability-failure-retains-detail-items.platform_failure.retryable");
    check(value.platformFailure!.detailItems.length == 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.count");
    check(value.platformFailure!.detailItems[0]!.kind == "capability-observation", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.kind");
    check(Object.keys(value.platformFailure!.detailItems[0]!.fields).length == 2, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.count");
    check(value.platformFailure!.detailItems[0]!.fields["capability"]! == "latent:http/streaming@0.3.0", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.0");
    check(value.platformFailure!.detailItems[0]!.fields["state"]! == "policy-revoked", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.0.fields.1");
    check(value.platformFailure!.detailItems[1]!.kind == "future-detail", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.kind");
    check(Object.keys(value.platformFailure!.detailItems[1]!.fields).length == 1, "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.count");
    check(value.platformFailure!.detailItems[1]!.fields["bounded"]! == "preserved", "typed-platform-capability-failure-retains-detail-items.platform_failure.detail_items.1.fields.0");
    check(value.consumption !== undefined, "typed-platform-capability-failure-retains-detail-items.consumption.presence");
    check(value.consumption!.cpuFuel == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.cpu_fuel");
    check(value.consumption!.peakMemoryBytes == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.peak_memory_bytes");
    check(value.consumption!.wallTimeMicros == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.wall_time_micros");
    check(value.consumption!.childCalls == 0, "typed-platform-capability-failure-retains-detail-items.consumption.child_calls");
    check(value.consumption!.outboundRequests == 0, "typed-platform-capability-failure-retains-detail-items.consumption.outbound_requests");
    check(value.consumption!.stateReadBytes == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.state_read_bytes");
    check(value.consumption!.stateWriteBytes == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.state_write_bytes");
    check(value.consumption!.blobReadBytes == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.blob_read_bytes");
    check(value.consumption!.blobWriteBytes == 0n, "typed-platform-capability-failure-retains-detail-items.consumption.blob_write_bytes");
    check(value.consumption!.logBytes == 18446744073709551615n, "typed-platform-capability-failure-retains-detail-items.consumption.log_bytes");
    check(value.consumption!.effectCount == 0, "typed-platform-capability-failure-retains-detail-items.consumption.effect_count");
    check(!(value.publicationId !== undefined), "typed-platform-capability-failure-retains-detail-items.publication_id.presence");
}
{
    const value: Profile.InvokeResponse = {activationId: "activation-a", revisionId: "", releaseDigest: "", routeGeneration: 0n, success: {payload: new Uint8Array([]), mediaType: "", effectIds: [], metadata: {}}, publicationId: ""};
    check(value.activationId == "activation-a", "present-invalid-publication-not-legacy.activation_id");
    check(value.revisionId == "", "present-invalid-publication-not-legacy.revision_id");
    check(value.releaseDigest == "", "present-invalid-publication-not-legacy.release_digest");
    check(value.routeGeneration == 0n, "present-invalid-publication-not-legacy.route_generation");
    check(value.success !== undefined, "present-invalid-publication-not-legacy.success.presence");
    check(value.success!.payload.length == 0, "present-invalid-publication-not-legacy.success.payload.length");
    check(value.success!.mediaType == "", "present-invalid-publication-not-legacy.success.media_type");
    check(!(value.success!.committedStateVersion !== undefined), "present-invalid-publication-not-legacy.success.committed_state_version.presence");
    check(value.success!.effectIds.length == 0, "present-invalid-publication-not-legacy.success.effect_ids.count");
    check(Object.keys(value.success!.metadata).length == 0, "present-invalid-publication-not-legacy.success.metadata.count");
    check(!(value.declaredError !== undefined), "present-invalid-publication-not-legacy.declared_error.presence");
    check(!(value.platformFailure !== undefined), "present-invalid-publication-not-legacy.platform_failure.presence");
    check(!(value.consumption !== undefined), "present-invalid-publication-not-legacy.consumption.presence");
    check(value.publicationId !== undefined, "present-invalid-publication-not-legacy.publication_id.presence");
    check(value.publicationId! == "", "present-invalid-publication-not-legacy.publication_id");
}
{
    const value: Profile.InvokeResponse = {activationId: "activation-a", revisionId: "", releaseDigest: "", routeGeneration: 0n, success: {payload: new Uint8Array([]), mediaType: "", effectIds: [], metadata: {}}, platformFailure: {code: "internal", message: "", retryable: false, detailItems: []}};
    check(value.activationId == "activation-a", "contradictory-outcome-retained-for-rejection.activation_id");
    check(value.revisionId == "", "contradictory-outcome-retained-for-rejection.revision_id");
    check(value.releaseDigest == "", "contradictory-outcome-retained-for-rejection.release_digest");
    check(value.routeGeneration == 0n, "contradictory-outcome-retained-for-rejection.route_generation");
    check(value.success !== undefined, "contradictory-outcome-retained-for-rejection.success.presence");
    check(value.success!.payload.length == 0, "contradictory-outcome-retained-for-rejection.success.payload.length");
    check(value.success!.mediaType == "", "contradictory-outcome-retained-for-rejection.success.media_type");
    check(!(value.success!.committedStateVersion !== undefined), "contradictory-outcome-retained-for-rejection.success.committed_state_version.presence");
    check(value.success!.effectIds.length == 0, "contradictory-outcome-retained-for-rejection.success.effect_ids.count");
    check(Object.keys(value.success!.metadata).length == 0, "contradictory-outcome-retained-for-rejection.success.metadata.count");
    check(!(value.declaredError !== undefined), "contradictory-outcome-retained-for-rejection.declared_error.presence");
    check(value.platformFailure !== undefined, "contradictory-outcome-retained-for-rejection.platform_failure.presence");
    check(value.platformFailure!.code == "internal", "contradictory-outcome-retained-for-rejection.platform_failure.code");
    check(value.platformFailure!.message == "", "contradictory-outcome-retained-for-rejection.platform_failure.message");
    check(value.platformFailure!.retryable == false, "contradictory-outcome-retained-for-rejection.platform_failure.retryable");
    check(value.platformFailure!.detailItems.length == 0, "contradictory-outcome-retained-for-rejection.platform_failure.detail_items.count");
    check(!(value.consumption !== undefined), "contradictory-outcome-retained-for-rejection.consumption.presence");
    check(!(value.publicationId !== undefined), "contradictory-outcome-retained-for-rejection.publication_id.presence");
}
{
    const value: Profile.CancelRequest = {activationId: "activation-a", reason: "caller-requested"};
    check(value.activationId == "activation-a", "cancel-request-known-id.activation_id");
    check(value.reason == "caller-requested", "cancel-request-known-id.reason");
}
{
    const value: Profile.CancelResponse = {disposition: 1};
    check(value.disposition == 1, "cancel-accepted-not-cleanup.disposition");
    check(!(value.terminalState !== undefined), "cancel-accepted-not-cleanup.terminal_state.presence");
}
{
    const value: Profile.CancelResponse = {disposition: 2, terminalState: "completed"};
    check(value.disposition == 2, "cancel-already-terminal.disposition");
    check(value.terminalState !== undefined, "cancel-already-terminal.terminal_state.presence");
    check(value.terminalState! == "completed", "cancel-already-terminal.terminal_state");
}
{
    const value: Profile.CancelResponse = {disposition: 3};
    check(value.disposition == 3, "cancel-not-found-not-nonexecution.disposition");
    check(!(value.terminalState !== undefined), "cancel-not-found-not-nonexecution.terminal_state.presence");
}
{
    const value: Profile.CancelResponse = {disposition: 0, terminalState: ""};
    check(value.disposition == 0, "cancel-unspecified-not-accepted.disposition");
    check(value.terminalState !== undefined, "cancel-unspecified-not-accepted.terminal_state.presence");
    check(value.terminalState! == "", "cancel-unspecified-not-accepted.terminal_state");
}
{
    const value: Profile.CancelResponse = {disposition: 91, terminalState: "future-terminal-state"};
    check(value.disposition == 91, "cancel-unknown-enum.disposition");
    check(value.terminalState !== undefined, "cancel-unknown-enum.terminal_state.presence");
    check(value.terminalState! == "future-terminal-state", "cancel-unknown-enum.terminal_state");
}
{
    const value: Profile.CancelResponse = {disposition: -2147483648};
    check(value.disposition == -2147483648, "cancel-negative-enum.disposition");
    check(!(value.terminalState !== undefined), "cancel-negative-enum.terminal_state.presence");
}
{
    const value: Profile.GetActivationRequest = {activationId: "activation-a"};
    check(value.activationId == "activation-a", "get-activation-recovery.activation_id");
}
{
    const value: Profile.ActivationStatus = {activationId: "activation-a", phase: "running", lastUpdatedUnixMillis: 18446744073709551615n, metadata: {}};
    check(value.activationId == "activation-a", "activation-running-absent-terminal.activation_id");
    check(value.phase == "running", "activation-running-absent-terminal.phase");
    check(!(value.terminalState !== undefined), "activation-running-absent-terminal.terminal_state.presence");
    check(value.lastUpdatedUnixMillis == 18446744073709551615n, "activation-running-absent-terminal.last_updated_unix_millis");
    check(Object.keys(value.metadata).length == 0, "activation-running-absent-terminal.metadata.count");
    check(!(value.succeeded !== undefined), "activation-running-absent-terminal.succeeded.presence");
    check(!(value.declaredError !== undefined), "activation-running-absent-terminal.declared_error.presence");
    check(!(value.platformFailure !== undefined), "activation-running-absent-terminal.platform_failure.presence");
    check(!(value.finalConsumption !== undefined), "activation-running-absent-terminal.final_consumption.presence");
    check(!(value.terminalAtUnixMillis !== undefined), "activation-running-absent-terminal.terminal_at_unix_millis.presence");
}
{
    const value: Profile.ActivationStatus = {activationId: "activation-a", phase: "terminal", terminalState: "failed", lastUpdatedUnixMillis: 0n, metadata: {}, platformFailure: {code: "resource-exhausted", message: "capability-capacity", retryable: false, detailItems: [{kind: "budget", fields: {"resource": "buffer-bytes"}}]}, finalConsumption: {cpuFuel: 0n, peakMemoryBytes: 18446744073709551615n, wallTimeMicros: 0n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0}, terminalAtUnixMillis: 0n};
    check(value.activationId == "activation-a", "activation-terminal-typed-failure.activation_id");
    check(value.phase == "terminal", "activation-terminal-typed-failure.phase");
    check(value.terminalState !== undefined, "activation-terminal-typed-failure.terminal_state.presence");
    check(value.terminalState! == "failed", "activation-terminal-typed-failure.terminal_state");
    check(value.lastUpdatedUnixMillis == 0n, "activation-terminal-typed-failure.last_updated_unix_millis");
    check(Object.keys(value.metadata).length == 0, "activation-terminal-typed-failure.metadata.count");
    check(!(value.succeeded !== undefined), "activation-terminal-typed-failure.succeeded.presence");
    check(!(value.declaredError !== undefined), "activation-terminal-typed-failure.declared_error.presence");
    check(value.platformFailure !== undefined, "activation-terminal-typed-failure.platform_failure.presence");
    check(value.platformFailure!.code == "resource-exhausted", "activation-terminal-typed-failure.platform_failure.code");
    check(value.platformFailure!.message == "capability-capacity", "activation-terminal-typed-failure.platform_failure.message");
    check(value.platformFailure!.retryable == false, "activation-terminal-typed-failure.platform_failure.retryable");
    check(value.platformFailure!.detailItems.length == 1, "activation-terminal-typed-failure.platform_failure.detail_items.count");
    check(value.platformFailure!.detailItems[0]!.kind == "budget", "activation-terminal-typed-failure.platform_failure.detail_items.0.kind");
    check(Object.keys(value.platformFailure!.detailItems[0]!.fields).length == 1, "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.count");
    check(value.platformFailure!.detailItems[0]!.fields["resource"]! == "buffer-bytes", "activation-terminal-typed-failure.platform_failure.detail_items.0.fields.0");
    check(value.finalConsumption !== undefined, "activation-terminal-typed-failure.final_consumption.presence");
    check(value.finalConsumption!.cpuFuel == 0n, "activation-terminal-typed-failure.final_consumption.cpu_fuel");
    check(value.finalConsumption!.peakMemoryBytes == 18446744073709551615n, "activation-terminal-typed-failure.final_consumption.peak_memory_bytes");
    check(value.finalConsumption!.wallTimeMicros == 0n, "activation-terminal-typed-failure.final_consumption.wall_time_micros");
    check(value.finalConsumption!.childCalls == 0, "activation-terminal-typed-failure.final_consumption.child_calls");
    check(value.finalConsumption!.outboundRequests == 0, "activation-terminal-typed-failure.final_consumption.outbound_requests");
    check(value.finalConsumption!.stateReadBytes == 0n, "activation-terminal-typed-failure.final_consumption.state_read_bytes");
    check(value.finalConsumption!.stateWriteBytes == 0n, "activation-terminal-typed-failure.final_consumption.state_write_bytes");
    check(value.finalConsumption!.blobReadBytes == 0n, "activation-terminal-typed-failure.final_consumption.blob_read_bytes");
    check(value.finalConsumption!.blobWriteBytes == 0n, "activation-terminal-typed-failure.final_consumption.blob_write_bytes");
    check(value.finalConsumption!.logBytes == 0n, "activation-terminal-typed-failure.final_consumption.log_bytes");
    check(value.finalConsumption!.effectCount == 0, "activation-terminal-typed-failure.final_consumption.effect_count");
    check(value.terminalAtUnixMillis !== undefined, "activation-terminal-typed-failure.terminal_at_unix_millis.presence");
    check(value.terminalAtUnixMillis! == 0n, "activation-terminal-typed-failure.terminal_at_unix_millis");
}
{
    const value: Profile.ActivationStatus = {activationId: "activation-a", phase: "terminal", terminalState: "completed", lastUpdatedUnixMillis: 0n, metadata: {}, succeeded: {committedStateVersion: "state-a", effectIds: ["effect-a"], metadata: {"retained": "true"}}, finalConsumption: {cpuFuel: 0n, peakMemoryBytes: 0n, wallTimeMicros: 0n, childCalls: 0, outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 4294967295}, terminalAtUnixMillis: 18446744073709551615n};
    check(value.activationId == "activation-a", "activation-terminal-success-summary.activation_id");
    check(value.phase == "terminal", "activation-terminal-success-summary.phase");
    check(value.terminalState !== undefined, "activation-terminal-success-summary.terminal_state.presence");
    check(value.terminalState! == "completed", "activation-terminal-success-summary.terminal_state");
    check(value.lastUpdatedUnixMillis == 0n, "activation-terminal-success-summary.last_updated_unix_millis");
    check(Object.keys(value.metadata).length == 0, "activation-terminal-success-summary.metadata.count");
    check(value.succeeded !== undefined, "activation-terminal-success-summary.succeeded.presence");
    check(value.succeeded!.committedStateVersion !== undefined, "activation-terminal-success-summary.succeeded.committed_state_version.presence");
    check(value.succeeded!.committedStateVersion! == "state-a", "activation-terminal-success-summary.succeeded.committed_state_version");
    check(value.succeeded!.effectIds.length == 1, "activation-terminal-success-summary.succeeded.effect_ids.count");
    check(value.succeeded!.effectIds[0]! == "effect-a", "activation-terminal-success-summary.succeeded.effect_ids.0");
    check(Object.keys(value.succeeded!.metadata).length == 1, "activation-terminal-success-summary.succeeded.metadata.count");
    check(value.succeeded!.metadata["retained"]! == "true", "activation-terminal-success-summary.succeeded.metadata.0");
    check(!(value.declaredError !== undefined), "activation-terminal-success-summary.declared_error.presence");
    check(!(value.platformFailure !== undefined), "activation-terminal-success-summary.platform_failure.presence");
    check(value.finalConsumption !== undefined, "activation-terminal-success-summary.final_consumption.presence");
    check(value.finalConsumption!.cpuFuel == 0n, "activation-terminal-success-summary.final_consumption.cpu_fuel");
    check(value.finalConsumption!.peakMemoryBytes == 0n, "activation-terminal-success-summary.final_consumption.peak_memory_bytes");
    check(value.finalConsumption!.wallTimeMicros == 0n, "activation-terminal-success-summary.final_consumption.wall_time_micros");
    check(value.finalConsumption!.childCalls == 0, "activation-terminal-success-summary.final_consumption.child_calls");
    check(value.finalConsumption!.outboundRequests == 0, "activation-terminal-success-summary.final_consumption.outbound_requests");
    check(value.finalConsumption!.stateReadBytes == 0n, "activation-terminal-success-summary.final_consumption.state_read_bytes");
    check(value.finalConsumption!.stateWriteBytes == 0n, "activation-terminal-success-summary.final_consumption.state_write_bytes");
    check(value.finalConsumption!.blobReadBytes == 0n, "activation-terminal-success-summary.final_consumption.blob_read_bytes");
    check(value.finalConsumption!.blobWriteBytes == 0n, "activation-terminal-success-summary.final_consumption.blob_write_bytes");
    check(value.finalConsumption!.logBytes == 0n, "activation-terminal-success-summary.final_consumption.log_bytes");
    check(value.finalConsumption!.effectCount == 4294967295, "activation-terminal-success-summary.final_consumption.effect_count");
    check(value.terminalAtUnixMillis !== undefined, "activation-terminal-success-summary.terminal_at_unix_millis.presence");
    check(value.terminalAtUnixMillis! == 18446744073709551615n, "activation-terminal-success-summary.terminal_at_unix_millis");
}
{
    const value: Profile.GetPolicyResponse = {};
    check(!(value.policy !== undefined), "policy-absence.policy.presence");
}
{
    const value: Profile.GetPolicyRequest = {id: "policy-a", recordKind: 1};
    check(value.id == "policy-a", "policy-record-kind.id");
    check(value.recordKind == 1, "policy-record-kind.record_kind");
}
{
    const value: Profile.GetPolicyRequest = {id: "binding-a", recordKind: 2};
    check(value.id == "binding-a", "provider-binding-record-kind.id");
    check(value.recordKind == 2, "provider-binding-record-kind.record_kind");
}
{
    const value: Profile.Policy = {id: "future-record", metadata: {name: "future-record", tenant: "", namespace: "", labels: {"sampled": "true"}, annotations: {"descriptive": "not-authority"}}, document: "", generation: 18446744073709551615n, language: "", recordKind: 2147483647, contentDigest: "", revoked: true};
    check(value.id == "future-record", "unknown-policy-kind.id");
    check(value.metadata !== undefined, "unknown-policy-kind.metadata.presence");
    check(value.metadata!.name == "future-record", "unknown-policy-kind.metadata.name");
    check(value.metadata!.tenant !== undefined, "unknown-policy-kind.metadata.tenant.presence");
    check(value.metadata!.tenant! == "", "unknown-policy-kind.metadata.tenant");
    check(value.metadata!.namespace !== undefined, "unknown-policy-kind.metadata.namespace.presence");
    check(value.metadata!.namespace! == "", "unknown-policy-kind.metadata.namespace");
    check(Object.keys(value.metadata!.labels).length == 1, "unknown-policy-kind.metadata.labels.count");
    check(value.metadata!.labels["sampled"]! == "true", "unknown-policy-kind.metadata.labels.0");
    check(Object.keys(value.metadata!.annotations).length == 1, "unknown-policy-kind.metadata.annotations.count");
    check(value.metadata!.annotations["descriptive"]! == "not-authority", "unknown-policy-kind.metadata.annotations.0");
    check(value.document == "", "unknown-policy-kind.document");
    check(value.generation == 18446744073709551615n, "unknown-policy-kind.generation");
    check(value.language == "", "unknown-policy-kind.language");
    check(value.recordKind == 2147483647, "unknown-policy-kind.record_kind");
    check(value.contentDigest == "", "unknown-policy-kind.content_digest");
    check(value.revoked == true, "unknown-policy-kind.revoked");
}
{
    const value: Profile.ApplyPolicyRequest = {operationId: "operation-a"};
    check(!(value.policy !== undefined), "apply-missing-generation.policy.presence");
    check(!(value.expectedGeneration !== undefined), "apply-missing-generation.expected_generation.presence");
    check(value.operationId == "operation-a", "apply-missing-generation.operation_id");
}
{
    const value: Profile.ApplyPolicyRequest = {expectedGeneration: 0n, operationId: ""};
    check(!(value.policy !== undefined), "apply-present-empty-operation.policy.presence");
    check(value.expectedGeneration !== undefined, "apply-present-empty-operation.expected_generation.presence");
    check(value.expectedGeneration! == 0n, "apply-present-empty-operation.expected_generation");
    check(value.operationId == "", "apply-present-empty-operation.operation_id");
}
{
    const value: Profile.ApplyPolicyRequest = {policy: {id: "policy-a", metadata: {name: "policy-a", tenant: "tenant-a", labels: {}, annotations: {}}, document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", generation: 0n, language: "lsf-capability-policy-v1", recordKind: 1, contentDigest: "", revoked: false}, expectedGeneration: 0n, operationId: "operation-a"};
    check(value.policy !== undefined, "apply-create-policy-zero-generation.policy.presence");
    check(value.policy!.id == "policy-a", "apply-create-policy-zero-generation.policy.id");
    check(value.policy!.metadata !== undefined, "apply-create-policy-zero-generation.policy.metadata.presence");
    check(value.policy!.metadata!.name == "policy-a", "apply-create-policy-zero-generation.policy.metadata.name");
    check(value.policy!.metadata!.tenant !== undefined, "apply-create-policy-zero-generation.policy.metadata.tenant.presence");
    check(value.policy!.metadata!.tenant! == "tenant-a", "apply-create-policy-zero-generation.policy.metadata.tenant");
    check(!(value.policy!.metadata!.namespace !== undefined), "apply-create-policy-zero-generation.policy.metadata.namespace.presence");
    check(Object.keys(value.policy!.metadata!.labels).length == 0, "apply-create-policy-zero-generation.policy.metadata.labels.count");
    check(Object.keys(value.policy!.metadata!.annotations).length == 0, "apply-create-policy-zero-generation.policy.metadata.annotations.count");
    check(value.policy!.document == "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"rules\":[{\"id\":\"deny\",\"effect\":\"deny\",\"principals\":[{\"kind\":\"user\",\"subject\":\"fixture-user\"}],\"services\":[\"echo\"],\"publications\":[\"publication:sha256:1111111111111111111111111111111111111111111111111111111111111111\"],\"capability\":\"latent:secrets/reader@0.1.0\",\"operations\":[\"read\"],\"resources\":{\"kind\":\"secrets\",\"references\":[\"fixture-selector\"]},\"ceiling\":{\"operations\":0,\"inputBytes\":0,\"outputBytes\":0,\"wallTimeMillis\":0}}]}", "apply-create-policy-zero-generation.policy.document");
    check(value.policy!.generation == 0n, "apply-create-policy-zero-generation.policy.generation");
    check(value.policy!.language == "lsf-capability-policy-v1", "apply-create-policy-zero-generation.policy.language");
    check(value.policy!.recordKind == 1, "apply-create-policy-zero-generation.policy.record_kind");
    check(value.policy!.contentDigest == "", "apply-create-policy-zero-generation.policy.content_digest");
    check(value.policy!.revoked == false, "apply-create-policy-zero-generation.policy.revoked");
    check(value.expectedGeneration !== undefined, "apply-create-policy-zero-generation.expected_generation.presence");
    check(value.expectedGeneration! == 0n, "apply-create-policy-zero-generation.expected_generation");
    check(value.operationId == "operation-a", "apply-create-policy-zero-generation.operation_id");
}
{
    const value: Profile.ApplyPolicyRequest = {policy: {id: "binding-a", metadata: {name: "binding-a", tenant: "tenant-a", labels: {}, annotations: {}}, document: "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", generation: 0n, language: "lsf-provider-binding-v1", recordKind: 2, contentDigest: "", revoked: false}, expectedGeneration: 18446744073709551615n, operationId: "operation-binding"};
    check(value.policy !== undefined, "apply-binding-max-precondition-and-opaque-limit-document.policy.presence");
    check(value.policy!.id == "binding-a", "apply-binding-max-precondition-and-opaque-limit-document.policy.id");
    check(value.policy!.metadata !== undefined, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.presence");
    check(value.policy!.metadata!.name == "binding-a", "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.name");
    check(value.policy!.metadata!.tenant !== undefined, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant.presence");
    check(value.policy!.metadata!.tenant! == "tenant-a", "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.tenant");
    check(!(value.policy!.metadata!.namespace !== undefined), "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.namespace.presence");
    check(Object.keys(value.policy!.metadata!.labels).length == 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.labels.count");
    check(Object.keys(value.policy!.metadata!.annotations).length == 0, "apply-binding-max-precondition-and-opaque-limit-document.policy.metadata.annotations.count");
    check(value.policy!.document == "{\"formatVersion\":1,\"tenant\":\"tenant-a\",\"capability\":\"latent:secrets/reader@0.1.0\",\"providerProfile\":\"local-secrets-v1\",\"configurationDigest\":\"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\",\"configurationEpoch\":18446744073709551615,\"restriction\":{\"operations\":[],\"ceiling\":{\"operations\":0,\"inputBytes\":18446744073709551615,\"outputBytes\":0,\"wallTimeMillis\":0}}}", "apply-binding-max-precondition-and-opaque-limit-document.policy.document");
    check(value.policy!.generation == 0n, "apply-binding-max-precondition-and-opaque-limit-document.policy.generation");
    check(value.policy!.language == "lsf-provider-binding-v1", "apply-binding-max-precondition-and-opaque-limit-document.policy.language");
    check(value.policy!.recordKind == 2, "apply-binding-max-precondition-and-opaque-limit-document.policy.record_kind");
    check(value.policy!.contentDigest == "", "apply-binding-max-precondition-and-opaque-limit-document.policy.content_digest");
    check(value.policy!.revoked == false, "apply-binding-max-precondition-and-opaque-limit-document.policy.revoked");
    check(value.expectedGeneration !== undefined, "apply-binding-max-precondition-and-opaque-limit-document.expected_generation.presence");
    check(value.expectedGeneration! == 18446744073709551615n, "apply-binding-max-precondition-and-opaque-limit-document.expected_generation");
    check(value.operationId == "operation-binding", "apply-binding-max-precondition-and-opaque-limit-document.operation_id");
}
{
    const value: Profile.ListPoliciesRequest = {recordKind: 1};
    check(value.recordKind == 1, "policy-page-absent.record_kind");
    check(!(value.page !== undefined), "policy-page-absent.page.presence");
}
{
    const value: Profile.ListPoliciesRequest = {recordKind: 2, page: {pageSize: 0}};
    check(value.recordKind == 2, "policy-page-zero-invalid.record_kind");
    check(value.page !== undefined, "policy-page-zero-invalid.page.presence");
    check(value.page!.pageSize == 0, "policy-page-zero-invalid.page.page_size");
    check(!(value.page!.pageToken !== undefined), "policy-page-zero-invalid.page.page_token.presence");
}
{
    const value: Profile.ListPoliciesRequest = {recordKind: 1, page: {pageSize: 1, pageToken: ""}};
    check(value.recordKind == 1, "policy-page-empty-token-invalid.record_kind");
    check(value.page !== undefined, "policy-page-empty-token-invalid.page.presence");
    check(value.page!.pageSize == 1, "policy-page-empty-token-invalid.page.page_size");
    check(value.page!.pageToken !== undefined, "policy-page-empty-token-invalid.page.page_token.presence");
    check(value.page!.pageToken! == "", "policy-page-empty-token-invalid.page.page_token");
}
{
    const value: Profile.ListPoliciesResponse = {policies: [{id: "policy-a", document: "", generation: 18446744073709551615n, language: "", recordKind: 1, contentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", revoked: true}], catalogGeneration: 18446744073709551615n, page: {nextPageToken: "opaque-policy-cursor"}};
    check(value.policies.length == 1, "policy-page-first.policies.count");
    check(value.policies[0]!.id == "policy-a", "policy-page-first.policies.0.id");
    check(!(value.policies[0]!.metadata !== undefined), "policy-page-first.policies.0.metadata.presence");
    check(value.policies[0]!.document == "", "policy-page-first.policies.0.document");
    check(value.policies[0]!.generation == 18446744073709551615n, "policy-page-first.policies.0.generation");
    check(value.policies[0]!.language == "", "policy-page-first.policies.0.language");
    check(value.policies[0]!.recordKind == 1, "policy-page-first.policies.0.record_kind");
    check(value.policies[0]!.contentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "policy-page-first.policies.0.content_digest");
    check(value.policies[0]!.revoked == true, "policy-page-first.policies.0.revoked");
    check(value.catalogGeneration == 18446744073709551615n, "policy-page-first.catalog_generation");
    check(value.page !== undefined, "policy-page-first.page.presence");
    check(value.page!.nextPageToken !== undefined, "policy-page-first.page.next_page_token.presence");
    check(value.page!.nextPageToken! == "opaque-policy-cursor", "policy-page-first.page.next_page_token");
}
{
    const value: Profile.ListPoliciesResponse = {policies: [], catalogGeneration: 18446744073709551615n, page: {}};
    check(value.policies.length == 0, "policy-page-last.policies.count");
    check(value.catalogGeneration == 18446744073709551615n, "policy-page-last.catalog_generation");
    check(value.page !== undefined, "policy-page-last.page.presence");
    check(!(value.page!.nextPageToken !== undefined), "policy-page-last.page.next_page_token.presence");
}
{
    const value: Profile.ListPoliciesRequest = {recordKind: 1, page: {pageSize: 1, pageToken: "opaque-policy-cursor"}};
    check(value.recordKind == 1, "policy-next-page-request.record_kind");
    check(value.page !== undefined, "policy-next-page-request.page.presence");
    check(value.page!.pageSize == 1, "policy-next-page-request.page.page_size");
    check(value.page!.pageToken !== undefined, "policy-next-page-request.page.page_token.presence");
    check(value.page!.pageToken! == "opaque-policy-cursor", "policy-next-page-request.page.page_token");
}
{
    const value: Profile.ApplyPolicyResponse = {policy: {id: "policy-a", document: "", generation: 18446744073709551615n, language: "", recordKind: 1, contentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", revoked: false}, receipt: {operationId: "operation-a", tenant: "tenant-a", id: "policy-a", recordKind: 1, generation: 18446744073709551615n, contentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", revoked: false}};
    check(value.policy !== undefined, "apply-retains-original-receipt.policy.presence");
    check(value.policy!.id == "policy-a", "apply-retains-original-receipt.policy.id");
    check(!(value.policy!.metadata !== undefined), "apply-retains-original-receipt.policy.metadata.presence");
    check(value.policy!.document == "", "apply-retains-original-receipt.policy.document");
    check(value.policy!.generation == 18446744073709551615n, "apply-retains-original-receipt.policy.generation");
    check(value.policy!.language == "", "apply-retains-original-receipt.policy.language");
    check(value.policy!.recordKind == 1, "apply-retains-original-receipt.policy.record_kind");
    check(value.policy!.contentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "apply-retains-original-receipt.policy.content_digest");
    check(value.policy!.revoked == false, "apply-retains-original-receipt.policy.revoked");
    check(value.receipt !== undefined, "apply-retains-original-receipt.receipt.presence");
    check(value.receipt!.operationId == "operation-a", "apply-retains-original-receipt.receipt.operation_id");
    check(value.receipt!.tenant == "tenant-a", "apply-retains-original-receipt.receipt.tenant");
    check(value.receipt!.id == "policy-a", "apply-retains-original-receipt.receipt.id");
    check(value.receipt!.recordKind == 1, "apply-retains-original-receipt.receipt.record_kind");
    check(value.receipt!.generation == 18446744073709551615n, "apply-retains-original-receipt.receipt.generation");
    check(value.receipt!.contentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "apply-retains-original-receipt.receipt.content_digest");
    check(value.receipt!.revoked == false, "apply-retains-original-receipt.receipt.revoked");
}
{
    const value: Profile.GetPolicyOperationRequest = {operationId: "operation-a"};
    check(value.operationId == "operation-a", "get-policy-operation-known-id.operation_id");
}
{
    const value: Profile.GetPolicyOperationResponse = {};
    check(!(value.receipt !== undefined), "operation-recovery-not-retained-is-unknown.receipt.presence");
}
{
    const value: Profile.GetPolicyOperationResponse = {receipt: {operationId: "operation-a", tenant: "tenant-a", id: "policy-a", recordKind: 1, generation: 18446744073709551615n, contentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", revoked: false}};
    check(value.receipt !== undefined, "operation-recovery-original-receipt.receipt.presence");
    check(value.receipt!.operationId == "operation-a", "operation-recovery-original-receipt.receipt.operation_id");
    check(value.receipt!.tenant == "tenant-a", "operation-recovery-original-receipt.receipt.tenant");
    check(value.receipt!.id == "policy-a", "operation-recovery-original-receipt.receipt.id");
    check(value.receipt!.recordKind == 1, "operation-recovery-original-receipt.receipt.record_kind");
    check(value.receipt!.generation == 18446744073709551615n, "operation-recovery-original-receipt.receipt.generation");
    check(value.receipt!.contentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "operation-recovery-original-receipt.receipt.content_digest");
    check(value.receipt!.revoked == false, "operation-recovery-original-receipt.receipt.revoked");
}
{
    const value: Profile.ListCapabilitiesRequest = {deploymentId: "deployment-a", includeNodeUsage: false};
    check(!(value.contractPrefix !== undefined), "capabilities-absent-page-default.contract_prefix.presence");
    check(!(value.provider !== undefined), "capabilities-absent-page-default.provider.presence");
    check(!(value.page !== undefined), "capabilities-absent-page-default.page.presence");
    check(value.deploymentId == "deployment-a", "capabilities-absent-page-default.deployment_id");
    check(value.includeNodeUsage == false, "capabilities-absent-page-default.include_node_usage");
}
{
    const value: Profile.ListCapabilitiesRequest = {page: {pageSize: 0}, deploymentId: "deployment-a", includeNodeUsage: false};
    check(!(value.contractPrefix !== undefined), "capabilities-zero-page-default.contract_prefix.presence");
    check(!(value.provider !== undefined), "capabilities-zero-page-default.provider.presence");
    check(value.page !== undefined, "capabilities-zero-page-default.page.presence");
    check(value.page!.pageSize == 0, "capabilities-zero-page-default.page.page_size");
    check(!(value.page!.pageToken !== undefined), "capabilities-zero-page-default.page.page_token.presence");
    check(value.deploymentId == "deployment-a", "capabilities-zero-page-default.deployment_id");
    check(value.includeNodeUsage == false, "capabilities-zero-page-default.include_node_usage");
}
{
    const value: Profile.ListCapabilitiesRequest = {contractPrefix: "", provider: "", page: {pageSize: 128}, deploymentId: "deployment-a", includeNodeUsage: true};
    check(value.contractPrefix !== undefined, "capabilities-present-empty-filters.contract_prefix.presence");
    check(value.contractPrefix! == "", "capabilities-present-empty-filters.contract_prefix");
    check(value.provider !== undefined, "capabilities-present-empty-filters.provider.presence");
    check(value.provider! == "", "capabilities-present-empty-filters.provider");
    check(value.page !== undefined, "capabilities-present-empty-filters.page.presence");
    check(value.page!.pageSize == 128, "capabilities-present-empty-filters.page.page_size");
    check(!(value.page!.pageToken !== undefined), "capabilities-present-empty-filters.page.page_token.presence");
    check(value.deploymentId == "deployment-a", "capabilities-present-empty-filters.deployment_id");
    check(value.includeNodeUsage == true, "capabilities-present-empty-filters.include_node_usage");
}
{
    const value: Profile.ListCapabilitiesRequest = {page: {pageSize: 1}, deploymentId: "", includeNodeUsage: false};
    check(!(value.contractPrefix !== undefined), "capabilities-explicit-deployment-required.contract_prefix.presence");
    check(!(value.provider !== undefined), "capabilities-explicit-deployment-required.provider.presence");
    check(value.page !== undefined, "capabilities-explicit-deployment-required.page.presence");
    check(value.page!.pageSize == 1, "capabilities-explicit-deployment-required.page.page_size");
    check(!(value.page!.pageToken !== undefined), "capabilities-explicit-deployment-required.page.page_token.presence");
    check(value.deploymentId == "", "capabilities-explicit-deployment-required.deployment_id");
    check(value.includeNodeUsage == false, "capabilities-explicit-deployment-required.include_node_usage");
}
{
    const value: Profile.ListCapabilitiesRequest = {page: {pageSize: 4294967295}, deploymentId: "deployment-a", includeNodeUsage: false};
    check(!(value.contractPrefix !== undefined), "capabilities-page-too-large.contract_prefix.presence");
    check(!(value.provider !== undefined), "capabilities-page-too-large.provider.presence");
    check(value.page !== undefined, "capabilities-page-too-large.page.presence");
    check(value.page!.pageSize == 4294967295, "capabilities-page-too-large.page.page_size");
    check(!(value.page!.pageToken !== undefined), "capabilities-page-too-large.page.page_token.presence");
    check(value.deploymentId == "deployment-a", "capabilities-page-too-large.deployment_id");
    check(value.includeNodeUsage == false, "capabilities-page-too-large.include_node_usage");
}
{
    const value: Profile.ListCapabilitiesResponse = {capabilities: [{id: "latent:secrets/reader@0.1.0", contract: "latent:secrets/reader@0.1.0", provider: "local-secrets-v1", operations: ["read"], attributes: {}, inspection: {definitionDigest: "", providerBinding: {id: "binding-a", revision: 18446744073709551615n, digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}, policies: [{id: "policy-a", revision: 9223372036854775808n, digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}], providerProfile: "local-secrets-v1", providerConfigurationDigest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", providerConfigurationEpoch: 18446744073709551615n, state: "provider-configuration-changed"}}, {id: "future-capability", contract: "future-contract", provider: "future-provider", operations: [], attributes: {"descriptive": "not-authority"}}], page: {nextPageToken: "opaque-capability-cursor"}, revision: {deploymentId: "deployment-a", revisionId: "revision-a", componentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", publicationId: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", routeGeneration: 18446744073709551615n, catalogTransaction: 9223372036854775808n}, tenantUsage: {scope: "tenant", counters: {"sessions": 18446744073709551615n, "calls": 0n}, unavailable: ["fixture-owner-unavailable"]}, state: "sampled"};
    check(value.capabilities.length == 2, "redacted-capability-provider-inspection.capabilities.count");
    check(value.capabilities[0]!.id == "latent:secrets/reader@0.1.0", "redacted-capability-provider-inspection.capabilities.0.id");
    check(value.capabilities[0]!.contract == "latent:secrets/reader@0.1.0", "redacted-capability-provider-inspection.capabilities.0.contract");
    check(value.capabilities[0]!.provider == "local-secrets-v1", "redacted-capability-provider-inspection.capabilities.0.provider");
    check(value.capabilities[0]!.operations.length == 1, "redacted-capability-provider-inspection.capabilities.0.operations.count");
    check(value.capabilities[0]!.operations[0]! == "read", "redacted-capability-provider-inspection.capabilities.0.operations.0");
    check(Object.keys(value.capabilities[0]!.attributes).length == 0, "redacted-capability-provider-inspection.capabilities.0.attributes.count");
    check(value.capabilities[0]!.inspection !== undefined, "redacted-capability-provider-inspection.capabilities.0.inspection.presence");
    check(value.capabilities[0]!.inspection!.definitionDigest !== undefined, "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest.presence");
    check(value.capabilities[0]!.inspection!.definitionDigest! == "", "redacted-capability-provider-inspection.capabilities.0.inspection.definition_digest");
    check(value.capabilities[0]!.inspection!.providerBinding !== undefined, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.presence");
    check(value.capabilities[0]!.inspection!.providerBinding!.id == "binding-a", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.id");
    check(value.capabilities[0]!.inspection!.providerBinding!.revision == 18446744073709551615n, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.revision");
    check(value.capabilities[0]!.inspection!.providerBinding!.digest == "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_binding.digest");
    check(value.capabilities[0]!.inspection!.policies.length == 1, "redacted-capability-provider-inspection.capabilities.0.inspection.policies.count");
    check(value.capabilities[0]!.inspection!.policies[0]!.id == "policy-a", "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.id");
    check(value.capabilities[0]!.inspection!.policies[0]!.revision == 9223372036854775808n, "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.revision");
    check(value.capabilities[0]!.inspection!.policies[0]!.digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "redacted-capability-provider-inspection.capabilities.0.inspection.policies.0.digest");
    check(value.capabilities[0]!.inspection!.providerProfile == "local-secrets-v1", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_profile");
    check(value.capabilities[0]!.inspection!.providerConfigurationDigest == "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_digest");
    check(value.capabilities[0]!.inspection!.providerConfigurationEpoch == 18446744073709551615n, "redacted-capability-provider-inspection.capabilities.0.inspection.provider_configuration_epoch");
    check(value.capabilities[0]!.inspection!.state == "provider-configuration-changed", "redacted-capability-provider-inspection.capabilities.0.inspection.state");
    check(value.capabilities[1]!.id == "future-capability", "redacted-capability-provider-inspection.capabilities.1.id");
    check(value.capabilities[1]!.contract == "future-contract", "redacted-capability-provider-inspection.capabilities.1.contract");
    check(value.capabilities[1]!.provider == "future-provider", "redacted-capability-provider-inspection.capabilities.1.provider");
    check(value.capabilities[1]!.operations.length == 0, "redacted-capability-provider-inspection.capabilities.1.operations.count");
    check(Object.keys(value.capabilities[1]!.attributes).length == 1, "redacted-capability-provider-inspection.capabilities.1.attributes.count");
    check(value.capabilities[1]!.attributes["descriptive"]! == "not-authority", "redacted-capability-provider-inspection.capabilities.1.attributes.0");
    check(!(value.capabilities[1]!.inspection !== undefined), "redacted-capability-provider-inspection.capabilities.1.inspection.presence");
    check(value.page !== undefined, "redacted-capability-provider-inspection.page.presence");
    check(value.page!.nextPageToken !== undefined, "redacted-capability-provider-inspection.page.next_page_token.presence");
    check(value.page!.nextPageToken! == "opaque-capability-cursor", "redacted-capability-provider-inspection.page.next_page_token");
    check(value.revision !== undefined, "redacted-capability-provider-inspection.revision.presence");
    check(value.revision!.deploymentId == "deployment-a", "redacted-capability-provider-inspection.revision.deployment_id");
    check(value.revision!.revisionId == "revision-a", "redacted-capability-provider-inspection.revision.revision_id");
    check(value.revision!.componentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "redacted-capability-provider-inspection.revision.component_digest");
    check(value.revision!.publicationId !== undefined, "redacted-capability-provider-inspection.revision.publication_id.presence");
    check(value.revision!.publicationId! == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "redacted-capability-provider-inspection.revision.publication_id");
    check(value.revision!.routeGeneration == 18446744073709551615n, "redacted-capability-provider-inspection.revision.route_generation");
    check(value.revision!.catalogTransaction == 9223372036854775808n, "redacted-capability-provider-inspection.revision.catalog_transaction");
    check(value.tenantUsage !== undefined, "redacted-capability-provider-inspection.tenant_usage.presence");
    check(value.tenantUsage!.scope == "tenant", "redacted-capability-provider-inspection.tenant_usage.scope");
    check(Object.keys(value.tenantUsage!.counters).length == 2, "redacted-capability-provider-inspection.tenant_usage.counters.count");
    check(value.tenantUsage!.counters["sessions"]! == 18446744073709551615n, "redacted-capability-provider-inspection.tenant_usage.counters.0");
    check(value.tenantUsage!.counters["calls"]! == 0n, "redacted-capability-provider-inspection.tenant_usage.counters.1");
    check(value.tenantUsage!.unavailable.length == 1, "redacted-capability-provider-inspection.tenant_usage.unavailable.count");
    check(value.tenantUsage!.unavailable[0]! == "fixture-owner-unavailable", "redacted-capability-provider-inspection.tenant_usage.unavailable.0");
    check(!(value.nodeUsage !== undefined), "redacted-capability-provider-inspection.node_usage.presence");
    check(value.state == "sampled", "redacted-capability-provider-inspection.state");
}
{
    const value: Profile.ListCapabilitiesResponse = {capabilities: [], nodeUsage: {scope: "node", counters: {}, unavailable: ["provider-pools-no-retained-owner", "audit-owner-not-configured"]}, state: "binding-plan-unavailable"};
    check(value.capabilities.length == 0, "missing-provider-plan-not-zero-usage.capabilities.count");
    check(!(value.page !== undefined), "missing-provider-plan-not-zero-usage.page.presence");
    check(!(value.revision !== undefined), "missing-provider-plan-not-zero-usage.revision.presence");
    check(!(value.tenantUsage !== undefined), "missing-provider-plan-not-zero-usage.tenant_usage.presence");
    check(value.nodeUsage !== undefined, "missing-provider-plan-not-zero-usage.node_usage.presence");
    check(value.nodeUsage!.scope == "node", "missing-provider-plan-not-zero-usage.node_usage.scope");
    check(Object.keys(value.nodeUsage!.counters).length == 0, "missing-provider-plan-not-zero-usage.node_usage.counters.count");
    check(value.nodeUsage!.unavailable.length == 2, "missing-provider-plan-not-zero-usage.node_usage.unavailable.count");
    check(value.nodeUsage!.unavailable[0]! == "provider-pools-no-retained-owner", "missing-provider-plan-not-zero-usage.node_usage.unavailable.0");
    check(value.nodeUsage!.unavailable[1]! == "audit-owner-not-configured", "missing-provider-plan-not-zero-usage.node_usage.unavailable.1");
    check(value.state == "binding-plan-unavailable", "missing-provider-plan-not-zero-usage.state");
}
{
    const value: Profile.CapabilityInspectionCeiling = {operations: 0, inputBytes: 18446744073709551615n, outputBytes: 0n, wallTimeMillis: 18446744073709551615n};
    check(value.operations == 0, "typed-ceiling-zero-and-max-not-grant.operations");
    check(value.inputBytes == 18446744073709551615n, "typed-ceiling-zero-and-max-not-grant.input_bytes");
    check(value.outputBytes == 0n, "typed-ceiling-zero-and-max-not-grant.output_bytes");
    check(value.wallTimeMillis == 18446744073709551615n, "typed-ceiling-zero-and-max-not-grant.wall_time_millis");
}
{
    const value: Profile.CallOptions = {};
    check(!(value.timeoutMillis !== undefined), "local-timeout-absent.timeout_millis.presence");
}
{
    const value: Profile.CallOptions = {timeoutMillis: 0n};
    check(value.timeoutMillis !== undefined, "local-timeout-zero.timeout_millis.presence");
    check(value.timeoutMillis! == 0n, "local-timeout-zero.timeout_millis");
}
{
    const value: Profile.CallOptions = {timeoutMillis: 18446744073709551615n};
    check(value.timeoutMillis !== undefined, "local-timeout-max-not-wrapped.timeout_millis.presence");
    check(value.timeoutMillis! == 18446744073709551615n, "local-timeout-max-not-wrapped.timeout_millis");
}
{
    const value: Profile.ClientFailure = {category: 1, message: "local-cancelled", dispatched: false, outcome: 1, identity: {activationId: "activation-a"}};
    check(value.category == 1, "local-cancel-before-dispatch.category");
    check(value.message == "local-cancelled", "local-cancel-before-dispatch.message");
    check(!(value.grpcStatus !== undefined), "local-cancel-before-dispatch.grpc_status.presence");
    check(!(value.platformError !== undefined), "local-cancel-before-dispatch.platform_error.presence");
    check(value.dispatched == false, "local-cancel-before-dispatch.dispatched");
    check(value.outcome == 1, "local-cancel-before-dispatch.outcome");
    check(value.identity.activationId !== undefined, "local-cancel-before-dispatch.identity.activation_id.presence");
    check(value.identity.activationId! == "activation-a", "local-cancel-before-dispatch.identity.activation_id");
    check(!(value.identity.operationId !== undefined), "local-cancel-before-dispatch.identity.operation_id.presence");
    check(!(value.auditAck !== undefined), "local-cancel-before-dispatch.audit_ack.presence");
    check(!(value.auditStatus !== undefined), "local-cancel-before-dispatch.audit_status.presence");
    check(!(value.unsupportedWireValue !== undefined), "local-cancel-before-dispatch.unsupported_wire_value.presence");
    check(!(value.auditAttemptSequence !== undefined), "local-cancel-before-dispatch.audit_attempt_sequence.presence");
}
{
    const value: Profile.ClientFailure = {category: 2, message: "deadline", grpcStatus: 4, dispatched: true, outcome: 2, identity: {operationId: "operation-a"}, auditAck: {status: 2, attemptSequence: 18446744073709551615n}, auditStatus: "outcome-unknown", auditAttemptSequence: 18446744073709551615n};
    check(value.category == 2, "deadline-after-dispatch-is-uncertain.category");
    check(value.message == "deadline", "deadline-after-dispatch-is-uncertain.message");
    check(value.grpcStatus !== undefined, "deadline-after-dispatch-is-uncertain.grpc_status.presence");
    check(value.grpcStatus! == 4, "deadline-after-dispatch-is-uncertain.grpc_status");
    check(!(value.platformError !== undefined), "deadline-after-dispatch-is-uncertain.platform_error.presence");
    check(value.dispatched == true, "deadline-after-dispatch-is-uncertain.dispatched");
    check(value.outcome == 2, "deadline-after-dispatch-is-uncertain.outcome");
    check(!(value.identity.activationId !== undefined), "deadline-after-dispatch-is-uncertain.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "deadline-after-dispatch-is-uncertain.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "deadline-after-dispatch-is-uncertain.identity.operation_id");
    check(value.auditAck !== undefined, "deadline-after-dispatch-is-uncertain.audit_ack.presence");
    check(value.auditAck!.status == 2, "deadline-after-dispatch-is-uncertain.audit_ack.status");
    check(value.auditAck!.attemptSequence !== undefined, "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence.presence");
    check(value.auditAck!.attemptSequence! == 18446744073709551615n, "deadline-after-dispatch-is-uncertain.audit_ack.attempt_sequence");
    check(value.auditStatus !== undefined, "deadline-after-dispatch-is-uncertain.audit_status.presence");
    check(value.auditStatus! == "outcome-unknown", "deadline-after-dispatch-is-uncertain.audit_status");
    check(!(value.unsupportedWireValue !== undefined), "deadline-after-dispatch-is-uncertain.unsupported_wire_value.presence");
    check(value.auditAttemptSequence !== undefined, "deadline-after-dispatch-is-uncertain.audit_attempt_sequence.presence");
    check(value.auditAttemptSequence! == 18446744073709551615n, "deadline-after-dispatch-is-uncertain.audit_attempt_sequence");
}
{
    const value: Profile.ClientFailure = {category: 4, message: "capability-policy-conflict", grpcStatus: 9, platformError: {code: "state-conflict", message: "capability-policy-conflict", retryable: false, detailItems: [{kind: "future-detail", fields: {"value": "retained"}}]}, dispatched: true, outcome: 3, identity: {operationId: "operation-a"}};
    check(value.category == 4, "rpc-conflict-retains-request-identity.category");
    check(value.message == "capability-policy-conflict", "rpc-conflict-retains-request-identity.message");
    check(value.grpcStatus !== undefined, "rpc-conflict-retains-request-identity.grpc_status.presence");
    check(value.grpcStatus! == 9, "rpc-conflict-retains-request-identity.grpc_status");
    check(value.platformError !== undefined, "rpc-conflict-retains-request-identity.platform_error.presence");
    check(value.platformError!.code == "state-conflict", "rpc-conflict-retains-request-identity.platform_error.code");
    check(value.platformError!.message == "capability-policy-conflict", "rpc-conflict-retains-request-identity.platform_error.message");
    check(value.platformError!.retryable == false, "rpc-conflict-retains-request-identity.platform_error.retryable");
    check(value.platformError!.detailItems.length == 1, "rpc-conflict-retains-request-identity.platform_error.detail_items.count");
    check(value.platformError!.detailItems[0]!.kind == "future-detail", "rpc-conflict-retains-request-identity.platform_error.detail_items.0.kind");
    check(Object.keys(value.platformError!.detailItems[0]!.fields).length == 1, "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.count");
    check(value.platformError!.detailItems[0]!.fields["value"]! == "retained", "rpc-conflict-retains-request-identity.platform_error.detail_items.0.fields.0");
    check(value.dispatched == true, "rpc-conflict-retains-request-identity.dispatched");
    check(value.outcome == 3, "rpc-conflict-retains-request-identity.outcome");
    check(!(value.identity.activationId !== undefined), "rpc-conflict-retains-request-identity.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "rpc-conflict-retains-request-identity.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "rpc-conflict-retains-request-identity.identity.operation_id");
    check(!(value.auditAck !== undefined), "rpc-conflict-retains-request-identity.audit_ack.presence");
    check(!(value.auditStatus !== undefined), "rpc-conflict-retains-request-identity.audit_status.presence");
    check(!(value.unsupportedWireValue !== undefined), "rpc-conflict-retains-request-identity.unsupported_wire_value.presence");
    check(!(value.auditAttemptSequence !== undefined), "rpc-conflict-retains-request-identity.audit_attempt_sequence.presence");
}
{
    const value: Profile.ClientFailure = {category: 5, message: "invalid-response", dispatched: true, outcome: 2, identity: {activationId: "activation-a", operationId: "operation-a"}, unsupportedWireValue: {field: "phase", value: "future-phase-not-authority"}};
    check(value.category == 5, "decode-failure-retains-known-identity.category");
    check(value.message == "invalid-response", "decode-failure-retains-known-identity.message");
    check(!(value.grpcStatus !== undefined), "decode-failure-retains-known-identity.grpc_status.presence");
    check(!(value.platformError !== undefined), "decode-failure-retains-known-identity.platform_error.presence");
    check(value.dispatched == true, "decode-failure-retains-known-identity.dispatched");
    check(value.outcome == 2, "decode-failure-retains-known-identity.outcome");
    check(value.identity.activationId !== undefined, "decode-failure-retains-known-identity.identity.activation_id.presence");
    check(value.identity.activationId! == "activation-a", "decode-failure-retains-known-identity.identity.activation_id");
    check(value.identity.operationId !== undefined, "decode-failure-retains-known-identity.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "decode-failure-retains-known-identity.identity.operation_id");
    check(!(value.auditAck !== undefined), "decode-failure-retains-known-identity.audit_ack.presence");
    check(!(value.auditStatus !== undefined), "decode-failure-retains-known-identity.audit_status.presence");
    check(value.unsupportedWireValue !== undefined, "decode-failure-retains-known-identity.unsupported_wire_value.presence");
    check(value.unsupportedWireValue!.field == "phase", "decode-failure-retains-known-identity.unsupported_wire_value.field");
    check(value.unsupportedWireValue!.value == "future-phase-not-authority", "decode-failure-retains-known-identity.unsupported_wire_value.value");
    check(!(value.auditAttemptSequence !== undefined), "decode-failure-retains-known-identity.audit_attempt_sequence.presence");
}
{
    const value: Profile.ResponseMetadata = {identity: {operationId: "operation-a"}, outcome: 3, auditAck: {status: 2, attemptSequence: 18446744073709551615n}, auditStatus: "outcome-unknown", auditAttemptSequence: 18446744073709551615n};
    check(!(value.identity.activationId !== undefined), "observed-receipt-audit-outcome-independent.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "observed-receipt-audit-outcome-independent.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "observed-receipt-audit-outcome-independent.identity.operation_id");
    check(value.outcome == 3, "observed-receipt-audit-outcome-independent.outcome");
    check(value.auditAck !== undefined, "observed-receipt-audit-outcome-independent.audit_ack.presence");
    check(value.auditAck!.status == 2, "observed-receipt-audit-outcome-independent.audit_ack.status");
    check(value.auditAck!.attemptSequence !== undefined, "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence.presence");
    check(value.auditAck!.attemptSequence! == 18446744073709551615n, "observed-receipt-audit-outcome-independent.audit_ack.attempt_sequence");
    check(value.auditStatus !== undefined, "observed-receipt-audit-outcome-independent.audit_status.presence");
    check(value.auditStatus! == "outcome-unknown", "observed-receipt-audit-outcome-independent.audit_status");
    check(value.auditAttemptSequence !== undefined, "observed-receipt-audit-outcome-independent.audit_attempt_sequence.presence");
    check(value.auditAttemptSequence! == 18446744073709551615n, "observed-receipt-audit-outcome-independent.audit_attempt_sequence");
}
{
    const value: Profile.ResponseMetadata = {identity: {operationId: "operation-a"}, outcome: 3};
    check(!(value.identity.activationId !== undefined), "policy-response-has-no-fabricated-audit.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "policy-response-has-no-fabricated-audit.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "policy-response-has-no-fabricated-audit.identity.operation_id");
    check(value.outcome == 3, "policy-response-has-no-fabricated-audit.outcome");
    check(!(value.auditAck !== undefined), "policy-response-has-no-fabricated-audit.audit_ack.presence");
    check(!(value.auditStatus !== undefined), "policy-response-has-no-fabricated-audit.audit_status.presence");
    check(!(value.auditAttemptSequence !== undefined), "policy-response-has-no-fabricated-audit.audit_attempt_sequence.presence");
}
{
    const value: Profile.ResponseMetadata = {identity: {operationId: "operation-a"}, outcome: 2};
    check(!(value.identity.activationId !== undefined), "missing-recovery-keeps-outcome-unknown.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "missing-recovery-keeps-outcome-unknown.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "missing-recovery-keeps-outcome-unknown.identity.operation_id");
    check(value.outcome == 2, "missing-recovery-keeps-outcome-unknown.outcome");
    check(!(value.auditAck !== undefined), "missing-recovery-keeps-outcome-unknown.audit_ack.presence");
    check(!(value.auditStatus !== undefined), "missing-recovery-keeps-outcome-unknown.audit_status.presence");
    check(!(value.auditAttemptSequence !== undefined), "missing-recovery-keeps-outcome-unknown.audit_attempt_sequence.presence");
}
{
    const value: Profile.ResponseMetadata = {identity: {operationId: "operation-a"}, outcome: 91, auditAck: {status: 91, attemptSequence: 0n}, auditStatus: "future-audit-status", auditAttemptSequence: 0n};
    check(!(value.identity.activationId !== undefined), "unknown-audit-enum-and-status.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "unknown-audit-enum-and-status.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "unknown-audit-enum-and-status.identity.operation_id");
    check(value.outcome == 91, "unknown-audit-enum-and-status.outcome");
    check(value.auditAck !== undefined, "unknown-audit-enum-and-status.audit_ack.presence");
    check(value.auditAck!.status == 91, "unknown-audit-enum-and-status.audit_ack.status");
    check(value.auditAck!.attemptSequence !== undefined, "unknown-audit-enum-and-status.audit_ack.attempt_sequence.presence");
    check(value.auditAck!.attemptSequence! == 0n, "unknown-audit-enum-and-status.audit_ack.attempt_sequence");
    check(value.auditStatus !== undefined, "unknown-audit-enum-and-status.audit_status.presence");
    check(value.auditStatus! == "future-audit-status", "unknown-audit-enum-and-status.audit_status");
    check(value.auditAttemptSequence !== undefined, "unknown-audit-enum-and-status.audit_attempt_sequence.presence");
    check(value.auditAttemptSequence! == 0n, "unknown-audit-enum-and-status.audit_attempt_sequence");
}
{
    const value: Profile.ResponseMetadata = {identity: {operationId: "operation-a"}, outcome: 3, auditStatus: "future-state", auditAttemptSequence: 18446744073709551615n};
    check(!(value.identity.activationId !== undefined), "unknown-audit-header-and-max-attempt.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "unknown-audit-header-and-max-attempt.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "unknown-audit-header-and-max-attempt.identity.operation_id");
    check(value.outcome == 3, "unknown-audit-header-and-max-attempt.outcome");
    check(!(value.auditAck !== undefined), "unknown-audit-header-and-max-attempt.audit_ack.presence");
    check(value.auditStatus !== undefined, "unknown-audit-header-and-max-attempt.audit_status.presence");
    check(value.auditStatus! == "future-state", "unknown-audit-header-and-max-attempt.audit_status");
    check(value.auditAttemptSequence !== undefined, "unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
    check(value.auditAttemptSequence! == 18446744073709551615n, "unknown-audit-header-and-max-attempt.audit_attempt_sequence");
}
{
    const value: Profile.ClientFailure = {category: 4, message: "rpc-failure", grpcStatus: 13, dispatched: true, outcome: 2, identity: {operationId: "operation-a"}, auditStatus: "future-state", auditAttemptSequence: 18446744073709551615n};
    check(value.category == 4, "failed-rpc-unknown-audit-header-and-max-attempt.category");
    check(value.message == "rpc-failure", "failed-rpc-unknown-audit-header-and-max-attempt.message");
    check(value.grpcStatus !== undefined, "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status.presence");
    check(value.grpcStatus! == 13, "failed-rpc-unknown-audit-header-and-max-attempt.grpc_status");
    check(!(value.platformError !== undefined), "failed-rpc-unknown-audit-header-and-max-attempt.platform_error.presence");
    check(value.dispatched == true, "failed-rpc-unknown-audit-header-and-max-attempt.dispatched");
    check(value.outcome == 2, "failed-rpc-unknown-audit-header-and-max-attempt.outcome");
    check(!(value.identity.activationId !== undefined), "failed-rpc-unknown-audit-header-and-max-attempt.identity.activation_id.presence");
    check(value.identity.operationId !== undefined, "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id.presence");
    check(value.identity.operationId! == "operation-a", "failed-rpc-unknown-audit-header-and-max-attempt.identity.operation_id");
    check(!(value.auditAck !== undefined), "failed-rpc-unknown-audit-header-and-max-attempt.audit_ack.presence");
    check(value.auditStatus !== undefined, "failed-rpc-unknown-audit-header-and-max-attempt.audit_status.presence");
    check(value.auditStatus! == "future-state", "failed-rpc-unknown-audit-header-and-max-attempt.audit_status");
    check(!(value.unsupportedWireValue !== undefined), "failed-rpc-unknown-audit-header-and-max-attempt.unsupported_wire_value.presence");
    check(value.auditAttemptSequence !== undefined, "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence.presence");
    check(value.auditAttemptSequence! == 18446744073709551615n, "failed-rpc-unknown-audit-header-and-max-attempt.audit_attempt_sequence");
}
{
    const value: Profile.AuditAck = {status: 1};
    check(value.status == 1, "audit-durable-attempt-absent.status");
    check(!(value.attemptSequence !== undefined), "audit-durable-attempt-absent.attempt_sequence.presence");
}
{
    const value: Profile.AuditAck = {status: 3, attemptSequence: 0n};
    check(value.status == 3, "audit-unavailable-attempt-zero.status");
    check(value.attemptSequence !== undefined, "audit-unavailable-attempt-zero.attempt_sequence.presence");
    check(value.attemptSequence! == 0n, "audit-unavailable-attempt-zero.attempt_sequence");
}
{
    const value: Profile.AuditAck = {status: 4};
    check(value.status == 4, "audit-disabled-distinct-from-absence.status");
    check(!(value.attemptSequence !== undefined), "audit-disabled-distinct-from-absence.attempt_sequence.presence");
}
{
    const value: Profile.PublicationRef = {id: "", tenant: "tenant-a"};
    check(value.id == "", "publication-reference-invalid-id.id");
    check(value.tenant == "tenant-a", "publication-reference-invalid-id.tenant");
}
{
    const value: Profile.PublicationRef = {id: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", tenant: "tenant-b"};
    check(value.id == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "publication-reference-tenant-scope.id");
    check(value.tenant == "tenant-b", "publication-reference-tenant-scope.tenant");
}
{
    const value: Profile.PublicationIdentity = {publication: {id: "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", tenant: "tenant-a"}, componentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", packageDigest: "sha256:1111111111111111111111111111111111111111111111111111111111111111"};
    check(value.publication.id == "publication:sha256:1111111111111111111111111111111111111111111111111111111111111111", "publication-original-package.publication.id");
    check(value.publication.tenant == "tenant-a", "publication-original-package.publication.tenant");
    check(value.componentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication-original-package.component_digest");
    check(value.packageDigest == "sha256:1111111111111111111111111111111111111111111111111111111111111111", "publication-original-package.package_digest");
}
{
    const value: Profile.PublicationIdentity = {publication: {id: "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", tenant: "tenant-a"}, componentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", packageDigest: "sha256:2222222222222222222222222222222222222222222222222222222222222222"};
    check(value.publication.id == "publication:sha256:2222222222222222222222222222222222222222222222222222222222222222", "publication-corrected-package-same-component.publication.id");
    check(value.publication.tenant == "tenant-a", "publication-corrected-package-same-component.publication.tenant");
    check(value.componentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication-corrected-package-same-component.component_digest");
    check(value.packageDigest == "sha256:2222222222222222222222222222222222222222222222222222222222222222", "publication-corrected-package-same-component.package_digest");
}
{
    const value: Profile.PublicationIdentity = {publication: {id: "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", tenant: "tenant-b"}, componentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", packageDigest: "sha256:2222222222222222222222222222222222222222222222222222222222222222"};
    check(value.publication.id == "publication:sha256:3333333333333333333333333333333333333333333333333333333333333333", "publication-other-tenant-same-package.publication.id");
    check(value.publication.tenant == "tenant-b", "publication-other-tenant-same-package.publication.tenant");
    check(value.componentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "publication-other-tenant-same-package.component_digest");
    check(value.packageDigest == "sha256:2222222222222222222222222222222222222222222222222222222222222222", "publication-other-tenant-same-package.package_digest");
}
{
    const value: Profile.InspectHttpTargetRequest = {service: "service-a", contract: "latent:web/application@0.1.0", function: "handle", route: "web", revisionId: "revision-a", publication: {id: "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", tenant: "tenant-a"}, routingKey: "reviewed-key", includePreparation: true, maximumWaitMillis: 30000n};
    check(value.service == "service-a", "target-inspection-exact-bounded-publication-selector.service");
    check(value.contract == "latent:web/application@0.1.0", "target-inspection-exact-bounded-publication-selector.contract");
    check(value.function == "handle", "target-inspection-exact-bounded-publication-selector.function");
    check(value.route !== undefined, "target-inspection-exact-bounded-publication-selector.route.presence");
    check(value.route! == "web", "target-inspection-exact-bounded-publication-selector.route");
    check(value.revisionId !== undefined, "target-inspection-exact-bounded-publication-selector.revision_id.presence");
    check(value.revisionId! == "revision-a", "target-inspection-exact-bounded-publication-selector.revision_id");
    check(value.publication !== undefined, "target-inspection-exact-bounded-publication-selector.publication.presence");
    check(value.publication!.id == "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "target-inspection-exact-bounded-publication-selector.publication.id");
    check(value.publication!.tenant == "tenant-a", "target-inspection-exact-bounded-publication-selector.publication.tenant");
    check(value.routingKey !== undefined, "target-inspection-exact-bounded-publication-selector.routing_key.presence");
    check(value.routingKey! == "reviewed-key", "target-inspection-exact-bounded-publication-selector.routing_key");
    check(value.includePreparation == true, "target-inspection-exact-bounded-publication-selector.include_preparation");
    check(value.maximumWaitMillis == 30000n, "target-inspection-exact-bounded-publication-selector.maximum_wait_millis");
}
{
    const value: Profile.InspectHttpTargetResponse = {schemaVersion: 1, tenant: "tenant-a", service: "service-a", contract: "latent:web/application@0.1.0", function: "handle", route: "web", state: 1, catalogTransaction: 18446744073709551615n, routeGeneration: 18446744073709551615n, bindingGeneration: 18446744073709551615n, policyStoreGeneration: 0n, candidates: [{deploymentId: "deployment-a", deploymentGeneration: 18446744073709551615n, revisionId: "revision-a", componentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", publication: {id: "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", tenant: "tenant-a"}, requestedPublication: {id: "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", tenant: "tenant-a"}, packageDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", publicationGeneration: 18446744073709551615n, routingWeight: 100, exportCompatible: true, httpCompatible: true, eligible: true, reasons: [1], dependencies: [{capability: "latent:runtime/clocks@0.1.0", state: "configured-current", policyIdentityDigest: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", providerConfigurationEpoch: 18446744073709551615n, binding: {id: "binding-a", digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", revision: 18446744073709551615n}, policies: [{id: "policy-a", digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", revision: 0n}], providerProfile: "host-runtime-v1", configurationDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}], preparation: {state: 1, profile: 2, engineVersion: "wasmtime-42", engineConfigurationDigest: "blake3:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", targetTriple: "x86_64-unknown-linux-gnu", cpuFeatureSet: "baseline", sealedMetadataFingerprint: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", importCount: 2n, functionCount: 1n, hostcallFuel: 18446744073709551615n, maximumLiftedBytes: 67108864n, maximumTypeNodes: 65536n, declaredBudget: {cpuFuel: 18446744073709551615n, memoryBytes: 18446744073709551615n, childCalls: 4294967295, outboundRequests: 0, stateReadBytes: 18446744073709551615n, stateWriteBytes: 0n, blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0, wallTimeLimitMillis: 0n}, imports: ["latent:runtime/clocks@0.1.0"], exports: [{contract: "latent:web/application@0.1.0", function: "handle"}], typeImports: ["examples:java-http-domain/types@1.0.0"]}, publicationKind: "capsule", httpBindings: [{id: "trigger-a", generation: 18446744073709551615n, selectedDeploymentGeneration: 18446744073709551615n, state: "configured-current"}]}], selectedRevisionId: "revision-a", liveGrantsChecked: false};
    check(value.schemaVersion == 1, "target-inspection-ready-keeps-full-width-owner-identities.schema_version");
    check(value.tenant == "tenant-a", "target-inspection-ready-keeps-full-width-owner-identities.tenant");
    check(value.service == "service-a", "target-inspection-ready-keeps-full-width-owner-identities.service");
    check(value.contract == "latent:web/application@0.1.0", "target-inspection-ready-keeps-full-width-owner-identities.contract");
    check(value.function == "handle", "target-inspection-ready-keeps-full-width-owner-identities.function");
    check(value.route == "web", "target-inspection-ready-keeps-full-width-owner-identities.route");
    check(value.state == 1, "target-inspection-ready-keeps-full-width-owner-identities.state");
    check(value.catalogTransaction == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.catalog_transaction");
    check(value.routeGeneration == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.route_generation");
    check(value.bindingGeneration == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.binding_generation");
    check(value.policyStoreGeneration !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.policy_store_generation.presence");
    check(value.policyStoreGeneration! == 0n, "target-inspection-ready-keeps-full-width-owner-identities.policy_store_generation");
    check(value.candidates.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.count");
    check(value.candidates[0]!.deploymentId == "deployment-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.deployment_id");
    check(value.candidates[0]!.deploymentGeneration == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.deployment_generation");
    check(value.candidates[0]!.revisionId == "revision-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.revision_id");
    check(value.candidates[0]!.componentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.component_digest");
    check(value.candidates[0]!.publication !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication.presence");
    check(value.candidates[0]!.publication!.id == "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication.id");
    check(value.candidates[0]!.publication!.tenant == "tenant-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication.tenant");
    check(value.candidates[0]!.requestedPublication !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.requested_publication.presence");
    check(value.candidates[0]!.requestedPublication!.id == "publication:sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.requested_publication.id");
    check(value.candidates[0]!.requestedPublication!.tenant == "tenant-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.requested_publication.tenant");
    check(value.candidates[0]!.packageDigest !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.package_digest.presence");
    check(value.candidates[0]!.packageDigest! == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.package_digest");
    check(value.candidates[0]!.publicationGeneration !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_generation.presence");
    check(value.candidates[0]!.publicationGeneration! == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_generation");
    check(value.candidates[0]!.routingWeight == 100, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.routing_weight");
    check(value.candidates[0]!.exportCompatible == true, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.export_compatible");
    check(value.candidates[0]!.httpCompatible == true, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_compatible");
    check(value.candidates[0]!.eligible == true, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.eligible");
    check(value.candidates[0]!.reasons.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.reasons.count");
    check(value.candidates[0]!.reasons[0]! == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.reasons.0");
    check(value.candidates[0]!.dependencies.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.count");
    check(value.candidates[0]!.dependencies[0]!.capability == "latent:runtime/clocks@0.1.0", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.capability");
    check(value.candidates[0]!.dependencies[0]!.state == "configured-current", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.state");
    check(value.candidates[0]!.dependencies[0]!.policyIdentityDigest == "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policy_identity_digest");
    check(value.candidates[0]!.dependencies[0]!.providerConfigurationEpoch == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.provider_configuration_epoch");
    check(value.candidates[0]!.dependencies[0]!.binding !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.presence");
    check(value.candidates[0]!.dependencies[0]!.binding!.id == "binding-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.id");
    check(value.candidates[0]!.dependencies[0]!.binding!.digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.digest");
    check(value.candidates[0]!.dependencies[0]!.binding!.revision == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.binding.revision");
    check(value.candidates[0]!.dependencies[0]!.policies.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.count");
    check(value.candidates[0]!.dependencies[0]!.policies[0]!.id == "policy-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.0.id");
    check(value.candidates[0]!.dependencies[0]!.policies[0]!.digest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.0.digest");
    check(value.candidates[0]!.dependencies[0]!.policies[0]!.revision == 0n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.policies.0.revision");
    check(value.candidates[0]!.dependencies[0]!.providerProfile == "host-runtime-v1", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.provider_profile");
    check(value.candidates[0]!.dependencies[0]!.configurationDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.dependencies.0.configuration_digest");
    check(value.candidates[0]!.preparation !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.presence");
    check(value.candidates[0]!.preparation!.state == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.state");
    check(!(value.candidates[0]!.preparation!.diagnostic !== undefined), "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.diagnostic.presence");
    check(value.candidates[0]!.preparation!.profile !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.profile.presence");
    check(value.candidates[0]!.preparation!.profile! == 2, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.profile");
    check(value.candidates[0]!.preparation!.engineVersion !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_version.presence");
    check(value.candidates[0]!.preparation!.engineVersion! == "wasmtime-42", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_version");
    check(value.candidates[0]!.preparation!.engineConfigurationDigest !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_configuration_digest.presence");
    check(value.candidates[0]!.preparation!.engineConfigurationDigest! == "blake3:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.engine_configuration_digest");
    check(value.candidates[0]!.preparation!.targetTriple !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.target_triple.presence");
    check(value.candidates[0]!.preparation!.targetTriple! == "x86_64-unknown-linux-gnu", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.target_triple");
    check(value.candidates[0]!.preparation!.cpuFeatureSet !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.cpu_feature_set.presence");
    check(value.candidates[0]!.preparation!.cpuFeatureSet! == "baseline", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.cpu_feature_set");
    check(value.candidates[0]!.preparation!.sealedMetadataFingerprint !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.sealed_metadata_fingerprint.presence");
    check(value.candidates[0]!.preparation!.sealedMetadataFingerprint! == "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.sealed_metadata_fingerprint");
    check(value.candidates[0]!.preparation!.importCount !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.import_count.presence");
    check(value.candidates[0]!.preparation!.importCount! == 2n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.import_count");
    check(value.candidates[0]!.preparation!.functionCount !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.function_count.presence");
    check(value.candidates[0]!.preparation!.functionCount! == 1n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.function_count");
    check(value.candidates[0]!.preparation!.hostcallFuel !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.hostcall_fuel.presence");
    check(value.candidates[0]!.preparation!.hostcallFuel! == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.hostcall_fuel");
    check(value.candidates[0]!.preparation!.maximumLiftedBytes !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_lifted_bytes.presence");
    check(value.candidates[0]!.preparation!.maximumLiftedBytes! == 67108864n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_lifted_bytes");
    check(value.candidates[0]!.preparation!.maximumTypeNodes !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_type_nodes.presence");
    check(value.candidates[0]!.preparation!.maximumTypeNodes! == 65536n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.maximum_type_nodes");
    check(value.candidates[0]!.preparation!.declaredBudget !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.presence");
    check(value.candidates[0]!.preparation!.declaredBudget!.cpuFuel == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.cpu_fuel");
    check(value.candidates[0]!.preparation!.declaredBudget!.memoryBytes == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.memory_bytes");
    check(value.candidates[0]!.preparation!.declaredBudget!.childCalls == 4294967295, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.child_calls");
    check(value.candidates[0]!.preparation!.declaredBudget!.outboundRequests == 0, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.outbound_requests");
    check(value.candidates[0]!.preparation!.declaredBudget!.stateReadBytes == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.state_read_bytes");
    check(value.candidates[0]!.preparation!.declaredBudget!.stateWriteBytes == 0n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.state_write_bytes");
    check(value.candidates[0]!.preparation!.declaredBudget!.blobReadBytes == 0n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.blob_read_bytes");
    check(value.candidates[0]!.preparation!.declaredBudget!.blobWriteBytes == 0n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.blob_write_bytes");
    check(value.candidates[0]!.preparation!.declaredBudget!.logBytes == 0n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.log_bytes");
    check(value.candidates[0]!.preparation!.declaredBudget!.effectCount == 0, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.effect_count");
    check(value.candidates[0]!.preparation!.declaredBudget!.wallTimeLimitMillis !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.wall_time_limit_millis.presence");
    check(value.candidates[0]!.preparation!.declaredBudget!.wallTimeLimitMillis! == 0n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.declared_budget.wall_time_limit_millis");
    check(value.candidates[0]!.preparation!.imports.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.imports.count");
    check(value.candidates[0]!.preparation!.imports[0]! == "latent:runtime/clocks@0.1.0", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.imports.0");
    check(value.candidates[0]!.preparation!.exports.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.exports.count");
    check(value.candidates[0]!.preparation!.exports[0]!.contract == "latent:web/application@0.1.0", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.exports.0.contract");
    check(value.candidates[0]!.preparation!.exports[0]!.function == "handle", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.exports.0.function");
    check(value.candidates[0]!.preparation!.typeImports.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.type_imports.count");
    check(value.candidates[0]!.preparation!.typeImports[0]! == "examples:java-http-domain/types@1.0.0", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.preparation.type_imports.0");
    check(value.candidates[0]!.publicationKind !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_kind.presence");
    check(value.candidates[0]!.publicationKind! == "capsule", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.publication_kind");
    check(value.candidates[0]!.httpBindings.length == 1, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.count");
    check(value.candidates[0]!.httpBindings[0]!.id == "trigger-a", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.id");
    check(value.candidates[0]!.httpBindings[0]!.generation == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.generation");
    check(value.candidates[0]!.httpBindings[0]!.selectedDeploymentGeneration == 18446744073709551615n, "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.selected_deployment_generation");
    check(value.candidates[0]!.httpBindings[0]!.state == "configured-current", "target-inspection-ready-keeps-full-width-owner-identities.candidates.0.http_bindings.0.state");
    check(value.selectedRevisionId !== undefined, "target-inspection-ready-keeps-full-width-owner-identities.selected_revision_id.presence");
    check(value.selectedRevisionId! == "revision-a", "target-inspection-ready-keeps-full-width-owner-identities.selected_revision_id");
    check(value.liveGrantsChecked == false, "target-inspection-ready-keeps-full-width-owner-identities.live_grants_checked");
}
{
    const value: Profile.InspectHttpTargetResponse = {schemaVersion: 1, tenant: "tenant-a", service: "service-a", contract: "domain:application/api@1.0.0", function: "get", route: "domain", state: 777, catalogTransaction: 0n, routeGeneration: 0n, bindingGeneration: 0n, candidates: [{deploymentId: "deployment-a", deploymentGeneration: 0n, revisionId: "revision-a", componentDigest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", routingWeight: 0, exportCompatible: false, httpCompatible: false, eligible: false, reasons: [-2147483648, 778], dependencies: [], preparation: {state: 779, diagnostic: {schemaVersion: 1, stage: 780, reason: 781, configuredBound: 0n, calculatedRequirement: 18446744073709551615n}, imports: [], exports: [], typeImports: []}, httpBindings: []}], liveGrantsChecked: false};
    check(value.schemaVersion == 1, "target-inspection-future-states-remain-descriptive.schema_version");
    check(value.tenant == "tenant-a", "target-inspection-future-states-remain-descriptive.tenant");
    check(value.service == "service-a", "target-inspection-future-states-remain-descriptive.service");
    check(value.contract == "domain:application/api@1.0.0", "target-inspection-future-states-remain-descriptive.contract");
    check(value.function == "get", "target-inspection-future-states-remain-descriptive.function");
    check(value.route == "domain", "target-inspection-future-states-remain-descriptive.route");
    check(value.state == 777, "target-inspection-future-states-remain-descriptive.state");
    check(value.catalogTransaction == 0n, "target-inspection-future-states-remain-descriptive.catalog_transaction");
    check(value.routeGeneration == 0n, "target-inspection-future-states-remain-descriptive.route_generation");
    check(value.bindingGeneration == 0n, "target-inspection-future-states-remain-descriptive.binding_generation");
    check(!(value.policyStoreGeneration !== undefined), "target-inspection-future-states-remain-descriptive.policy_store_generation.presence");
    check(value.candidates.length == 1, "target-inspection-future-states-remain-descriptive.candidates.count");
    check(value.candidates[0]!.deploymentId == "deployment-a", "target-inspection-future-states-remain-descriptive.candidates.0.deployment_id");
    check(value.candidates[0]!.deploymentGeneration == 0n, "target-inspection-future-states-remain-descriptive.candidates.0.deployment_generation");
    check(value.candidates[0]!.revisionId == "revision-a", "target-inspection-future-states-remain-descriptive.candidates.0.revision_id");
    check(value.candidates[0]!.componentDigest == "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "target-inspection-future-states-remain-descriptive.candidates.0.component_digest");
    check(!(value.candidates[0]!.publication !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.publication.presence");
    check(!(value.candidates[0]!.requestedPublication !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.requested_publication.presence");
    check(!(value.candidates[0]!.packageDigest !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.package_digest.presence");
    check(!(value.candidates[0]!.publicationGeneration !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.publication_generation.presence");
    check(value.candidates[0]!.routingWeight == 0, "target-inspection-future-states-remain-descriptive.candidates.0.routing_weight");
    check(value.candidates[0]!.exportCompatible == false, "target-inspection-future-states-remain-descriptive.candidates.0.export_compatible");
    check(value.candidates[0]!.httpCompatible == false, "target-inspection-future-states-remain-descriptive.candidates.0.http_compatible");
    check(value.candidates[0]!.eligible == false, "target-inspection-future-states-remain-descriptive.candidates.0.eligible");
    check(value.candidates[0]!.reasons.length == 2, "target-inspection-future-states-remain-descriptive.candidates.0.reasons.count");
    check(value.candidates[0]!.reasons[0]! == -2147483648, "target-inspection-future-states-remain-descriptive.candidates.0.reasons.0");
    check(value.candidates[0]!.reasons[1]! == 778, "target-inspection-future-states-remain-descriptive.candidates.0.reasons.1");
    check(value.candidates[0]!.dependencies.length == 0, "target-inspection-future-states-remain-descriptive.candidates.0.dependencies.count");
    check(value.candidates[0]!.preparation !== undefined, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.presence");
    check(value.candidates[0]!.preparation!.state == 779, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.state");
    check(value.candidates[0]!.preparation!.diagnostic !== undefined, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.presence");
    check(value.candidates[0]!.preparation!.diagnostic!.schemaVersion == 1, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.schema_version");
    check(value.candidates[0]!.preparation!.diagnostic!.stage == 780, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.stage");
    check(value.candidates[0]!.preparation!.diagnostic!.reason == 781, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.reason");
    check(!(value.candidates[0]!.preparation!.diagnostic!.profile !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.profile.presence");
    check(!(value.candidates[0]!.preparation!.diagnostic!.profileDigest !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.profile_digest.presence");
    check(value.candidates[0]!.preparation!.diagnostic!.configuredBound !== undefined, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.configured_bound.presence");
    check(value.candidates[0]!.preparation!.diagnostic!.configuredBound! == 0n, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.configured_bound");
    check(value.candidates[0]!.preparation!.diagnostic!.calculatedRequirement !== undefined, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.calculated_requirement.presence");
    check(value.candidates[0]!.preparation!.diagnostic!.calculatedRequirement! == 18446744073709551615n, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.calculated_requirement");
    check(!(value.candidates[0]!.preparation!.diagnostic!.fixedBytes !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.fixed_bytes.presence");
    check(!(value.candidates[0]!.preparation!.diagnostic!.liftingFuel !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.lifting_fuel.presence");
    check(!(value.candidates[0]!.preparation!.diagnostic!.liftMultiplier !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.diagnostic.lift_multiplier.presence");
    check(!(value.candidates[0]!.preparation!.profile !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.profile.presence");
    check(!(value.candidates[0]!.preparation!.engineVersion !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.engine_version.presence");
    check(!(value.candidates[0]!.preparation!.engineConfigurationDigest !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.engine_configuration_digest.presence");
    check(!(value.candidates[0]!.preparation!.targetTriple !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.target_triple.presence");
    check(!(value.candidates[0]!.preparation!.cpuFeatureSet !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.cpu_feature_set.presence");
    check(!(value.candidates[0]!.preparation!.sealedMetadataFingerprint !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.sealed_metadata_fingerprint.presence");
    check(!(value.candidates[0]!.preparation!.importCount !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.import_count.presence");
    check(!(value.candidates[0]!.preparation!.functionCount !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.function_count.presence");
    check(!(value.candidates[0]!.preparation!.hostcallFuel !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.hostcall_fuel.presence");
    check(!(value.candidates[0]!.preparation!.maximumLiftedBytes !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.maximum_lifted_bytes.presence");
    check(!(value.candidates[0]!.preparation!.maximumTypeNodes !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.maximum_type_nodes.presence");
    check(!(value.candidates[0]!.preparation!.declaredBudget !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.preparation.declared_budget.presence");
    check(value.candidates[0]!.preparation!.imports.length == 0, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.imports.count");
    check(value.candidates[0]!.preparation!.exports.length == 0, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.exports.count");
    check(value.candidates[0]!.preparation!.typeImports.length == 0, "target-inspection-future-states-remain-descriptive.candidates.0.preparation.type_imports.count");
    check(!(value.candidates[0]!.publicationKind !== undefined), "target-inspection-future-states-remain-descriptive.candidates.0.publication_kind.presence");
    check(value.candidates[0]!.httpBindings.length == 0, "target-inspection-future-states-remain-descriptive.candidates.0.http_bindings.count");
    check(!(value.selectedRevisionId !== undefined), "target-inspection-future-states-remain-descriptive.selected_revision_id.presence");
    check(value.liveGrantsChecked == false, "target-inspection-future-states-remain-descriptive.live_grants_checked");
}
check(Profile.formatU64Decimal(Profile.parseU64Decimal("0")) == "0", "uint64 roundtrip");
check(Profile.formatU64Decimal(Profile.parseU64Decimal("9007199254740993")) == "9007199254740993", "uint64 roundtrip");
check(Profile.formatU64Decimal(Profile.parseU64Decimal("9223372036854775808")) == "9223372036854775808", "uint64 roundtrip");
check(Profile.formatU64Decimal(Profile.parseU64Decimal("18446744073709551615")) == "18446744073709551615", "uint64 roundtrip");
rejects(() => Profile.parseU64Decimal("18446744073709551616"));
rejects(() => Profile.parseU64Decimal("-1"));
rejects(() => Profile.parseU64Decimal("+1"));
rejects(() => Profile.parseU64Decimal("01"));
rejects(() => Profile.parseU64Decimal(" 1"));
rejects(() => Profile.parseU64Decimal("1 "));
rejects(() => Profile.parseU64Decimal("1.0"));
rejects(() => Profile.parseU64Decimal("1e3"));
rejects(() => Profile.parseU64Decimal(""));
rejects(() => Profile.parseU64Decimal("1\u0000"));
rejects(() => Profile.parseU64Decimal("1\n"));
rejects(() => Profile.parseU64Decimal("1\r\n"));
rejects(() => Profile.formatU64Decimal(9007199254740992 as unknown as bigint));
rejects(() => Profile.parseU64Decimal(1 as unknown as string));
rejects(() => Profile.formatU64Decimal(-1n));
rejects(() => Profile.formatU64Decimal(18446744073709551616n));
console.log("shared profile vectors: 77");
