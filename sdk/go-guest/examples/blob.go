package export_tests_local_blobs_api

import (
	blob "wit_component/lsf/blob"
	raw "wit_component/latent_blob_blob"
	wit "go.bytecodealliance.org/pkg/wit/types"
)

func Run(which uint32, _ string, handle uint64) uint64 {
	// Raw generated access is used only by the stale-host-handle negative cases.
	if which == 2 || which == 4 {
		if which == 2 {
			handle = raw.Create("text/plain", wit.Some[uint64](0)).Ok()
			if !raw.Close(handle).Ok() { panic("writer did not close") }
		}
		r := raw.Write(handle, 0, []byte{})
		if r.IsErr() && r.Err().Tag() == raw.BlobErrorInvalidState { return 10 }
		if r.IsErr() && r.Err().Tag() == raw.BlobErrorPermissionDenied { return 11 }
		panic("closed or foreign handle accepted")
	}
	if which == 5 { return raw.Create("text/plain", wit.Some[uint64](0)).Ok() }
	writer := blob.Create("text/plain", wit.Some[uint64](4)).Ok()
	if which == 1 { return 1 } // charged until activation cleanup; no hidden task
	if writer.Write(0, []byte("data")).Ok() != 4 { panic("short blob write") }
	reader := blob.Open(writer.Seal().Ok()).Ok()
	chunk := reader.Read(0, 4).Ok()
	defer chunk.Close()
	if !reader.Close().Ok() { panic("reader did not close") }
	if which == 3 { return 3 }
	bytes := chunk.Bytes().Ok()
	if string(bytes) != "data" { panic("blob bytes changed") }
	return uint64(len(bytes))
}
