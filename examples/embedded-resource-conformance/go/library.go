package library

import data "outside.example.test/embedded-resource-data"

var visits uint32

func Run(mode string) string {
    visits++
    if visits != 1 { panic("resource library state survived retirement") }
    return data.Read(mode) + "|fresh=1"
}
