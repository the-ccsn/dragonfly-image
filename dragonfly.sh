#!/bin/sh
set -eu

detected=$(dragonfly-cpu-mode)
case "${DRAGONFLY_CPU_MODE:-auto}" in
    auto) mode=$detected ;;
    generic) mode=generic ;;
    avx2)
        if [ "$detected" != avx2 ]; then
            echo "dragonfly: this CPU/OS cannot run the AVX2 build" >&2
            exit 1
        fi
        mode=avx2
        ;;
    *)
        echo "dragonfly: DRAGONFLY_CPU_MODE must be auto, generic, or avx2" >&2
        exit 1
        ;;
esac
echo "dragonfly: selected $mode build" >&2
exec "/usr/local/lib/dragonfly/dragonfly-$mode" "$@"

