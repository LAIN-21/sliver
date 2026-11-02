# Official upstream source, resolved through the Go proxy and checksum database.
FROM golang:1.26.1-bookworm@sha256:ab3d6955bbc813a0f3fdf220c1d817dd89c0b3f283777db8ece4a32fe7858edd AS builder

ENV CGO_ENABLED=0 \
    GOBIN=/out \
    GOTOOLCHAIN=local \
    GOPROXY=https://proxy.golang.org \
    GOSUMDB=sum.golang.org

# Pin the final upstream releases, not mutable branches or a third-party mirror.
# Limit compiler parallelism to fit contributor machines and hosted CI runners.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go install -p 2 -trimpath \
      -ldflags='-s -w -X github.com/minio/minio/cmd.Version=2025-10-15T17:29:55Z -X github.com/minio/minio/cmd.ReleaseTag=RELEASE.2025-10-15T17-29-55Z -X github.com/minio/minio/cmd.CommitID=9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a -X github.com/minio/minio/cmd.ShortCommitID=9e49d5e7a648' \
      github.com/minio/minio@v0.0.0-20251015172955-9e49d5e7a648 \
    && go install -p 2 -trimpath \
      github.com/minio/mc@v0.0.0-20250813083541-7394ce0dd2a8 \
    && mkdir -p /licenses \
    && cp /go/pkg/mod/github.com/minio/minio@v0.0.0-20251015172955-9e49d5e7a648/LICENSE /licenses/minio-LICENSE \
    && cp /go/pkg/mod/github.com/minio/mc@v0.0.0-20250813083541-7394ce0dd2a8/LICENSE /licenses/mc-LICENSE \
    && printf '%s\n' \
      'MinIO server: https://github.com/minio/minio/tree/9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a' \
      'MinIO client: https://github.com/minio/mc/tree/7394ce0dd2a80935aded936b09fa12cbb3cb8096' \
      'Built from unmodified upstream source; Go module checksums verified by sum.golang.org.' \
      > /licenses/SOURCES

FROM scratch

LABEL org.opencontainers.image.title="Sliver local MinIO" \
      org.opencontainers.image.source="https://github.com/minio/minio" \
      org.opencontainers.image.revision="9e49d5e7a648f00e26f2246f4dc28e6b07f8c84a" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later"

COPY --from=builder /out/minio /usr/local/bin/minio
COPY --from=builder /out/mc /usr/local/bin/mc
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=builder /licenses /licenses

ENV HOME=/root \
    USER=root \
    PATH=/usr/local/bin

WORKDIR /data
EXPOSE 9000 9001
ENTRYPOINT ["/usr/local/bin/minio"]
