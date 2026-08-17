export interface ResourceBudget {
  readonly cpuFuel: bigint;
  readonly memoryBytes: bigint;
  readonly wallDeadlineUnixMillis?: bigint;
  readonly childCalls: number;
  readonly outboundRequests: number;
  readonly stateReadBytes: bigint;
  readonly stateWriteBytes: bigint;
  readonly blobReadBytes: bigint;
  readonly blobWriteBytes: bigint;
  readonly logBytes: bigint;
  readonly effectCount: number;
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

export interface InvocationTarget {
  readonly tenant: string;
  readonly service: string;
  readonly contract: string;
  readonly function: string;
  readonly route?: string;
}

export interface InvokeOptions {
  readonly deadlineUnixMillis?: bigint;
  readonly priority: number;
  readonly idempotencyKey?: string;
  readonly budget: ResourceBudget;
  readonly metadata: Readonly<Record<string, string>>;
  readonly signal?: AbortSignal;
}

export interface InvokeRequest {
  readonly target: InvocationTarget;
  readonly payload: Uint8Array;
  readonly mediaType: string;
  readonly options: InvokeOptions;
}

export interface InvokeResponse {
  readonly activationId: string;
  readonly revisionId: string;
  readonly releaseDigest: string;
  readonly routeGeneration: bigint;
  readonly payload: Uint8Array;
  readonly mediaType: string;
  readonly committedStateVersion?: string;
  readonly effectIds: readonly string[];
  readonly consumption: BudgetConsumption;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface PlatformFailure {
  readonly code: string;
  readonly message: string;
  readonly retryable: boolean;
  readonly details: Readonly<Record<string, string>>;
}

export interface LatentClient {
  invoke(request: InvokeRequest): Promise<InvokeResponse>;
  cancel(activationId: string, reason: string): Promise<void>;
}

export interface GuestContext {
  readonly activationId: string;
  readonly rootActivationId: string;
  readonly parentActivationId?: string;
  readonly deadlineUnixMillis?: bigint;
  readonly remainingBudget: ResourceBudget;
  readonly metadata: Readonly<Record<string, string>>;
}
