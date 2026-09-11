# User-space state pager

Investigate Linux `userfaultfd` for page-on-demand state materialization and dirty-page delta capture. The planned portable state model uses explicit capability calls; Phase 1 is stateless and implements neither those providers nor this pager. Arbitrary language heaps are out of scope unless their representation is stable and explicitly designed for persistence.
