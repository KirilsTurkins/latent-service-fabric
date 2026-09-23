/** Tenant must match authenticated scope; an ID alone grants no authority. */
export interface PublicationRef {
  readonly id: string;
  readonly tenant: string;
}

export interface PublicationIdentity {
  readonly publication: PublicationRef;
  readonly componentDigest: string;
  readonly packageDigest: string;
}
