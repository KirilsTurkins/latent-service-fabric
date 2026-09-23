import * as raw from 'latent:http/streaming@0.3.0';
import { Owner, drop } from './owner.js';
import { call } from './result.js';
export type { Request, Header, Method, HttpError } from 'latent:http/streaming@0.3.0';
export type Upload = Owner<raw.Upload, 'http-upload'>;
export type Body = Owner<raw.Body, 'http-body'>;
export type Chunk = Owner<raw.Chunk, 'http-chunk'>;
export type Response = Omit<raw.Response, 'body'> & { body: Body };
const errors: readonly raw.HttpError['tag'][] = ['invalid-url', 'invalid-request', 'permission-denied',
  'request-too-large', 'response-too-large', 'deadline-exceeded', 'cancelled', 'budget-exhausted',
  'dns-failed', 'tls-failed', 'connection-failed', 'unavailable', 'uncertain', 'invalid-state',
  'unexpected-eof', 'unsupported-encoding'];
function invoke<T>(operation: () => T) { return call<T, raw.HttpError>(operation, errors); }
export function open(request: raw.Request) {
  return invoke((): Upload => new Owner(raw.open(request), drop));
}
export function write(upload: Upload, bytes: Uint8Array) {
  return invoke(() => upload.borrow(value => raw.write(value, bytes)));
}
export function finish(upload: Upload) {
  return invoke((): Response => {
    const response = upload.consume(value => raw.finish(value));
    return { ...response, body: new Owner(response.body, drop) };
  });
}
export function read(body: Body, maximumBytes: number) {
  return invoke((): Chunk | undefined => body.borrow(value => {
    const chunk = raw.read(value, maximumBytes);
    return chunk === undefined ? undefined : new Owner(chunk, drop);
  }));
}
/** A chunk remains charged until close, including after materialization. */
export function chunkBytes(chunk: Chunk) { return invoke(() => chunk.borrow(raw.chunkBytes)); }
export function trailers(body: Body) { return invoke(() => body.borrow(raw.trailers)); }
export function abortUpload(upload: Upload) { return invoke(() => upload.consume(raw.abortUpload)); }
export function abortBody(body: Body) { return invoke(() => body.consume(raw.abortBody)); }
