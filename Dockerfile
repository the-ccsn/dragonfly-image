# syntax=docker/dockerfile:1
FROM ghcr.io/romange/ubuntu-dev:20-gcc14 AS source
ARG DRAGONFLY_VERSION=v1.40.1
ARG DRAGONFLY_COMMIT=434478e00c366c711985d0b3269023fc39db8ad1
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/dragonflydb/dragonfly.git \
    && git fetch --depth=1 origin "refs/tags/${DRAGONFLY_VERSION}" \
    && git checkout --detach FETCH_HEAD \
    && test "$(git rev-parse HEAD)" = "$DRAGONFLY_COMMIT" \
    && git submodule update --init --recursive --depth=1

FROM source AS generic
ARG BUILD_JOBS=2
RUN make configure RELEASE_DIR=build-generic \
      HELIO_MARCH_OPT="-march=x86-64 -mtune=generic" WITH_SIMSIMD=OFF \
    && cmake --build build-generic --target dragonfly --parallel "$BUILD_JOBS" \
    && strip --strip-debug build-generic/dragonfly
# Lua's independent Makefile defaults to Sandy Bridge and ignores HELIO_MARCH_OPT.
# Rebuild every Lua object, install its archive, and relink the baseline binary.
RUN cd build-generic/third_party/lua \
    && touch ./*.c \
    && make all OPTFLAGS="-march=x86-64 -mtune=generic" \
    && cp liblua.a /src/build-generic/third_party/libs/lua/lib/liblua.a \
    && cd /src \
    && cmake --build build-generic --target dragonfly --parallel "$BUILD_JOBS" \
    && strip --strip-debug build-generic/dragonfly
COPY cpu-mode.c /tmp/cpu-mode.c
RUN gcc -O2 -Wall -Wextra -Werror -march=x86-64 -mtune=generic \
      /tmp/cpu-mode.c -o /tmp/dragonfly-cpu-mode

FROM source AS avx2
ARG BUILD_JOBS=2
RUN make configure RELEASE_DIR=build-avx2 \
      HELIO_MARCH_OPT="-march=x86-64-v3 -mtune=generic" WITH_SIMSIMD=ON \
    && cmake --build build-avx2 --target dragonfly --parallel "$BUILD_JOBS" \
    && strip --strip-debug build-avx2/dragonfly

FROM ubuntu:22.04 AS runtime
ARG DRAGONFLY_VERSION=v1.40.1
ARG DRAGONFLY_COMMIT=434478e00c366c711985d0b3269023fc39db8ad1
LABEL org.opencontainers.image.source="https://github.com/the-ccsn/dragonfly-image" \
      org.opencontainers.image.version="$DRAGONFLY_VERSION" \
      dev.ccsn.dragonfly.upstream-revision="$DRAGONFLY_COMMIT"
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates redis-tools tini util-linux net-tools netcat-openbsd \
    && groupadd -r -g 999 dfly && useradd -r -g dfly -u 999 dfly \
    && mkdir /data && chown dfly:dfly /data
COPY --from=generic /src/build-generic/dragonfly /usr/local/lib/dragonfly/dragonfly-generic
COPY --from=avx2 /src/build-avx2/dragonfly /usr/local/lib/dragonfly/dragonfly-avx2
COPY --from=generic /tmp/dragonfly-cpu-mode /usr/local/bin/dragonfly-cpu-mode
COPY --from=source /src/tools/docker/entrypoint.sh /usr/local/bin/entrypoint.sh
COPY --from=source /src/tools/docker/healthcheck.sh /usr/local/bin/healthcheck.sh
COPY --from=source /src/LICENSE.md /usr/share/doc/dragonfly/LICENSE.md
COPY --chmod=755 dragonfly.sh /usr/local/bin/dragonfly
WORKDIR /data
VOLUME /data
EXPOSE 6379
HEALTHCHECK CMD /usr/local/bin/healthcheck.sh
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/entrypoint.sh"]
CMD ["dragonfly", "--logtostderr"]

# Pin a recent static user-mode emulator without changing production libraries.
FROM ubuntu:22.04 AS emulator
ADD --checksum=sha256:8e7d8f4c0c7809fc3fea0085199fd6b16f671e7c73d9bf6bec711e1cb535920a https://github.com/tonistiigi/binfmt/releases/download/deploy/v10.2.3-68/qemu_v10.2.3_linux-amd64.tar.gz /tmp/qemu.tar.gz
RUN tar -xzf /tmp/qemu.tar.gz -C /usr/local/bin qemu-x86_64

# Test the production libraries with a newer statically linked emulator.
FROM runtime AS test
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3
COPY --from=emulator /usr/local/bin/qemu-x86_64 /usr/local/bin/qemu-x86_64
COPY scripts/test-image.py /tests/test-image.py
RUN python3 /tests/test-image.py
