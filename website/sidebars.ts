import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';
import {prepare} from './lib/prepare.mjs';
import {buildSidebars} from './lib/navigation.mjs';

const sidebars: SidebarsConfig = buildSidebars(prepare().index.pages);

export default sidebars;
