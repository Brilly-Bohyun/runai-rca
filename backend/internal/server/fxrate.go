package server

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"
)

// seoul is the reference clock for the daily refresh. The operator reads these
// figures in KST, so "today's rate" has to mean today in Seoul.
var seoul = time.FixedZone("KST", 9*60*60)

// fxRefreshHour is the local hour the daily rate lands. Published reference
// rates for the previous session are available well before this.
const fxRefreshHour = 9

// FXRate is the USD→KRW rate the dashboard converts with, plus when it was
// taken so the UI can say how fresh it is.
type FXRate struct {
	USDKRW    float64   `json:"usd_krw"`
	FetchedAt time.Time `json:"usd_krw_at"`
	// Fallback marks a rate that came from configuration rather than the feed —
	// the figures are still shown, but they are not today's market rate.
	Fallback bool `json:"usd_krw_is_fallback"`
}

func (s *Server) fxRate() FXRate {
	s.fxMu.RLock()
	defer s.fxMu.RUnlock()
	return s.fx
}

// nextFXRefresh is the next fxRefreshHour boundary in Seoul, strictly after now.
func nextFXRefresh(now time.Time) time.Time {
	local := now.In(seoul)
	next := time.Date(local.Year(), local.Month(), local.Day(), fxRefreshHour, 0, 0, 0, seoul)
	if !next.After(local) {
		next = next.AddDate(0, 0, 1)
	}
	return next
}

// runFXRefresh keeps the USD→KRW rate current: once at startup so the dashboard
// isn't stuck on the configured fallback until tomorrow, then daily at 09:00 KST.
func (s *Server) runFXRefresh(ctx context.Context) {
	s.refreshFXRate(ctx)
	for {
		timer := time.NewTimer(time.Until(nextFXRefresh(time.Now())))
		select {
		case <-ctx.Done():
			timer.Stop()
			return
		case <-timer.C:
			s.refreshFXRate(ctx)
		}
	}
}

func (s *Server) refreshFXRate(ctx context.Context) {
	rate, err := s.fetchUSDKRW(ctx)
	if err != nil {
		// Keep whatever rate we already have — a stale real rate beats the
		// fallback, and the fallback beats showing nothing.
		log.Printf("WARNING: USD/KRW refresh failed, keeping the previous rate: %v", err)
		return
	}
	s.fxMu.Lock()
	s.fx = FXRate{USDKRW: rate, FetchedAt: time.Now().UTC()}
	s.fxMu.Unlock()
}

func (s *Server) fetchUSDKRW(ctx context.Context) (float64, error) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.fxRateURL, nil)
	if err != nil {
		return 0, err
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return 0, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return 0, fmt.Errorf("rate feed returned HTTP %d", resp.StatusCode)
	}
	var payload struct {
		Rates map[string]float64 `json:"rates"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&payload); err != nil {
		return 0, err
	}
	rate := payload.Rates["KRW"]
	if rate <= 0 {
		return 0, fmt.Errorf("rate feed carried no usable KRW rate")
	}
	return rate, nil
}
