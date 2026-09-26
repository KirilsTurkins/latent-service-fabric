import * as raw from 'latent:http/client@0.2.0';
import { call } from './result.js';
export type { Request, Response, Header, Method, HttpError } from 'latent:http/client@0.2.0';
const errors: readonly raw.HttpError['tag'][] = ['invalid-url', 'invalid-request', 'permission-denied',
  'request-too-large', 'response-too-large', 'deadline-exceeded', 'cancelled', 'budget-exhausted',
  'dns-failed', 'tls-failed', 'connection-failed', 'unavailable', 'uncertain'];

/** One authorized, budgeted host operation; never automatically retried. */
export function send(request: raw.Request) {
  return call<raw.Response, raw.HttpError>(() => raw.send(request), errors);
}
