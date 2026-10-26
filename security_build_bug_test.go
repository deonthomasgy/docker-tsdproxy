// SPDX-FileCopyrightText: 2026 TSDProxy contributors
// SPDX-License-Identifier: MIT

package tsdproxy_test

import (
	"go/version"
	"os"
	"regexp"
	"runtime"
	"testing"

	"github.com/blang/semver/v4"
)

// ID: TS-2026-013 (https://tailscale.com/security-bulletins#ts-2026-013).
// Description: builds must include the compromised eMudhra CA distrust fix.
// Attack scenario: a forged certificate chains to a compromised intermediate
// trusted by the host's CA store, allowing impersonation of a TLS endpoint.
// Expected post-fix behavior: require Tailscale >= 1.104.2 and Go >= 1.27.3
// for source, production Docker and development Docker builds.
// Go 1.26.10 also has the distrust backport, but Tailscale 1.104.2 requires
// Go 1.27.3. The old production builder was patched; go.mod allowed 1.26.7.
// Today: this test fails because go.mod and Docker builders permit older
// versions. This checks build prerequisites, not a certificate exploit.
func TestSecurityBuild_TS2026013_BUG(t *testing.T) {
	t.Parallel()

	const minGo = "go1.27.3"
	const minTailscale = "1.104.2"

	for _, tc := range []struct {
		file    string
		pattern string
	}{
		{"go.mod", `(?m)^go (\S+)$`},
		{"Dockerfile", `(?m)^FROM .*golang:([0-9.]+)-`},
		{"dev/Dockerfile.dev", `(?m)^FROM golang:([0-9.]+)-`},
	} {
		t.Run(tc.file, func(t *testing.T) {
			t.Parallel()
			got := "go" + securityBuildVersion(t, tc.file, tc.pattern)
			if !version.IsValid(got) || version.Compare(got, minGo) < 0 {
				t.Errorf("TS-2026-013: %s requires %s or newer; found %s", tc.file, minGo, got)
			}
		})
	}
	if got := runtime.Version(); !version.IsValid(got) || version.Compare(got, minGo) < 0 {
		t.Errorf("TS-2026-013: tests built with %s; require %s or newer", got, minGo)
	}

	tailscaleVersion := securityBuildVersion(t, "go.mod", `(?m)^\s*tailscale\.com v(\S+)`)
	parsed, err := semver.Parse(tailscaleVersion)
	if err != nil {
		t.Fatalf("parse Tailscale version: %v", err)
	}
	if parsed.LT(semver.MustParse(minTailscale)) {
		t.Errorf("TS-2026-013: Tailscale %s is older than %s", tailscaleVersion, minTailscale)
	}
	stamp := securityBuildVersion(t, "Dockerfile", `(?m)^ARG TAILSCALE_VERSION=(\S+)$`)
	if stamp != tailscaleVersion {
		t.Errorf("Docker Tailscale stamp %s differs from dependency %s", stamp, tailscaleVersion)
	}
}

func securityBuildVersion(t *testing.T, path, pattern string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	match := regexp.MustCompile(pattern).FindSubmatch(data)
	if match == nil {
		t.Fatalf("missing version in %s (pattern %s)", path, pattern)
	}
	return string(match[1])
}
