package export_tests_local_secrets_api

import secrets "wit_component/lsf/secrets"

func Run(_ uint32, reference string, _ uint64) uint64 {
	r := secrets.Read(reference)
	if r.IsErr() {
		switch r.Err().Tag() {
		case secrets.SecretErrorPermissionDenied: return 10
		case secrets.SecretErrorNotFound: return 11
		case secrets.SecretErrorExpired: return 12
		case secrets.SecretErrorUnavailable: return 13
		default: panic("unknown secret error")
		}
	}
	secret := r.Ok()
	defer secret.Close()
	var borrowed []byte
	var count uint64
	secret.WithBytes(func(bytes []byte) { borrowed = bytes; count = uint64(len(bytes)) })
	secret.Metadata()
	secret.Close()
	// Test-only retained alias proves explicit Close erased this allocation.
	for _, value := range borrowed { if value != 0 { panic("secret not erased") } }
	return count
}
