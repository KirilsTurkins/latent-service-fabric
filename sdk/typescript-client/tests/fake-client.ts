// Test-only server policy and interface fixture. This is not an SDK transport.
import type {
  ActivationStatus, BudgetConsumption, CancelResponse, InvocationOutcome,
  InvokeRequest, LatentClient, PlatformFailure,
} from "../src/index.js";

export class TransportFailure extends Error {}
export class ServerRejection extends Error {}

const consumption: BudgetConsumption = {
  cpuFuel: 0n, peakMemoryBytes: 0n, wallTimeMicros: 0n, childCalls: 0,
  outboundRequests: 0, stateReadBytes: 0n, stateWriteBytes: 0n,
  blobReadBytes: 0n, blobWriteBytes: 0n, logBytes: 0n, effectCount: 0,
};
const cancelled: PlatformFailure = {
  code: "cancelled", message: "fixture cancellation", retryable: false, details: [],
};

interface Entry {
  readonly root: string;
  readonly parent: string | undefined;
  status: ActivationStatus;
  cancelRequested: boolean;
  readonly resolve: (outcome: InvocationOutcome) => void;
  readonly reject: (error: Error) => void;
}

export class FakeClient implements LatentClient {
  readonly requests: InvokeRequest[] = [];
  failNextCancel = false;
  private readonly entries = new Map<string, Entry>();

  invoke(request: InvokeRequest): Promise<InvocationOutcome> {
    this.requests.push(request);
    const identities = [request.activationId, request.rootActivationId, request.parentActivationId];
    if (identities.some(value => value === "") ||
        (request.parentActivationId !== undefined && request.rootActivationId === undefined)) {
      return Promise.reject(new ServerRejection("invalid-argument"));
    }
    // Assignment belongs to this fake server, after observing the unchanged request.
    const id = request.activationId ?? `server-assigned-${this.requests.length}`;
    if (this.entries.has(id)) return Promise.reject(new ServerRejection("already-exists"));
    return new Promise<InvocationOutcome>((resolve, reject) => {
      this.entries.set(id, {
        root: request.rootActivationId ?? id, parent: request.parentActivationId,
        status: { activationId: id, phase: "running", lastUpdatedUnixMillis: 1n, metadata: {} },
        cancelRequested: false, resolve, reject,
      });
    });
  }

  async cancel(id: string, _reason: string): Promise<CancelResponse> {
    if (this.failNextCancel) {
      this.failNextCancel = false;
      throw new TransportFailure("cancel transport unavailable");
    }
    const entry = this.entries.get(id);
    if (!entry) return { disposition: "not-found" };
    if (entry.status.terminalState !== undefined) {
      return { disposition: "already-terminal", terminalState: entry.status.terminalState };
    }
    entry.cancelRequested = true;
    return { disposition: "accepted" };
  }

  async getActivation(id: string): Promise<ActivationStatus> {
    const entry = this.entries.get(id);
    if (!entry) throw new ServerRejection("not-found");
    return entry.status;
  }

  lineage(id: string): { root: string; parent: string | undefined } {
    const entry = this.entries.get(id);
    if (!entry) throw new Error("missing fixture activation");
    return { root: entry.root, parent: entry.parent };
  }

  finish(id: string, loseResponse = false): void {
    const entry = this.entries.get(id);
    if (!entry) throw new Error("missing fixture activation");
    const terminal = entry.cancelRequested ? "cancelled" : "completed";
    entry.status = {
      activationId: id, phase: entry.cancelRequested ? "running" : "committed", terminalState: terminal,
      terminalOutcome: entry.cancelRequested
        ? { kind: "platform-failure", error: cancelled }
        : { kind: "success", effectIds: [], metadata: {} },
      finalConsumption: consumption, lastUpdatedUnixMillis: 2n, terminalAtUnixMillis: 2n, metadata: {},
    };
    if (loseResponse) {
      entry.reject(new TransportFailure("invoke response lost after completion"));
    } else if (entry.cancelRequested) {
      entry.resolve({
        kind: "platform-failure", error: cancelled,
        receipt: { activationId: id, revisionId: "r", releaseDigest: "d", routeGeneration: 1n, consumption },
      });
    } else {
      entry.resolve({ kind: "success", response: {
        activationId: id, revisionId: "r", releaseDigest: "d", routeGeneration: 1n,
        payload: new Uint8Array(), mediaType: "application/octet-stream",
        effectIds: [], consumption, metadata: {},
      } });
    }
  }
}
