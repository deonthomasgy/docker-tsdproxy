// SPDX-FileCopyrightText: 2026 Deon Thomas
// SPDX-License-Identifier: MIT

package config

import (
	"testing"

	"github.com/rs/zerolog"
)

// ID: docker-admin-opt-in
// Description: Docker defaults must preserve the administrator's access policy.
// Attack scenario: a client on a trusted private address bypasses authentication
// when Docker startup silently changes adminAllowLocalhost from false to true.
// Expected post-fix behavior: local admin access requires explicit opt-in.
// Today: this test fails because applyDockerDefaults unconditionally enables it.
func TestDockerAdminRequiresOptIn_BUG(t *testing.T) {
	t.Parallel()
	if !isRunningInDocker() {
		t.Skip("regression must run inside Docker (Dockerfile test target)")
	}
	for _, allowed := range []bool{false, true} {
		cfg := &Data{AdminAllowLocalhost: allowed}
		cfg.HTTP.Hostname = "0.0.0.0"
		cfg.applyDockerDefaults(zerolog.Nop())
		if cfg.AdminAllowLocalhost != allowed {
			t.Errorf("adminAllowLocalhost changed from %t to %t", allowed, cfg.AdminAllowLocalhost)
		}
	}
}
