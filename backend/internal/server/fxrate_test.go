package server

import (
	"testing"
	"time"
)

func TestNextFXRefreshIsTheNextSeoulMorning(t *testing.T) {
	// The refresh has to land on 09:00 in Seoul regardless of the host's zone,
	// and must never return "now" — a boundary hit would spin the timer.
	cases := []struct {
		name string
		now  time.Time
		want time.Time
	}{
		{
			name: "before the hour, same day",
			now:  time.Date(2026, 7, 30, 3, 0, 0, 0, seoul),
			want: time.Date(2026, 7, 30, 9, 0, 0, 0, seoul),
		},
		{
			name: "after the hour, next day",
			now:  time.Date(2026, 7, 30, 17, 30, 0, 0, seoul),
			want: time.Date(2026, 7, 31, 9, 0, 0, 0, seoul),
		},
		{
			name: "exactly on the hour rolls forward",
			now:  time.Date(2026, 7, 30, 9, 0, 0, 0, seoul),
			want: time.Date(2026, 7, 31, 9, 0, 0, 0, seoul),
		},
		{
			name: "a UTC clock still lands on Seoul morning",
			// 2026-07-30T23:00Z is 2026-07-31T08:00 KST — the same morning.
			now:  time.Date(2026, 7, 30, 23, 0, 0, 0, time.UTC),
			want: time.Date(2026, 7, 31, 9, 0, 0, 0, seoul),
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := nextFXRefresh(tc.now)
			if !got.Equal(tc.want) {
				t.Fatalf("nextFXRefresh(%s) = %s, want %s", tc.now, got, tc.want)
			}
			if !got.After(tc.now) {
				t.Fatalf("next refresh %s must be strictly after %s", got, tc.now)
			}
		})
	}
}
