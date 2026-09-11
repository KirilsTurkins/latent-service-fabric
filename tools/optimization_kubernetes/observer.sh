#!/bin/sh
# Fixed observer in the owned kind worker. Output is key<TAB>base64(raw bytes).
set -eu

number() { case "$1" in ''|*[!0-9]*) exit 64 ;; esac; [ "$1" -gt 0 ]; }
emit_file() {
    printf '%s\t' "$1"
    if [ -r "$2" ]; then
        [ "$(wc -c < "$2" 2>/dev/null || printf 0)" -le 65536 ] || exit 65
        head -c 65537 "$2" | base64 -w 0
    else
        printf '%s' '-'
    fi
    printf '\n'
}
emit_value() { printf '%s\t' "$1"; printf '%s' "$2" | base64 -w 0; printf '\n'; }
start_ticks() {
    line=$(cat "/proc/$1/stat")
    tail=${line##*) }
    set -- $tail
    shift 19
    printf '%s' "$1"
}
verify() {
    number "$1"
    case "$2" in ''|*[!a-f0-9]*) exit 64 ;; esac
    [ "${#2}" -eq 64 ] || exit 64
    number "$3"
    [ "$(start_ticks "$1")" = "$3" ] || exit 66
    grep -F "$2" "/proc/$1/cgroup" >/dev/null || exit 66
    [ "$(awk '/^NSpid:/ {print $NF}' "/proc/$1/status")" = 1 ] || exit 66
}
process() {
    prefix=$1
    pid=$2
    number "$pid"
    for name in stat status limits cgroup mountinfo; do
        emit_file "$prefix.$name" "/proc/$pid/$name"
    done
    for name in pid mnt net user; do
        emit_value "$prefix.ns.$name" "$(readlink "/proc/$pid/ns/$name")"
    done
    emit_file "$prefix.stat_after" "/proc/$pid/stat"
}

mode=$1
shift
case "$mode" in
    signal)
        [ "$#" -eq 4 ] || exit 64
        verify "$1" "$2" "$3"
        case "$4" in USR1|TERM) kill -s "$4" "$1" ;; *) exit 64 ;; esac
        ;;
    observe|client)
        [ "$#" -eq 3 ] || exit 64
        verify "$1" "$2" "$3"
        wrapper=$1
        leaf=$(awk -F: '$1 == "0" {print $3}' "/proc/$wrapper/cgroup")
        case "$leaf" in /*) ;; *) exit 66 ;; esac
        case "$leaf" in *..*) exit 66 ;; esac
        directory=/sys/fs/cgroup$leaf
        emit_value wrapper.pid "$wrapper"
        process wrapper "$wrapper"
        if [ "$mode" = observe ]; then
            children=$(cat "$directory/cgroup.procs")
            child=''
            for item in $children; do
                if [ "$item" != "$wrapper" ]; then
                    [ -z "$child" ] || exit 66
                    child=$item
                fi
            done
            number "$child"
            emit_value child.pid "$child"
            process child "$child"
        fi
        index=0
        while :; do
            [ "$index" -lt 16 ] || exit 65
            emit_value "cgroup.$index.path" "$directory"
            for name in cpu.max memory.max memory.swap.max pids.max pids.current; do
                emit_file "cgroup.$index.$name" "$directory/$name"
            done
            [ "$directory" != /sys/fs/cgroup ] || break
            directory=${directory%/*}
            index=$((index + 1))
        done
        verify "$1" "$2" "$3"
        ;;
    *) exit 64 ;;
esac
