import * as raw from 'latent:telemetry/custom@0.1.0';
import { call } from './result.js';
export type { Metric, MetricKind, TelemetryError } from 'latent:telemetry/custom@0.1.0';
const errors: readonly raw.TelemetryError['tag'][] = ['invalid-name', 'budget-exhausted', 'unavailable'];
export function emit(metric: raw.Metric) { return call<boolean, raw.TelemetryError>(() => raw.emitMetric(metric), errors); }
