/** lsf-node-net-tcp-v1: finite activation-local TCP API, not a full Node host.
 * Requires the exact stream interface/runtime and independently granted TCP
 * endpoint. Root completion requires acknowledged close, not end/destroy initiation.
 * No TLS/DNS API, listeners, descriptors, address export, persistent idle pools,
 * custom lookup, family fallback, proxy or arbitrary socket options.
 */
import type {Buffer} from 'node:buffer';
type BufferEncoding = NonNullable<Parameters<Buffer['toString']>[0]>;
export interface SocketOptions {allowHalfOpen?: boolean; highWaterMark?: number;}
export interface TcpConnectOptions {host?: string; port: number | string;}
export interface SocketError extends Error {
  code: string; syscall: string; streamCode?: string;
  acceptedPrefixBytes: number; mayHaveApplied: boolean;
  nativeAcceptedPrefixBytes?: number; nativeMayHaveApplied?: boolean;
  cause?: unknown;
}
export interface SocketEvents {
  connect: []; ready: []; data: [Buffer]; drain: []; end: []; finish: [];
  error: [Error]; close: [boolean]; timeout: [];
}
export class Socket {
  constructor(options?: SocketOptions);
  connect(options: TcpConnectOptions, listener?: () => void): this;
  connect(port: number | string, host?: string, listener?: () => void): this;
  connect(port: number | string, listener?: () => void): this;
  on<K extends keyof SocketEvents>(event: K, listener: (...args: SocketEvents[K]) => void): this;
  addListener<K extends keyof SocketEvents>(event: K, listener: (...args: SocketEvents[K]) => void): this;
  once<K extends keyof SocketEvents>(event: K, listener: (...args: SocketEvents[K]) => void): this;
  off<K extends keyof SocketEvents>(event: K, listener: (...args: SocketEvents[K]) => void): this;
  removeListener<K extends keyof SocketEvents>(event: K, listener: (...args: SocketEvents[K]) => void): this;
  removeAllListeners(event?: keyof SocketEvents): this;
  listenerCount(event: keyof SocketEvents): number;
  emit<K extends keyof SocketEvents>(event: K, ...args: SocketEvents[K]): boolean;
  write(data: string | Uint8Array, callback?: (error?: Error) => void): boolean;
  write(data: string, encoding: BufferEncoding, callback?: (error?: Error) => void): boolean;
  end(callback?: () => void): this;
  end(data: string | Uint8Array, callback?: () => void): this;
  end(data: string, encoding: BufferEncoding, callback?: () => void): this;
  destroy(error?: Error): this;
  pause(): this; resume(): this;
  setTimeout(milliseconds: number, callback?: () => void): this;
  readonly connecting: boolean; readonly pending: boolean; readonly destroyed: boolean;
  readonly closed: boolean; readonly readable: boolean; readonly writable: boolean;
  readonly readableEnded: boolean; readonly writableEnded: boolean; readonly writableFinished: boolean;
  readonly writableLength: number; readonly writableHighWaterMark: number;
  readonly bytesRead: number; readonly bytesWritten: number;
  readonly timeout: number | undefined; readonly remotePort: number | undefined;
  readonly readyState: 'opening' | 'open' | 'readOnly' | 'writeOnly' | 'closed';
}
export function createConnection(options: TcpConnectOptions, listener?: () => void): Socket;
export function createConnection(port: number | string, host?: string, listener?: () => void): Socket;
export function createConnection(port: number | string, listener?: () => void): Socket;
export const connect: typeof createConnection;
declare const net: {Socket: typeof Socket; createConnection: typeof createConnection; connect: typeof connect;};
export default net;
