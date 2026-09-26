import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';
import {prepare} from './lib/prepare.mjs';
import {buildSidebars} from './lib/navigation.mjs';

const sidebars: SidebarsConfig = buildSidebars(prepare().index.pages);

// Start at the decision page, then the runnable path; preserve other groups.
const startOrder = ['start/index', 'start/application-development', 'start/developer-setup', 'start/first-node'];
const rank = (id: string) => startOrder.includes(id) ? startOrder.indexOf(id) : startOrder.length;
(sidebars.start as Array<{type: 'doc'; id: string; label: string}>).sort((left, right) => rank(left.id) - rank(right.id));

export default sidebars;
