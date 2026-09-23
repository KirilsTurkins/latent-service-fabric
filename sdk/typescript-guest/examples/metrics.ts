import type * as Contract from '../generated/interfaces/tests-metrics-api.js';
import * as metrics from '../vendor/lsf/sdk/typescript-guest/capabilities/metrics.js';
import { unwrap } from '../vendor/lsf/sdk/typescript-guest/capabilities/result.js';
export const api: typeof Contract = {
  run(which, name) {
    const kind = (['counter', 'up-down-counter', 'gauge', 'histogram'] as const)[which];
    if (kind === undefined) throw new Error('unknown-metric-kind');
    const result = metrics.emit({ name, kind, value: 2, unit: '1', attributes: [['region', 'east']] });
    if (result.tag === 'err') return ({ 'invalid-name': 10n, 'budget-exhausted': 11n, unavailable: 12n })[result.val.tag];
    return unwrap(result) ? 1n : 0n;
  },
};
