import { connect, type ClientHttp2Session } from "node:http2";
import { createConnection, type Socket } from "node:net";
import { performance } from "node:perf_hooks";
import { type ClientLimits } from "./config.js";

export class Channel {
  #session: ClientHttp2Session | undefined;
  #socket: Socket | undefined;
  #timer: NodeJS.Timeout | undefined;
  #failed = false;
  #closed = false;

  constructor(
    readonly endpoint: string, readonly host: string, readonly port: number,
    readonly limits: ClientLimits, readonly retired: () => void,
  ) {}

  get closed(): boolean { return this.#closed; }
  get sessions(): number { return this.#session === undefined ? 0 : 1; }
  get sockets(): number { return this.#socket === undefined ? 0 : 1; }

  get(deadline: number): ClientHttp2Session {
    if (this.#closed || this.#failed) throw new Error("client channel is closed");
    if (this.#session) return this.#session;
    try {
      const session = connect(this.endpoint, {
        createConnection: () => {
          if (this.#socket) throw new Error("client connection already exists");
          const socket = createConnection({ host: this.host, port: this.port, autoSelectFamily: false, family: this.host === "::1" ? 6 : 4 });
          this.#socket = socket;
          socket.setNoDelay(true);
          socket.on("error", () => this.fail());
          socket.once("close", () => {
            this.#socket = undefined;
            this.clearTimer();
            this.retired();
          });
          socket.once("connect", () => {
            if (socket.remoteAddress !== this.host || socket.remotePort !== this.port) this.fail();
          });
          return socket;
        },
        settings: { enablePush: false, initialWindowSize: 32768, maxHeaderListSize: 16384, headerTableSize: 4096, maxFrameSize: 16384, maxConcurrentStreams: this.limits.maximumCalls },
        peerMaxConcurrentStreams: this.limits.maximumCalls,
        maxReservedRemoteStreams: 0,
        maxSessionMemory: 4,
        maxHeaderListPairs: 32,
        maxSendHeaderBlockLength: 8192,
        maxOutstandingPings: 1,
        maxSettings: 12,
      });
      this.#session = session;
      session.on("error", () => this.fail());
      session.on("frameError", () => this.fail());
      session.on("goaway", () => this.fail());
      session.on("stream", (stream) => { stream.destroy(); this.fail(); });
      session.once("connect", () => {
        this.clearTimer();
        if (!this.#closed && !this.#failed) session.setLocalWindowSize(128 * 1024);
      });
      session.once("close", () => {
        this.#session = undefined;
        this.#failed = true;
        this.clearTimer();
        this.retired();
      });
      this.#timer = setTimeout(() => this.fail(), Math.max(1, Math.ceil(Math.min(deadline - performance.now(), this.limits.connectTimeoutMillis))));
      return session;
    } catch (error) {
      this.fail();
      throw error;
    }
  }

  close(): void {
    this.#closed = true;
    this.fail();
  }

  private fail(): void {
    this.#failed = true;
    this.clearTimer();
    this.#session?.destroy();
    this.#socket?.destroy();
  }

  private clearTimer(): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = undefined;
  }
}
