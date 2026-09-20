# Theme and illustration qualification, 2026-09-20

The tested source is `499a6db25d8ed178f71a47749f17117ad773c0c7`, including
development through `8d0db1055857e18aca2e05aef2f25728ec2094bd`. This directory
retains observations of that source; adding evidence does not relabel the run.

Node 24.19.0 and npm 12.0.1 passed website check/typecheck, 35 unit tests
(one Windows file-symlink prerequisite skipped), both production builds,
`test:build` and `test:theme`. [Build evidence](build.json) records 185 rendered
pages and 13,338 checked links per base path with no browser errors.
[Theme evidence](theme.json) records 128 token pairings, rendered text/control
contrast, hover/focus, first paint, 26 keyboard stops per mode, responsive
navigation, Mermaid, and historical/presentation SVG comparisons. Four Python
illustration tests and the palette check passed; all five historical hashes and
the inventoried legacy Wiki blobs remain unchanged.

[Native zoom evidence](native-zoom.json) separately uses Chromium
153.0.8010.47 on Linux, at both `/` and `/latent-service-fabric/`. An ephemeral
review extension called `chrome.tabs.setZoom(tab.id, 2)` and read back the native
zoom value. The browser changed from 1280 CSS pixels at DPR 1 to 640 CSS pixels
at DPR 2; document width remained 640. Keyboard activation and mobile navigation
passed in light and dark modes without browser errors. This exercises native
browser zoom, independently of the original viewport/DPR approximation.

Visual review of the retained [dark gallery](project-dark-gallery.png),
[light mobile page](project-light-mobile.png), and native 200% views in
[light](project-light-native-zoom-200.png) and
[dark](project-dark-native-zoom-200.png) found legible headings, callouts and
controls, clear keyboard focus, and no clipped reading content. Wide code and
tables keep their own horizontal scrolling; diagrams expose full-size views.
Status icons/labels remain distinct alongside color.

These observations satisfy the scoped theme and illustration review for #349
and #350. They do not establish screen-reader or all-browser certification,
complete guide coverage, Wiki migration, release versioning or Pages deployment.
Those remain separate requirements of #345. Native OS select popups and physical
assistive-technology testing were not performed.
