import {fileURLToPath} from 'node:url';
import {replaceBundledIpAddress, replaceBundledUndici, replaceBundledBraceExpansion} from '../lib/package-manager-security.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
replaceBundledIpAddress(root);
replaceBundledUndici(root);
replaceBundledBraceExpansion(root);
// This verifies every locked dependency and executes the security regressions
// against the package actually resolved by npm, before npm performs any work.
await import('./check-package-manager.mjs');
