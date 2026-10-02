# Rust backend image: a static musl binary on distroless (no shell, no
# package manager). Build from the repo root (the context needs app/static
# and weather.yaml):
#   podman build -f rust/Dockerfile -t localhost/wetter-rust .
# Without --platform it builds natively for the build machine (PC: x86_64,
# Raspberry Pi 5: aarch64). On an x86_64 PC it also cross-compiles for the
# Raspberry Pis (arm64) with zig + cargo-zigbuild; the build stage runs
# natively, so no emulation is needed:
#   podman build --platform linux/arm64 -f rust/Dockerfile -t localhost/wetter-rust:arm64 .
FROM --platform=$BUILDPLATFORM docker.io/library/rust:1.99.0-slim-trixie AS build
# Set by podman/buildah from --platform (default: the build machine)
ARG TARGETARCH
# Cross toolchain, pinned (zig for x86_64 Linux hosts only)
ARG ZIG_VERSION=0.16.0
ARG ZIG_SHA256=70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00
ARG CARGO_ZIGBUILD_VERSION=0.23.4
# Writes the Rust target to /target-triple and the cargo subcommand
# (build or zigbuild) to /cargo-build
RUN set -eu; \
    case "$TARGETARCH" in \
        amd64) arch=x86_64 ;; \
        arm64) arch=aarch64 ;; \
        *) echo "unsupported target architecture: $TARGETARCH (64-bit only)" >&2; exit 1 ;; \
    esac; \
    echo "$arch-unknown-linux-musl" > /target-triple; \
    if [ "$arch" = "$(uname -m)" ]; then \
        apt-get update; \
        apt-get install -y --no-install-recommends musl-tools; \
        echo build > /cargo-build; \
    else \
        if [ "$(uname -m)" != x86_64 ]; then \
            echo "cross builds run on x86_64 hosts only (this is $(uname -m))" >&2; exit 1; \
        fi; \
        apt-get update; \
        apt-get install -y --no-install-recommends curl xz-utils; \
        curl -sSfL -o /tmp/zig.tar.xz \
            "https://ziglang.org/download/$ZIG_VERSION/zig-x86_64-linux-$ZIG_VERSION.tar.xz"; \
        echo "$ZIG_SHA256  /tmp/zig.tar.xz" | sha256sum -c -; \
        mkdir /opt/zig; \
        tar -xJf /tmp/zig.tar.xz -C /opt/zig --strip-components=1; \
        ln -s /opt/zig/zig /usr/local/bin/zig; \
        rm /tmp/zig.tar.xz; \
        cargo install --locked "cargo-zigbuild@$CARGO_ZIGBUILD_VERSION"; \
        echo zigbuild > /cargo-build; \
    fi; \
    rm -rf /var/lib/apt/lists/*; \
    rustup target add "$(cat /target-triple)"
WORKDIR /build

# Dependencies first, in their own cached layer (empty sources)
COPY rust/Cargo.toml rust/Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs && touch src/lib.rs \
    && cargo "$(cat /cargo-build)" --release --locked --target "$(cat /target-triple)" \
    && rm -rf src

# The app; touch so cargo rebuilds it over the empty placeholder
COPY rust/src ./src
RUN touch src/main.rs src/lib.rs \
    && cargo "$(cat /cargo-build)" --release --locked --target "$(cat /target-triple)" \
    && mkdir -p /out/data \
    && cp "target/$(cat /target-triple)/release/wetter" /out/wetter

# distroless/static-debian13:nonroot (multi-arch index, so --platform picks
# the matching variant), pinned by digest
FROM gcr.io/distroless/static-debian13@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3
# Code and config stay root-owned: the app user can read but not change them
COPY --from=build /out/wetter /app/wetter
COPY app/static /app/static
COPY weather.yaml /app/weather.yaml
# SQLite lives here (mount a volume); uid 1000 like the Python image, so an
# existing weather-data volume stays writable
COPY --from=build --chown=1000:1000 /out/data /data
ENV DATABASE_PATH=/data/weather.db \
    WEATHER_CONFIG=/app/weather.yaml \
    STATIC_DIR=/app/static \
    BIND_ADDR=0.0.0.0:8000
EXPOSE 8000
USER 1000:1000
ENTRYPOINT ["/app/wetter"]
