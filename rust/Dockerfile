# Rust backend image: a static musl binary on distroless (no shell, no
# package manager). Build from the repo root (the context needs app/static
# and weather.yaml):
#   podman build -f rust/Dockerfile -t localhost/wetter-rust .
# Builds natively for the build machine's architecture (PC: x86_64,
# Raspberry Pi 5: aarch64).
FROM docker.io/library/rust:1.98.1-slim-trixie AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends musl-tools \
    && rm -rf /var/lib/apt/lists/* \
    && rustup target add "$(uname -m)-unknown-linux-musl"
WORKDIR /build

# Dependencies first, in their own cached layer (empty sources)
COPY rust/Cargo.toml rust/Cargo.lock ./
RUN mkdir src && echo 'fn main() {}' > src/main.rs && touch src/lib.rs \
    && cargo build --release --locked --target "$(uname -m)-unknown-linux-musl" \
    && rm -rf src

# The app; touch so cargo rebuilds it over the empty placeholder
COPY rust/src ./src
RUN touch src/main.rs src/lib.rs \
    && cargo build --release --locked --target "$(uname -m)-unknown-linux-musl" \
    && mkdir -p /out/data \
    && cp "target/$(uname -m)-unknown-linux-musl/release/wetter" /out/wetter

# distroless/static-debian13:nonroot (multi-arch index), pinned by digest
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
