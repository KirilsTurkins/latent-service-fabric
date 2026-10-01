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

export interface GetEffectRequest {
  readonly profile?: TransactionProfile;
  readonly command?: CommandSelector;
  readonly effectId: string;
  readonly authorizationPublication?: profile.PublicationRef;
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
}

export interface MutateStateResponse {
  readonly receipt?: StateOperationReceipt;
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
