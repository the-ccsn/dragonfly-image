default:
    @just --list

check:
    mkdir -p .tmp
    shellcheck dragonfly.sh
    actionlint
    gcc -O2 -Wall -Wextra -Werror -march=x86-64 cpu-mode.c -o .tmp/dragonfly-cpu-mode

test-image:
    docker build --target test -t dragonfly-auto-test .

build:
    docker build --target runtime -t dragonfly-auto .
