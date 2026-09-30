import {fileURLToPath} from 'node:url';
import {replaceBundledIpAddress, replaceBundledUndici} from '../lib/package-manager-security.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
replaceBundledIpAddress(root);
replaceBundledUndici(root);
// This verifies every locked dependency and executes the NAT64 regression
// against the package actually resolved by npm, before npm performs any work.
await import('./check-package-manager.mjs');
