# Dragonfly with automatic CPU selection

`ghcr.io/the-ccsn/dragonfly` contains two builds of the same pinned Dragonfly
source revision. A baseline x86-64 launcher chooses the build before Dragonfly
starts:

| CPU and OS capabilities | Build |
| --- | --- |
| x86-64-v3, including usable AVX register state | AVX2 optimized |
| Older x86-64 CPUs, including Xeon E5520 (Nehalem) | Generic, without AVX |

The generic build uses `-march=x86-64 -mtune=generic` and disables optional
SimSIMD. Lua has its own Makefile with a Sandy Bridge default; the generic stage
rebuilds every Lua object with baseline flags and relinks Dragonfly.
The optimized build uses `-march=x86-64-v3 -mtune=generic`. This is a
custom compatibility build, not an upstream hardware support guarantee.
Both builds retain the same Redis API, authentication, and snapshot format.

## Dragonfly Operator

Keep the existing Operator. Set `spec.image` on a Dragonfly resource, or set the
Operator chart's `dragonflyImage` default, to the published image with its digest:

```yaml
spec:
  image: ghcr.io/the-ccsn/dragonfly:v1.40.1-auto-<commit12>@sha256:<digest>
```

Existing arguments, Secret references, probes, and `/data` mounts continue to use
the upstream entrypoint. The launcher uses `exec` to preserve signal delivery.
Only `linux/amd64` is published. There is no CPU-specific node selector.

`DRAGONFLY_CPU_MODE` defaults to `auto`. Set it to `generic` to disable the
optimized build on every CPU. `avx2` requires the full x86-64-v3 feature set and
fails clearly when the CPU or OS does not support it. Invalid values fail startup.
Selection is made at startup; a process does not retry another binary after a crash.

## Build and release

The GitHub Actions workflow builds and tests every pull request. Main-branch
pushes and manual runs publish only after the tests pass. No extra registry secret
is needed; the workflow uses `GITHUB_TOKEN` with package write permission.
The first GHCR package may need to be made public in its package settings.

Published tags include the upstream version and this repository's commit:
`v1.40.1-auto-<commit12>` and `sha-<commit12>`. There is no mutable `latest` tag.
The workflow summary records the published digest for GitOps configuration.

To upgrade, change **both** `DRAGONFLY_VERSION` and `DRAGONFLY_COMMIT` defaults in
the Dockerfile. Their values must match in the source and runtime stages. Builds
verify the tag resolves to the pinned commit and fetch its pinned submodules.

Run `just check` for local source checks and `just test-image` for full builds and
tests. CI uses QEMU user emulation to check CPU detection with Nehalem, Sandy
Bridge, Haswell, and missing-feature variants. It performs string/hash/list/set/
sorted-set/JSON operations, repeated cache writes, snapshot save, and snapshot
restore in both directions between CPU builds. This supplements, rather than
replaces, sustained tests on the real T410 and Harbor workload before rollout.

## Upstream

- Source: https://github.com/dragonflydb/dragonfly
- Build settings: https://github.com/dragonflydb/dragonfly/blob/v1.40.1/Makefile
- Hardware support: https://www.dragonflydb.io/docs/getting-started

Dragonfly is distributed under its upstream license, included in the image at
`/usr/share/doc/dragonfly/LICENSE.md`.
