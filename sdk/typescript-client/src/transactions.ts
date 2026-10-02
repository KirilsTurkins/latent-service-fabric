// Generated from the authoritative transaction client descriptors.
import type * as profile from "./management.js";

export type CommandCancelDisposition = number;
export const CommandCancelDisposition = {
  Unspecified: 0,
  Requested: 1,
  AlreadyCommitted: 2,
  AlreadyTerminal: 3,
  NotFound: 4,
  RecoveryRequired: 5,
} as const;

export type CommandOutcome = number;
export const CommandOutcome = {
  Unspecified: 0,
  InProgress: 1,
  Committed: 2,
  Rejected: 3,
  Aborted: 4,
  Unknown: 5,
  RecoveryRequired: 6,
  Expired: 7,
} as const;

export type DispatcherAction = number;
export const DispatcherAction = {
  Unspecified: 0,
  Pause: 1,
  Resume: 2,
} as const;

export type DispatcherFailure = number;
export const DispatcherFailure = {
  Unspecified: 0,
  None: 1,
  Authority: 2,
  Store: 3,
  Worker: 4,
  RestoreCheckpoint: 5,
  AdmissionClosed: 6,
  Configuration: 7,
} as const;

export type DispatcherScope = number;
export const DispatcherScope = {
  Unspecified: 0,
  Node: 1,
} as const;

export type EffectDisposition = number;
export const EffectDisposition = {
  Unspecified: 0,
  Pending: 1,
  Dispatching: 2,
  ProviderAcknowledged: 3,
  KnownFailure: 4,
  UncertainAfterDispatch: 5,
  Expired: 6,
  PolicyBlocked: 7,
  AdministrativelyTerminated: 8,
  RetryScheduled: 9,
  DeadLettered: 10,
} as const;

export type EffectManagementFact = number;
export const EffectManagementFact = {
  Unspecified: 0,
  RedriveScheduled: 1,
  ProviderConfirmed: 2,
  AdministratorTerminated: 3,
} as const;

export type EffectPlanSafety = number;
export const EffectPlanSafety = {
  Unspecified: 0,
  KnownNonexecution: 1,
  QualifiedDeduplication: 2,
  ProviderReceiptLookup: 3,
  AdministratorDeclared: 4,
} as const;

export type NamespaceMutationKind = number;
export const NamespaceMutationKind = {
  Unspecified: 0,
  Create: 1,
  Quiesce: 2,
  Retire: 3,
  Destroy: 4,
  Recreate: 5,
} as const;

export type NamespaceStatus = number;
export const NamespaceStatus = {
  Unspecified: 0,
  Active: 1,
  Quiescing: 2,
  Retired: 3,
  Tombstone: 4,
} as const;

export type StateMutationKind = number;
export const StateMutationKind = {
  Unspecified: 0,
  RetryKnownFailedEffect: 1,
  TerminateEffect: 2,
  PurgeExpiredPayload: 3,
  CheckpointNamespace: 4,
  ReconcileEffect: 5,
} as const;

export type StateOperationDisposition = number;
export const StateOperationDisposition = {
  Unspecified: 0,
  Committed: 1,
  Conflict: 2,
  Rejected: 3,
  Unknown: 4,
  RecoveryRequired: 5,
} as const;

export interface AbortFence {
  readonly commandId: string;
  readonly attemptId: string;
  readonly transactionId: string;
  readonly ownerFence: Uint8Array;
}

export interface TransactionProfile {
  readonly profile: string;
  readonly hostAbiDigest: string;
  readonly preparationProfileDigest: string;
}

export interface NamespaceSelector {
  readonly tenant: string;
  readonly namespace: string;
  readonly incarnation: string;
}

export interface CommandSelector {
  readonly namespace?: NamespaceSelector;
  readonly operation: string;
  readonly entity?: string;
  readonly clientKey: string;
  readonly sharedRecoveryScope?: string;
}

export interface LookupCommandRequest {
  readonly profile?: TransactionProfile;
  readonly command?: CommandSelector;
  readonly attemptId?: string;
  readonly authorizationPublication?: profile.PublicationRef;
}

export interface CancelCommandRequest {
  readonly command?: LookupCommandRequest;
  readonly reason: string;
}

export interface CommandKey {
  readonly namespace?: NamespaceSelector;
  readonly recoveryScope: string;
  readonly operation: string;
  readonly entity?: string;
  readonly clientKey: string;
}

export interface SourceIdentity {
  readonly publicationId: string;
  readonly revisionId: string;
  readonly releaseDigest: string;
  readonly routeGeneration: bigint;
  readonly contractDigest: string;
  readonly stateSchema: string;
  readonly inputFormat: string;
  readonly resultFormat: string;
  readonly componentDigest: string;
}

export interface CommitReceipt {
  readonly commandId: string;
  readonly attemptId: string;
  readonly transactionId: string;
  readonly committedVersion: Uint8Array;
  readonly committedAtUnixMillis: bigint;
  readonly effectIds: readonly string[];
  readonly receiptId: string;
  readonly source?: SourceIdentity;
}

export interface LinkedRetention {
  readonly recordFormat: string;
  readonly recordVersion: number;
  readonly payloadExpiresAtUnixMillis?: bigint;
  readonly identityExpiresAtUnixMillis?: bigint;
  readonly remainingRecoveryMillis?: bigint;
  readonly requiredRecordIds: readonly string[];
  readonly payloadAvailable: boolean;
}

export interface CommandInspection {
  readonly key?: CommandKey;
  readonly commandId: string;
  readonly attemptId: string;
  readonly fingerprintSha256: Uint8Array;
  readonly outcome: CommandOutcome;
  readonly metadataDurable: boolean;
  readonly applicationStateCommitted: boolean;
  readonly source?: SourceIdentity;
  readonly success?: profile.Success;
  readonly businessRejection?: profile.DeclaredError;
  readonly technicalFailure?: profile.PlatformError;
  readonly commit?: CommitReceipt;
  readonly provenAbort?: AbortFence;
  readonly retention?: LinkedRetention;
  readonly cleanupFailure?: profile.PlatformError;
}

export interface CancelCommandResponse {
  readonly disposition: CommandCancelDisposition;
  readonly command?: CommandInspection;
}

export interface DispatcherGeneration {
  readonly ownerEpoch: bigint;
  readonly revision: bigint;
}

export interface ControlDispatcherRequest {
  readonly profile?: TransactionProfile;
  readonly scope: DispatcherScope;
  readonly operationId: string;
  readonly action: DispatcherAction;
  readonly expectedGeneration?: DispatcherGeneration;
}

export interface DispatcherOperationReceipt {
  readonly operationId: string;
  readonly receiptId: string;
  readonly action: DispatcherAction;
  readonly authenticatedOperator: string;
  readonly actorTenant: string;
  readonly beforeGeneration?: DispatcherGeneration;
  readonly afterGeneration?: DispatcherGeneration;
  readonly observedAtUnixMillis: bigint;
  readonly clockContinuityProven: boolean;
  readonly restoreReviewRequired: boolean;
  readonly disposition: StateOperationDisposition;
}

export interface ControlDispatcherResponse {
  readonly receipt?: DispatcherOperationReceipt;
  readonly replayed: boolean;
  readonly published: boolean;
  readonly paused: boolean;
  readonly auditAck?: profile.AuditAck;
}

export interface DispatcherSnapshot {
  readonly generation?: DispatcherGeneration;
  readonly paused: boolean;
  readonly pendingControl: boolean;
  readonly restoreReviewRequired: boolean;
  readonly admissionClosed: boolean;
  readonly quarantined: boolean;
  readonly failure: DispatcherFailure;
  readonly queued: bigint;
  readonly activeJobs: bigint;
  readonly retainedAttemptBytes: bigint;
  readonly liveWorkers: bigint;
  readonly acceptedEffects: bigint;
  readonly physicalOwners: bigint;
  readonly quarantinedPhysicalOwners: bigint;
  readonly commandOwners: bigint;
  readonly claims: bigint;
  readonly pendingEffects: bigint;
  readonly uncertainEffects: bigint;
  readonly blockedEffects: bigint;
  readonly deadLetterEffects: bigint;
  readonly countsObservedAtUnixMillis: bigint;
  readonly clockContinuityProven: boolean;
}

export interface GetEffectRequest {
  readonly profile?: TransactionProfile;
  readonly command?: CommandSelector;
  readonly effectId: string;
  readonly authorizationPublication?: profile.PublicationRef;
}

export interface PlanEffectMutationRequest {
  readonly effect?: GetEffectRequest;
  readonly operationId: string;
  readonly mutation: StateMutationKind;
  readonly expectedVersion: Uint8Array;
  readonly expectedPolicyDigest: string;
  readonly reason: string;
  readonly retryDelayMillis: bigint;
}

export interface EffectManagementPlan {
  readonly original?: PlanEffectMutationRequest;
  readonly planDigest: Uint8Array;
  readonly managementSequence: number;
  readonly ownerEpoch: bigint;
  readonly claimGeneration: bigint;
  readonly dispatchAttempt: number;
  readonly expiresAtUnixMillis: bigint;
  readonly preparedAtUnixMillis: bigint;
  readonly before: EffectDisposition;
  readonly safety: EffectPlanSafety;
  readonly dedupValidUntilUnixMillis?: bigint;
}

export interface EffectManagementReceiptDetails {
  readonly originalPlan?: EffectManagementPlan;
  readonly before: EffectDisposition;
  readonly after: EffectDisposition;
  readonly fact: EffectManagementFact;
  readonly providerReceipt?: string;
  readonly providerObservedAtUnixMillis?: bigint;
}

export interface EffectReceipt {
  readonly effectId: string;
  readonly commandId: string;
  readonly commandAttemptId: string;
  readonly dispatchAttempt: number;
  readonly disposition: EffectDisposition;
  readonly providerReceipt?: string;
  readonly failureCode?: string;
  readonly occurredAtUnixMillis: bigint;
  readonly retention?: LinkedRetention;
  readonly managementOperationReceiptId?: string;
  readonly providerProfile: string;
  readonly recordVersion: Uint8Array;
  readonly ownerEpoch?: bigint;
  readonly claimGeneration?: bigint;
}

export interface EntityInspection {
  readonly entity: string;
  readonly version: Uint8Array;
}

export interface ExpectedVersion {
  readonly key: Uint8Array;
  readonly absent?: boolean;
  readonly version?: Uint8Array;
}

export interface GetDispatcherOperationRequest {
  readonly original?: ControlDispatcherRequest;
}

export interface GetDispatcherOperationResponse {
  readonly receipt?: DispatcherOperationReceipt;
  readonly auditAck?: profile.AuditAck;
}

export interface GetEffectResponse {
  readonly effect?: EffectReceipt;
}

export interface InspectNamespaceRequest {
  readonly profile?: TransactionProfile;
  readonly namespace?: NamespaceSelector;
  readonly authorizationPublication?: profile.PublicationRef;
}

export interface GetStateOperationReceiptRequest {
  readonly namespace?: InspectNamespaceRequest;
  readonly operationId: string;
  readonly originalEffectPlan?: EffectManagementPlan;
}

export interface StateOperationReceipt {
  readonly operationId: string;
  readonly receiptId: string;
  readonly mutation: StateMutationKind;
  readonly namespace?: NamespaceSelector;
  readonly authenticatedOperator: string;
  readonly beforeVersion: Uint8Array;
  readonly afterVersion: Uint8Array;
  readonly completedAtUnixMillis: bigint;
  readonly recordId?: string;
  readonly policyDigest: string;
  readonly disposition: StateOperationDisposition;
  readonly effect?: EffectManagementReceiptDetails;
}

export interface NamespaceOperationReceipt {
  readonly operationId: string;
  readonly receiptId: string;
  readonly mutation: NamespaceMutationKind;
  readonly namespace?: NamespaceSelector;
  readonly authenticatedOperator: string;
  readonly beforeGeneration?: bigint;
  readonly afterGeneration: bigint;
  readonly status: NamespaceStatus;
  readonly stateSchema: string;
  readonly disposition: StateOperationDisposition;
}

export interface GetStateOperationReceiptResponse {
  readonly receipt?: StateOperationReceipt;
  readonly namespaceReceipt?: NamespaceOperationReceipt;
  readonly auditAck?: profile.AuditAck;
}

export interface InspectDispatcherRequest {
  readonly profile?: TransactionProfile;
  readonly scope: DispatcherScope;
}

export interface InspectDispatcherResponse {
  readonly dispatcher?: DispatcherSnapshot;
  readonly auditAck?: profile.AuditAck;
}

export interface ViewIdentity {
  readonly namespace?: NamespaceSelector;
  readonly version: Uint8Array;
  readonly stateSchema: string;
}

export interface NamespaceQuota {
  readonly stateKeys: bigint;
  readonly stateBytes: bigint;
  readonly resultRows: bigint;
  readonly resultBytes: bigint;
  readonly effectRows: bigint;
  readonly effectBytes: bigint;
  readonly payloadBytes: bigint;
  readonly recoveryBytes: bigint;
}

export interface NamespaceInspection {
  readonly view?: ViewIdentity;
  readonly encodedStateBytes: bigint;
  readonly commandCount: bigint;
  readonly pendingEffectCount: bigint;
  readonly retainedFormats: readonly LinkedRetention[];
  readonly engineProfile: string;
  readonly engineProfileDigest: string;
  readonly status: NamespaceStatus;
  readonly quota?: NamespaceQuota;
  readonly generation: bigint;
  readonly namespacePolicyDigest: string;
}

export interface InspectNamespaceResponse {
  readonly namespace?: NamespaceInspection;
}

export interface RetryAttempt {
  readonly requestId: string;
  readonly expectedAbort?: AbortFence;
}

export interface InvokeCommandRequest {
  readonly profile?: TransactionProfile;
  readonly invocation?: profile.InvokeRequest;
  readonly command?: CommandSelector;
  readonly inputFormat: string;
  readonly expectedVersions: readonly ExpectedVersion[];
  readonly retryAttempt?: RetryAttempt;
}

export interface InvokeCommandResponse {
  readonly invocation?: profile.InvokeResponse;
  readonly command?: CommandInspection;
  readonly replayed: boolean;
}

export interface PageRequest {
  readonly limit: number;
  readonly cursor?: Uint8Array;
}

export interface ListEffectHistoryRequest {
  readonly effect?: GetEffectRequest;
  readonly page?: PageRequest;
}

export interface PageResponse {
  readonly nextCursor?: Uint8Array;
  readonly returnedCount: number;
  readonly encodedBytes: bigint;
}

export interface ListEffectHistoryResponse {
  readonly receipts: readonly EffectReceipt[];
  readonly page?: PageResponse;
}

export interface LookupCommandResponse {
  readonly command?: CommandInspection;
}

export interface LookupCommitRequest {
  readonly profile?: TransactionProfile;
  readonly command?: CommandSelector;
  readonly receiptId: string;
  readonly authorizationPublication?: profile.PublicationRef;
}

export interface LookupCommitResponse {
  readonly command?: CommandInspection;
}

export interface NamespaceConfiguration {
  readonly stateSchema: string;
  readonly quota?: NamespaceQuota;
}

export interface MutateNamespaceRequest {
  readonly namespace?: InspectNamespaceRequest;
  readonly operationId: string;
  readonly mutation: NamespaceMutationKind;
  readonly expectedGeneration?: bigint;
  readonly configuration?: NamespaceConfiguration;
}

export interface MutateNamespaceResponse {
  readonly receipt?: NamespaceOperationReceipt;
  readonly replayed: boolean;
  readonly auditAck?: profile.AuditAck;
}

export interface MutateStateRequest {
  readonly namespace?: InspectNamespaceRequest;
  readonly operationId: string;
  readonly mutation: StateMutationKind;
  readonly recordId?: string;
  readonly expectedVersion: Uint8Array;
  readonly expectedPolicyDigest: string;
  readonly reason: string;
  readonly effectPlan?: EffectManagementPlan;
}

export interface MutateStateResponse {
  readonly receipt?: StateOperationReceipt;
  readonly auditAck?: profile.AuditAck;
  readonly replayed: boolean;
}

export interface PlanEffectMutationResponse {
  readonly plan?: EffectManagementPlan;
  readonly replayed: boolean;
  readonly auditAck?: profile.AuditAck;
}

export interface QueryRequest {
  readonly profile?: TransactionProfile;
  readonly invocation?: profile.InvokeRequest;
  readonly namespace?: NamespaceSelector;
  readonly entity?: string;
  readonly minimumViewVersion?: Uint8Array;
}

export interface QueryResponse {
  readonly invocation?: profile.InvokeResponse;
  readonly view?: ViewIdentity;
  readonly source?: SourceIdentity;
  readonly observedAtUnixMillis: bigint;
}

export interface SelectEntityRequest {
  readonly namespace?: InspectNamespaceRequest;
  readonly prefix?: Uint8Array;
  readonly page?: PageRequest;
}

export interface SelectEntityResponse {
  readonly entities: readonly EntityInspection[];
  readonly page?: PageResponse;
}

/** Constructs a protocol descriptor; this value grants no authority. */
export function currentProfile(): TransactionProfile {
  return {
    profile: "lsf-transaction-v1",
    hostAbiDigest: "sha256:3b85f790f85ab23d36e492d7bd4a04a1b8aab87fc6f67dd7d7498bcf28129d35",
    preparationProfileDigest: "sha256:6acd7a248633dd01c9cdcbf8a1ed33fc5e6aa1d2edb09b7d89e53fda594b5507",
  };
}
