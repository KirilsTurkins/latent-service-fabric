export type AuditAckStatus = number;
export const AuditAckStatus = {
  Unspecified: 0,
  Durable: 1,
  OutcomeUnknown: 2,
  AuditUnavailable: 3,
  Disabled: 4,
} as const;

export type CancelDisposition = number;
export const CancelDisposition = {
  Unspecified: 0,
  Accepted: 1,
  AlreadyTerminal: 2,
  NotFound: 3,
} as const;

export type CapabilityPolicyRecordKind = number;
export const CapabilityPolicyRecordKind = {
  Unspecified: 0,
  Policy: 1,
  ProviderBinding: 2,
} as const;

export type FailureCategory = number;
export const FailureCategory = {
  Unspecified: 0,
  LocalCancelled: 1,
  Deadline: 2,
  Transport: 3,
  Rpc: 4,
  Decode: 5,
  Limit: 6,
  InvalidRequest: 7,
} as const;

export type OutcomeKnowledge = number;
export const OutcomeKnowledge = {
  Unspecified: 0,
  NotDispatched: 1,
  Unknown: 2,
  Observed: 3,
} as const;

export interface ResourceBudget {
  readonly cpuFuel: bigint;
  readonly memoryBytes: bigint;
  readonly childCalls: number;
  readonly outboundRequests: number;
  readonly stateReadBytes: bigint;
  readonly stateWriteBytes: bigint;
  readonly blobReadBytes: bigint;
  readonly blobWriteBytes: bigint;
  readonly logBytes: bigint;
  readonly effectCount: number;
  readonly wallTimeLimitMillis?: bigint;
}

export interface ErrorDetail {
  readonly kind: string;
  readonly fields: Readonly<Record<string, string>>;
}

export interface PlatformError {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly detailItems: readonly ErrorDetail[];
}

export interface ObjectMetadata {
  readonly name: string;
  readonly tenant?: string;
  readonly namespace?: string;
  readonly labels: Readonly<Record<string, string>>;
  readonly annotations: Readonly<Record<string, string>>;
}

export interface PageRequest {
  readonly pageSize: number;
  readonly pageToken?: string;
}

export interface PageResponse {
  readonly nextPageToken?: string;
}

export interface AuditAck {
  readonly status: AuditAckStatus;
  readonly attemptSequence?: bigint;
}

export interface InvocationTarget {
  readonly tenant: string;
  readonly service: string;
  readonly contract: string;
  readonly function: string;
  readonly route?: string;
}

export interface InvokeRequest {
  readonly activationId?: string;
  readonly parentActivationId?: string;
  readonly rootActivationId?: string;
  readonly target?: InvocationTarget;
  readonly payload: Uint8Array;
  readonly mediaType: string;
  readonly deadlineUnixMillis?: bigint;
  readonly priority: number;
  readonly idempotencyKey?: string;
  readonly budget?: ResourceBudget;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface BudgetConsumption {
  readonly cpuFuel: bigint;
  readonly peakMemoryBytes: bigint;
  readonly wallTimeMicros: bigint;
  readonly childCalls: number;
  readonly outboundRequests: number;
  readonly stateReadBytes: bigint;
  readonly stateWriteBytes: bigint;
  readonly blobReadBytes: bigint;
  readonly blobWriteBytes: bigint;
  readonly logBytes: bigint;
  readonly effectCount: number;
}

export interface Success {
  readonly payload: Uint8Array;
  readonly mediaType: string;
  readonly committedStateVersion?: string;
  readonly effectIds: readonly string[];
  readonly metadata: Readonly<Record<string, string>>;
}

export interface DeclaredError {
  readonly code: string;
  readonly message: string;
  readonly payload: Uint8Array;
  readonly mediaType: string;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface InvokeResponse {
  readonly activationId: string;
  readonly revisionId: string;
  readonly releaseDigest: string;
  readonly routeGeneration: bigint;
  readonly success?: Success;
  readonly declaredError?: DeclaredError;
  readonly platformFailure?: PlatformError;
  readonly consumption?: BudgetConsumption;
  readonly publicationId?: string;
}

export interface CancelRequest {
  readonly activationId: string;
  readonly reason: string;
}

export interface CancelResponse {
  readonly disposition: CancelDisposition;
  readonly terminalState?: string;
}

export interface GetActivationRequest {
  readonly activationId: string;
}

export interface ActivationSuccessSummary {
  readonly committedStateVersion?: string;
  readonly effectIds: readonly string[];
  readonly metadata: Readonly<Record<string, string>>;
}

export interface ActivationStatus {
  readonly activationId: string;
  readonly phase: string;
  readonly terminalState?: string;
  readonly lastUpdatedUnixMillis: bigint;
  readonly metadata: Readonly<Record<string, string>>;
  readonly succeeded?: ActivationSuccessSummary;
  readonly declaredError?: DeclaredError;
  readonly platformFailure?: PlatformError;
  readonly finalConsumption?: BudgetConsumption;
  readonly terminalAtUnixMillis?: bigint;
}

export interface Policy {
  readonly id: string;
  readonly metadata?: ObjectMetadata;
  readonly document: string;
  readonly generation: bigint;
  readonly language: string;
  readonly recordKind: CapabilityPolicyRecordKind;
  readonly contentDigest: string;
  readonly revoked: boolean;
}

export interface ApplyPolicyRequest {
  readonly policy?: Policy;
  readonly expectedGeneration?: bigint;
  readonly operationId: string;
}

export interface CapabilityPolicyOperation {
  readonly operationId: string;
  readonly tenant: string;
  readonly id: string;
  readonly recordKind: CapabilityPolicyRecordKind;
  readonly generation: bigint;
  readonly contentDigest: string;
  readonly revoked: boolean;
}

export interface ApplyPolicyResponse {
  readonly policy?: Policy;
  readonly receipt?: CapabilityPolicyOperation;
}

export interface GetPolicyRequest {
  readonly id: string;
  readonly recordKind: CapabilityPolicyRecordKind;
}

export interface GetPolicyResponse {
  readonly policy?: Policy;
}

export interface GetPolicyOperationRequest {
  readonly operationId: string;
}

export interface GetPolicyOperationResponse {
  readonly receipt?: CapabilityPolicyOperation;
}

export interface ListPoliciesRequest {
  readonly recordKind: CapabilityPolicyRecordKind;
  readonly page?: PageRequest;
}

export interface ListPoliciesResponse {
  readonly policies: readonly Policy[];
  readonly catalogGeneration: bigint;
  readonly page?: PageResponse;
}

export interface CapabilityInspectionPolicy {
  readonly id: string;
  readonly revision: bigint;
  readonly digest: string;
}

export interface CapabilityBindingInspection {
  readonly definitionDigest?: string;
  readonly providerBinding?: CapabilityInspectionPolicy;
  readonly policies: readonly CapabilityInspectionPolicy[];
  readonly providerProfile: string;
  readonly providerConfigurationDigest: string;
  readonly providerConfigurationEpoch: bigint;
  readonly state: string;
}

export interface CapabilityDescriptor {
  readonly id: string;
  readonly contract: string;
  readonly provider: string;
  readonly operations: readonly string[];
  readonly attributes: Readonly<Record<string, string>>;
  readonly inspection?: CapabilityBindingInspection;
}

export interface ListCapabilitiesRequest {
  readonly contractPrefix?: string;
  readonly provider?: string;
  readonly page?: PageRequest;
  readonly deploymentId: string;
  readonly includeNodeUsage: boolean;
}

export interface CapabilityInspectionRevision {
  readonly deploymentId: string;
  readonly revisionId: string;
  readonly componentDigest: string;
  readonly publicationId?: string;
  readonly routeGeneration: bigint;
  readonly catalogTransaction: bigint;
}

export interface CapabilityResourceUsage {
  readonly scope: string;
  readonly counters: Readonly<Record<string, bigint>>;
  readonly unavailable: readonly string[];
}

export interface ListCapabilitiesResponse {
  readonly capabilities: readonly CapabilityDescriptor[];
  readonly page?: PageResponse;
  readonly revision?: CapabilityInspectionRevision;
  readonly tenantUsage?: CapabilityResourceUsage;
  readonly nodeUsage?: CapabilityResourceUsage;
  readonly state: string;
}

export interface CapabilityInspectionCeiling {
  readonly operations: number;
  readonly inputBytes: bigint;
  readonly outputBytes: bigint;
  readonly wallTimeMillis: bigint;
}

export interface PublicationRef {
  readonly id: string;
  readonly tenant: string;
}

export interface ReleaseSelector {
  readonly componentDigest?: string;
  readonly publication?: PublicationRef;
}

export interface PublicationIdentity {
  readonly publication: PublicationRef;
  readonly componentDigest: string;
  readonly packageDigest: string;
}

export interface CallOptions {
  readonly timeoutMillis?: bigint;
  readonly signal?: AbortSignal;
}

export interface RequestIdentity {
  readonly activationId?: string;
  readonly operationId?: string;
}

export interface ResponseMetadata {
  readonly identity: RequestIdentity;
  readonly outcome: OutcomeKnowledge;
  readonly auditAck?: AuditAck;
  readonly auditStatus?: string;
}

export interface ClientFailure {
  readonly category: FailureCategory;
  readonly message: string;
  readonly grpcStatus?: number;
  readonly platformError?: PlatformError;
  readonly dispatched: boolean;
  readonly outcome: OutcomeKnowledge;
  readonly identity: RequestIdentity;
  readonly auditAck?: AuditAck;
  readonly auditStatus?: string;
}

export interface ClientResponse<Response> {
  readonly value: Response;
  readonly metadata: ResponseMetadata;
}

export interface ClientProfile {
  invoke(request: InvokeRequest, options?: CallOptions): Promise<ClientResponse<InvokeResponse>>;
  cancel(request: CancelRequest, options?: CallOptions): Promise<ClientResponse<CancelResponse>>;
  getActivation(request: GetActivationRequest, options?: CallOptions): Promise<ClientResponse<ActivationStatus>>;
  getPolicy(request: GetPolicyRequest, options?: CallOptions): Promise<ClientResponse<GetPolicyResponse>>;
  listPolicies(request: ListPoliciesRequest, options?: CallOptions): Promise<ClientResponse<ListPoliciesResponse>>;
  listCapabilities(request: ListCapabilitiesRequest, options?: CallOptions): Promise<ClientResponse<ListCapabilitiesResponse>>;
  applyPolicy(request: ApplyPolicyRequest, options?: CallOptions): Promise<ClientResponse<ApplyPolicyResponse>>;
  getPolicyOperation(request: GetPolicyOperationRequest, options?: CallOptions): Promise<ClientResponse<GetPolicyOperationResponse>>;
}

export class ClientError extends Error {
  constructor(readonly failure: ClientFailure) {
    super(failure.message);
    this.name = "ClientError";
  }
}

export function parseU64Decimal(value: string): bigint {
  if (typeof value !== "string" || !/^(0|[1-9][0-9]{0,19})$/.test(value)) {
    throw new RangeError("invalid uint64 decimal");
  }
  const parsed = BigInt(value);
  if (parsed > 18446744073709551615n) throw new RangeError("uint64 overflow");
  return parsed;
}

export function formatU64Decimal(value: bigint): string {
  if (typeof value !== "bigint" || value < 0n || value > 18446744073709551615n) {
    throw new RangeError("invalid uint64 bigint");
  }
  return value.toString(10);
}
