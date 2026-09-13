/** Tenant must match authenticated scope; an ID alone grants no authority. */
export interface PublicationRef {
  readonly id: string;
  readonly tenant: string;
}

/** Exactly one selector is valid. Preserve present empty/both for rejection. */
export interface ReleaseSelector {
  readonly componentDigest?: string;
  readonly publication?: PublicationRef;
}

export interface PublicationIdentity {
  readonly publication: PublicationRef;
  readonly componentDigest: string;
  readonly packageDigest: string;
}
