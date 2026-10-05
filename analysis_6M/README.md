# The two ~$6M runs (10/2/2026, 19:27 start)

| | algo2e_fin.py | dir.py |
|---|---|---|
| log | raw/fin_v3_*_20261002_192708.csv | raw/dir_v3_*_20261002_192712_port17000_pid129560.csv |
| how identified | log name has no pid (fin's naming); quotes + trend | log name has port+pid (dir's naming); MM_ENABLED=False |
| True final P&L (server NLV) | $6,288,771 | $6,278,408 |
| bot's own `pnl` column | $6,289,215 | $6,138,442 (baseline bug: -$139,966) |
| RY / CNR / AC | +6,224,827 / -52,646 / +116,590 | +6,238,173 / -77,895 / +118,130 |
| Without the spike (RY exit at $121.08) | ~$511k | ~$500k |
| Spike contribution | $5.78M (91.9%) | $5.78M (92.0%) |

True P&L = server NLV, which equals CNR_pnl + RY_pnl + AC_pnl to the cent.

## Files
- fig1..fig4 *.png: charts
- {fin,dir}_pnl_by_case_tick.csv: NLV actual and spike-removed, per-ticker P&L, positions, modes, books, per case tick
- {fin,dir}_fills_stops_dir_events.csv: every fill, MM stop, trend entry/exit, breaker (fill price column is the MID at fill time, not the true fill price)
- {fin,dir}_trend_rides.csv: each trend ride, hold time, size, P&L actual vs ex-spike, exit reason
- {fin,dir}_pnl_by_ticker_mode.csv, {fin,dir}_usage_by_ticker.csv
- {fin,dir}_ry_spike_window_raw.csv: raw RY ticks +-10 s around the jump
- sensitivity_exit_price.csv: ex-spike P&L for several assumed RY exit prices
- summary_with_without_spike.csv, raw/ (copies of the original tick+event logs)
- ../analyze_6M.py regenerates everything

## Method for "without the spike"
RY's first dislocation (tick 217: bid 121 -> 239 -> 346 -> 402, asks gone) is replaced by selling the same
~22,060 RY shares at the last tight-book bid before the jump ($121.08). All RY activity after that
(a second jump at tick 261) is dropped. CNR and AC are untouched. Sensitivity (exit $109-$123): total
$0.23M to $0.56M. Cost basis (~$100.3-100.6) is estimated from the logged fill mids.
