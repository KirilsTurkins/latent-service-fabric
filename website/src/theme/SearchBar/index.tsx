import React, {useEffect, useState} from 'react';
import Link from '@docusaurus/Link';
import {useLocation} from '@docusaurus/router';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import {channelFromPath} from '../../../lib/search.mjs';

export default function SearchBar(): React.ReactNode {
  const {siteConfig} = useDocusaurusContext();
  const location = useLocation();
  const publications = siteConfig.customFields?.publications as {version: string}[];
  const channels = ['development', ...publications.map(item => item.version)];
  const fromPath = channelFromPath(location.pathname, siteConfig.baseUrl, channels);
  const [remembered, remember] = useState('development');
  useEffect(() => {
    try {
      const stored = localStorage.getItem('lsf-documentation-channel');
      if (fromPath) { localStorage.setItem('lsf-documentation-channel', fromPath); remember(fromPath); }
      else if (stored && channels.includes(stored)) remember(stored);
    } catch { /* A version-labelled URL works without browser storage. */ }
  }, [fromPath, publications]);
  return <Link className="navbar__link" to={`/search/?version=${encodeURIComponent(fromPath ?? remembered)}`} aria-label="Search documentation">Search</Link>;
}
