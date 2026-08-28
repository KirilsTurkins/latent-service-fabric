export interface ResourceBudget {
  readonly cpuFuel: bigint;
  readonly memoryBytes: bigint;
  /** Relative to admission; undefined adds no ceiling and 0n grants no time. */
  readonly wallTimeLimitMillis?: bigint;
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
  readonly details: readonly ErrorDetail[];
}

export interface ErrorDetail {
  readonly kind: string;
  readonly fields: Readonly<Record<string, string>>;
}

export interface DeclaredError {
  readonly code: string;
  readonly message: string;
  readonly payload: Uint8Array;
  readonly mediaType: string;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface InvocationReceipt {
  readonly activationId: string;
  readonly revisionId: string;
  readonly releaseDigest: string;
  readonly routeGeneration: bigint;
  readonly consumption: BudgetConsumption;
}

export type InvocationOutcome =
  | { readonly kind: "success"; readonly response: InvokeResponse }
  | {
      readonly kind: "declared-error";
      readonly receipt: InvocationReceipt;
      readonly error: DeclaredError;
    }
  | {
      readonly kind: "platform-failure";
      readonly receipt: InvocationReceipt;
      readonly error: PlatformFailure;
    };

export type CancelDisposition = "accepted" | "already-terminal" | "not-found";

export interface CancelResponse {
  readonly disposition: CancelDisposition;
  readonly terminalState?: string;
}

export type RetainedInvocationOutcome =
  | {
      readonly kind: "success";
      readonly committedStateVersion?: string;
      readonly effectIds: readonly string[];
      readonly metadata: Readonly<Record<string, string>>;
    }
  | { readonly kind: "declared-error"; readonly error: DeclaredError }
  | { readonly kind: "platform-failure"; readonly error: PlatformFailure };

export interface ActivationStatus {
  readonly activationId: string;
  readonly phase: string;
  readonly terminalState?: string;
  readonly terminalOutcome?: RetainedInvocationOutcome;
  readonly finalConsumption?: BudgetConsumption;
  readonly lastUpdatedUnixMillis: bigint;
  readonly terminalAtUnixMillis?: bigint;
  readonly metadata: Readonly<Record<string, string>>;
}

export interface LatentClient {
  invoke(request: InvokeRequest): Promise<InvocationOutcome>;
  cancel(activationId: string, reason: string): Promise<CancelResponse>;
  getActivation(activationId: string): Promise<ActivationStatus>;
}

export interface GuestContext {
  readonly activationId: string;
  readonly rootActivationId: string;
  readonly parentActivationId?: string;
  readonly deadlineUnixMillis?: bigint;
  readonly remainingBudget: ResourceBudget;
  readonly metadata: Readonly<Record<string, string>>;
}
