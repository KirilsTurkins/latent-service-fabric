package export_tests_local_api

import wit "go.bytecodealliance.org/pkg/wit/types"

func Answer() uint32 { return 42 }
func Fail() wit.Result[uint32,string] { return wit.Err[uint32,string]("declared application failure") }
func Spin() uint32 { for {} }
