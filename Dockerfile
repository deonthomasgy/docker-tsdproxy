# SPDX-FileCopyrightText: 2024 Paulo Almeida <almeidapaulopt@gmail.com>
# SPDX-License-Identifier: MIT

FROM --platform=$BUILDPLATFORM oven/bun:1@sha256:1d22548f177f4ff38e0c15baa3c2c46c6c2060ba2d1bc573bb4720b407548f1d AS frontend
WORKDIR /app/web
COPY web/package.json web/bun.lock* ./
RUN bun install --frozen-lockfile
COPY web/ ./
COPY internal/ /app/internal/
RUN bun run build

FROM --platform=$BUILDPLATFORM golang:1.26.10-bookworm@sha256:632dff7351799a5a9954a48dc06670ade72ee44e8c351cdc0e5a57af2fea21af AS source

ARG TARGETOS
ARG TARGETARCH
ARG TARGETVARIANT
ARG VERSION=3.0.0-beta.4-security-r1
ARG TAILSCALE_VERSION=1.102.5
ARG GIT_COMMIT

ENV GOTOOLCHAIN=local

WORKDIR /app

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . .
COPY --from=frontend /app/web/dist ./web/dist

RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go install github.com/a-h/templ/cmd/templ@v0.3.1020 && templ generate

FROM source AS test
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    go mod verify && go test -race -count=1 ./... && go vet ./...

FROM source AS builder

# GOARM derived from TARGETVARIANT: v6→6, v7→7; empty for non-arm arches
RUN --mount=type=cache,target=/go/pkg/mod --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=${TARGETOS} GOARCH=${TARGETARCH} GOARM=${TARGETVARIANT#v} go build -trimpath \
      -ldflags "-s -w \
        -X github.com/almeidapaulopt/tsdproxy/internal/core.version=${VERSION} \
        -X tailscale.com/version.Short=${TAILSCALE_VERSION} \
        -X tailscale.com/version.Long=${TAILSCALE_VERSION}-TSDProxy \
        -X tailscale.com/version.GitCommit=${GIT_COMMIT} \
        -X tailscale.com/version.shortStamp=${TAILSCALE_VERSION} \
        -X tailscale.com/version.longStamp=${TAILSCALE_VERSION}-TSDProxy \
        -X tailscale.com/version.gitCommitStamp=${GIT_COMMIT}" \
      -o /tsdproxyd ./cmd/server/

FROM scratch
ARG VERSION=3.0.0-beta.4-security-r1
ARG GIT_COMMIT
LABEL org.opencontainers.image.source="https://github.com/deonthomasgy/docker-tsdproxy" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${GIT_COMMIT}" \
      org.opencontainers.image.licenses="MIT"

COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
COPY --from=builder /tsdproxyd /tsdproxyd

ENTRYPOINT ["/tsdproxyd"]
EXPOSE 8080
HEALTHCHECK --interval=1m --timeout=2s CMD [ "/tsdproxyd", "healthcheck" ]
