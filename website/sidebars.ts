import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';
import {createRepositoryIndex} from './lib/repository.mjs';
import {buildSidebars} from './lib/navigation.mjs';

const sidebars: SidebarsConfig = buildSidebars(createRepositoryIndex().pages);

export default sidebars;
