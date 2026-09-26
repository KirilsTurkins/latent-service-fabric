package export_tests_random_api

import random "wit_component/lsf/random"

func Run(which uint32, _ string, _ uint64) uint64 {
	switch which {
	case 0:
		return uint64(len(random.Bytes(32).Ok()))
	case 1:
		random.U64Value().Ok()
		return 8
	case 2:
		if random.Bytes(^uint32(0)).Err().Tag() != random.RandomErrorInvalidLength {
			panic("random length changed")
		}
		return 10
	default:
		panic("unknown random probe")
	}
}
