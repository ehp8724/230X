"""
Analysis of the two ~$6M practice runs (10/2 19:27):
    fin = algo2e_fin.py  -> logs/v3_*_20261002_192708.csv
    dir = dir.py         -> logs/v3_*_20261002_192712_port17000_pid129560.csv
Writes data (csv), a summary and charts into ./analysis_6M/

True P&L = server NLV (== sum of per-ticker realized+unrealized to the cent).
The bot's own `pnl` column has a wrong baseline (nlv0 taken from a stale value), so it is NOT used.

"Without the spike": RY's first dislocation (book jumped from ~$121 to $238/$345/$401 at case tick 217)
is replaced by selling the same RY position at a normal-book bid. Everything RY does after that
is dropped. CNR and AC are untouched.
"""
import os, shutil
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

HERE = os.path.dirname(os.path.abspath(__file__))
LOGS = os.path.join(HERE, "logs")
OUT = os.path.join(HERE, "analysis_6M")
os.makedirs(os.path.join(OUT, "raw"), exist_ok=True)

RUNS = {
    "fin": ("algo2e_fin.py", "20261002_192708"),
    "dir": ("dir.py", "20261002_192712_port17000_pid129560"),
}
TK = ["CNR", "RY", "AC"]

# ---- palette (reference palette slots 1-3, light surface) ----
SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
COL = {"CNR": "#2a78d6", "RY": "#eb6834", "AC": "#1baf7a"}
TOTAL = "#0b0b0b"
plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10,
    "axes.titleweight": "bold", "axes.titlesize": 11, "axes.titlelocation": "left",
})
def _money(v, _=None):
    sg = "-" if v < 0 else ""
    a = abs(v)
    return f"{sg}${a/1e6:.1f}M" if a >= 1e6 else f"{sg}${a/1e3:,.0f}k" if a >= 1e3 else f"{sg}${a:,.0f}"
money = FuncFormatter(_money)


def load(key):
    script, stamp = RUNS[key]
    tp = os.path.join(LOGS, f"v3_ticks_{stamp}.csv")
    ep = os.path.join(LOGS, f"v3_events_{stamp}.csv")
    for p in (tp, ep):
        shutil.copy(p, os.path.join(OUT, "raw", f"{key}_" + os.path.basename(p)))
    t = pd.read_csv(tp)
    ev = pd.read_csv(ep)
    t["nlv_true"] = t.CNR_pnl + t.RY_pnl + t.AC_pnl          # == server NLV
    return t, ev


def find_spike(t, ev):
    """first row after RY's first dir_enter where RY bid is >1.5x the entry mid"""
    e = ev[(ev.event == "dir_enter") & (ev.ticker == "RY")].iloc[0]
    t0 = e.t
    ent_mid = float(e.price)
    after = t[(t.t >= t0)]
    bad = after[(after.RY_bid > 1.5 * ent_mid) | (after.RY_ask > 1.5 * ent_mid)]
    i_spike = bad.index[0]
    # last row before the spike with a tight, real book ( <= $0.50 spread )
    prior = t.loc[:i_spike - 1]
    prior = prior[(prior.t >= t0) & (prior.RY_bid > 0) & (prior.RY_ask > 0) & ((prior.RY_ask - prior.RY_bid) <= 0.50)]
    i_tight = prior.index[-1]
    return e, i_spike, i_tight


def ride_table(t, ev, key, cf_ry_exit=None, cf_ry_vwap=None, cf_ry_pre=None, spike_t=None):
    rows = []
    ent = ev[ev.event == "dir_enter"].reset_index(drop=True)
    ex = ev[ev.event == "dir_exit"].reset_index(drop=True)
    for _, e in ent.iterrows():
        nxt = ex[(ex.ticker == e.ticker) & (ex.t > e.t)]
        if nxt.empty:
            continue
        x = nxt.iloc[0]
        tk = e.ticker
        flat = t[(t.t >= x.t) & (t[f"{tk}_pos"] == 0)]
        t_end = flat.t.iloc[0] if not flat.empty else t.t.iloc[-1]
        r0 = t[t.t >= e.t].iloc[0]
        r1 = t[t.t >= t_end].iloc[0]
        seg = t[(t.t >= e.t) & (t.t <= t_end)]
        rows.append(dict(
            run=key, ticker=tk, side=e.side, enter_case_tick=int(e.case_tick), exit_case_tick=int(r1.case_tick),
            enter_t=round(e.t, 1), exit_signal_t=round(x.t, 1), flat_t=round(t_end, 1),
            hold_sec=round(t_end - e.t, 1), entry_mid=round(float(e.price), 4),
            max_abs_pos=int(seg[f"{tk}_pos"].abs().max()),
            pnl_actual=round(r1[f"{tk}_pnl"] - r0[f"{tk}_pnl"], 0),
            exit_reason=str(x.note)[:60], entry_note=str(e.note)[:60]))
    return pd.DataFrame(rows)


summary = []
curves = {}
spikeinfo = {}
sens_rows = []
for key in RUNS:
    t, ev = load(key)
    e, i_spike, i_tight = find_spike(t, ev)
    spike_t = t.loc[i_spike, "t"]
    tight = t.loc[i_tight]
    last_normal = t.loc[i_spike - 1]

    # --- RY ride cost basis from the logged fills (mid-priced) ---
    fills = ev[(ev.event == "fill") & (ev.ticker == "RY") & (ev.t >= e.t) & (ev.t < spike_t) & (ev.side == "BUY")]
    vwap = float((fills.qty * fills.price).sum() / fills.qty.sum())
    pos = int(t.loc[i_spike - 1, "RY_pos"])
    pre = float(t[t.t < e.t].iloc[-1].RY_pnl)             # RY P&L right before the ride (flat or MM carry)
    ref_bid = float(tight.RY_bid)
    cf_exit = {"ref (last tight-book bid)": ref_bid,
               "last row before spike": float(last_normal.RY_bid),
               "-5% haircut on ref": ref_bid * 0.95,
               "-10% haircut on ref": ref_bid * 0.90,
               "exit at $110": 110.0}
    ry_cf = {k: pre + pos * (v - vwap) for k, v in cf_exit.items()}
    ry_actual = float(t.RY_pnl.iloc[-1])
    final = float(t.nlv_true.iloc[-1])
    others = final - ry_actual
    main = "ref (last tight-book bid)"
    spikeinfo[key] = dict(spike_t=spike_t, spike_ct=int(t.loc[i_spike, "case_tick"]), tight=tight, vwap=vwap, pos=pos, pre=pre,
                          ref_bid=ref_bid, ry_cf=ry_cf, ry_actual=ry_actual, final=final, others=others)
    for k, v in ry_cf.items():
        sens_rows.append(dict(run=key, scenario=k, ry_exit_price=round(cf_exit[k], 2), ry_pnl_ex_spike=round(v),
                              total_pnl_ex_spike=round(others + v), spike_contribution=round(final - (others + v))))

    # --- counterfactual curves (case-tick resolution, last value per tick) ---
    ry_cf_main = ry_cf[main]
    t = t.copy()
    after = t.t >= spike_t
    t["RY_pnl_cf"] = np.where(after, ry_cf_main, t.RY_pnl)
    t["nlv_cf"] = t.CNR_pnl + t.RY_pnl_cf + t.AC_pnl
    curves[key] = t

    # ---------- data files ----------
    g = t.groupby("case_tick").last().reset_index()
    cols = ["case_tick", "t", "nlv_true", "nlv_cf", "CNR_pnl", "RY_pnl", "RY_pnl_cf", "AC_pnl", "gross", "net",
            "CNR_pos", "RY_pos", "AC_pos", "CNR_mode", "RY_mode", "AC_mode", "CNR_bid", "CNR_ask", "RY_bid", "RY_ask", "AC_bid", "AC_ask"]
    g[cols].round(2).to_csv(os.path.join(OUT, f"{key}_pnl_by_case_tick.csv"), index=False)
    ev[ev.event.isin(["fill", "stop", "dir_enter", "dir_exit", "breaker", "end"])].to_csv(
        os.path.join(OUT, f"{key}_fills_stops_dir_events.csv"), index=False)
    w = t[(t.t >= spike_t - 8) & (t.t <= spike_t + 12)]
    w[["t", "case_tick", "RY_bid", "RY_ask", "RY_fair", "RY_pos", "RY_mode", "RY_pnl", "nlv_true", "nlv_cf"]].round(3).to_csv(
        os.path.join(OUT, f"{key}_ry_spike_window_raw.csv"), index=False)
    rides = ride_table(t, ev, key)
    # ex-spike ride P&L for the spike ride
    rides["pnl_ex_spike"] = rides.pnl_actual
    m = (rides.ticker == "RY") & (rides.enter_t < spike_t) & (rides.flat_t > spike_t)
    rides.loc[m, "pnl_ex_spike"] = round(ry_cf_main - pre)
    rides.loc[(rides.ticker == "RY") & (rides.enter_t > spike_t), "pnl_ex_spike"] = 0.0
    rides.to_csv(os.path.join(OUT, f"{key}_trend_rides.csv"), index=False)

    # ---------- P&L by (ticker, mode) ----------
    rows = []
    for tk in TK:
        d = t[f"{tk}_pnl"].diff().fillna(0)
        dcf = (t["RY_pnl_cf"].diff().fillna(0) if tk == "RY" else d)
        for md in sorted(t[f"{tk}_mode"].unique()):
            s = t[f"{tk}_mode"] == md
            rows.append(dict(run=key, ticker=tk, mode=md, pnl_actual=round(d[s].sum()), pnl_ex_spike=round(dcf[s].sum()),
                             seconds_in_mode=round(t.t.diff().fillna(0)[s].sum())))
    bm = pd.DataFrame(rows)
    bm.to_csv(os.path.join(OUT, f"{key}_pnl_by_ticker_mode.csv"), index=False)

    # ---------- usage stats ----------
    f = ev[ev.event == "fill"]
    use = []
    for tk in TK:
        ft = f[f.ticker == tk]
        use.append(dict(run=key, ticker=tk, fills=len(ft), shares_traded=int(ft.qty.sum()),
                        fills_in_mm=int((ft.note == "mode=mm").sum()), fills_in_dir_or_cut=int((ft.note != "mode=mm").sum()),
                        mm_stopouts=int(((ev.event == "stop") & (ev.ticker == tk)).sum()),
                        trend_rides=int(((ev.event == "dir_enter") & (ev.ticker == tk)).sum()),
                        max_abs_pos=int(t[f"{tk}_pos"].abs().max()),
                        pnl_actual=round(t[f"{tk}_pnl"].iloc[-1]),
                        pnl_ex_spike=round(t["RY_pnl_cf"].iloc[-1] if tk == "RY" else t[f"{tk}_pnl"].iloc[-1])))
    pd.DataFrame(use).to_csv(os.path.join(OUT, f"{key}_usage_by_ticker.csv"), index=False)

    # pre-spike drawdown / low
    pre_t = t[t.t < spike_t]
    summary.append(dict(
        run=key, script=RUNS[key][0], log=RUNS[key][1], final_pnl_true_nlv=round(final),
        bot_logged_pnl_column=round(t.pnl.iloc[-1]), baseline_error=round(t.pnl.iloc[-1] - final),
        ry_actual=round(ry_actual), cnr=round(t.CNR_pnl.iloc[-1]), ac=round(t.AC_pnl.iloc[-1]),
        ry_ride_shares=pos, ry_ride_vwap_est=round(vwap, 3), spike_case_tick=int(t.loc[i_spike, "case_tick"]),
        ry_ref_exit_bid=round(ref_bid, 2), ry_pnl_ex_spike=round(ry_cf_main), total_pnl_ex_spike=round(others + ry_cf_main),
        spike_contribution=round(final - (others + ry_cf_main)),
        spike_share_pct=round(100 * (final - (others + ry_cf_main)) / final, 1),
        low_before_spike=round(pre_t.nlv_true.min()), peak_before_spike=round(pre_t.nlv_true.max()),
        pnl_at_tick_200=round(t[t.case_tick == 200].nlv_true.iloc[-1])))

pd.DataFrame(summary).T.to_csv(os.path.join(OUT, "summary_with_without_spike.csv"), header=False)
pd.DataFrame(sens_rows).to_csv(os.path.join(OUT, "sensitivity_exit_price.csv"), index=False)
print(pd.DataFrame(summary).T.to_string())
print(pd.DataFrame(sens_rows).to_string(index=False))

# ======================= CHARTS =======================
NAMES = {"fin": "algo2e_fin.py (market making + trend)", "dir": "dir.py (trend only, no quoting)"}

# ---- fig1: total P&L actual vs ex-spike ----
fig, ax = plt.subplots(2, 2, figsize=(14, 8.2))
for j, key in enumerate(RUNS):
    t = curves[key]; si = spikeinfo[key]
    g = t.groupby("case_tick").last()
    a = ax[0, j]
    a.plot(g.index, g.nlv_true, color=TOTAL, lw=2)
    a.axvline(si["spike_ct"], color=COL["RY"], lw=1.2, ls="--")
    a.annotate(f"RY book spike\ntick {si['spike_ct']}", (si["spike_ct"], g.nlv_true.max() * 0.55), xytext=(-8, 0),
               textcoords="offset points", ha="right", color=INK2, fontsize=9)
    a.annotate(f"final {money(si['final'])}", (g.index[-1], g.nlv_true.iloc[-1]), xytext=(-6, -14), textcoords="offset points",
               ha="right", color=INK, fontweight="bold")
    a.set_title(f"{NAMES[key]}\nActual P&L (server NLV)")
    a.yaxis.set_major_formatter(money); a.set_xlabel("case tick")
    b = ax[1, j]
    b.plot(g.index, g.nlv_cf, color=TOTAL, lw=2, label="total, spike removed")
    for tk in TK:
        y = g["RY_pnl_cf"] if tk == "RY" else g[f"{tk}_pnl"]
        b.plot(g.index, y, color=COL[tk], lw=1.5, label=tk)
    b.axvline(si["spike_ct"], color=COL["RY"], lw=1.0, ls="--")
    b.axhline(0, color=INK2, lw=0.8)
    b.annotate(f"{money(g.nlv_cf.iloc[-1])}", (g.index[-1], g.nlv_cf.iloc[-1]), xytext=(-6, 8), textcoords="offset points",
               ha="right", color=INK, fontweight="bold")
    b.set_title("Same run with RY exit valued at the last normal-book bid")
    b.yaxis.set_major_formatter(money); b.set_xlabel("case tick")
    b.legend(frameon=False, ncol=4, loc="upper left")
fig.suptitle("The $6M run: actual vs. without the single RY dislocation", x=0.01, ha="left", fontsize=14, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(os.path.join(OUT, "fig1_pnl_actual_vs_ex_spike.png"), dpi=150)
plt.close(fig)

# ---- fig2: per-ticker actual P&L, log-free: RY dominates so show CNR/AC alongside ----
fig, ax = plt.subplots(1, 2, figsize=(14, 4.6), sharey=False)
for j, key in enumerate(RUNS):
    t = curves[key]; g = t.groupby("case_tick").last()
    a = ax[j]
    for tk in TK:
        a.plot(g.index, g[f"{tk}_pnl"], color=COL[tk], lw=1.8, label=tk)
    a.set_yscale("symlog", linthresh=1e5)
    a.yaxis.set_major_formatter(money)
    a.set_title(f"{NAMES[key]}\nP&L by ticker, actual (symlog axis)")
    a.set_xlabel("case tick"); a.legend(frameon=False, ncol=3, loc="upper left")
    for tk in TK:
        a.annotate(f"{tk} {money(g[f'{tk}_pnl'].iloc[-1])}", (g.index[-1], g[f"{tk}_pnl"].iloc[-1]), xytext=(-4, 5),
                   textcoords="offset points", ha="right", color=INK, fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig2_pnl_by_ticker_actual.png"), dpi=150)
plt.close(fig)

# ---- fig3: RY spike zoom ----
fig, ax = plt.subplots(2, 2, figsize=(14, 7), gridspec_kw={"height_ratios": [2, 1]})
for j, key in enumerate(RUNS):
    t = curves[key]; si = spikeinfo[key]
    st = si["spike_t"]
    w = t[(t.t >= st - 75) & (t.t <= st + 12)]
    a = ax[0, j]
    a.plot(w.t - st, w.RY_bid.where(w.RY_bid > 0), color=COL["RY"], lw=1.8, label="best bid")
    a.plot(w.t - st, w.RY_ask.where(w.RY_ask > 0), color=INK2, lw=1.2, label="best ask")
    a.axvline(0, color=INK2, ls="--", lw=1)
    a.set_title(f"{NAMES[key]}\nRY book around the spike (0 s = first abnormal quote)")
    a.set_ylabel("RY price ($)"); a.legend(frameon=False, loc="upper left")
    a.annotate("bid $100 -> $121 over ~65 s:\nthe trend ride", (-45, 118), color=INK2, fontsize=9)
    a.annotate("bid jumps to $239 / $346 / $402,\nno asks left", (0.5, 330), color=INK2, fontsize=9)
    b = ax[1, j]
    b.step(w.t - st, w.RY_pos, color=COL["RY"], lw=1.8, where="post")
    b.set_ylabel("RY position (sh)"); b.set_xlabel("seconds relative to spike")
    b.axvline(0, color=INK2, ls="--", lw=1)
    b2 = b.twiny(); b2.set_visible(False)
fig.suptitle("RY: a steady ride up, then a one-sided book that paid roughly 350 to 400 per share", x=0.01, ha="left", fontsize=14, fontweight="bold")
fig.tight_layout(rect=(0, 0, 1, 0.95))
fig.savefig(os.path.join(OUT, "fig3_ry_spike_zoom.png"), dpi=150)
plt.close(fig)

# ---- fig4: P&L by ticker x mode, actual vs ex-spike ----
fig, ax = plt.subplots(1, 2, figsize=(14, 4.8))
for j, key in enumerate(RUNS):
    bm = pd.read_csv(os.path.join(OUT, f"{key}_pnl_by_ticker_mode.csv"))
    a = ax[j]
    lab = [f"{r.ticker}\n{r['mode']}" for _, r in bm.iterrows()]
    x = np.arange(len(bm)); wd = 0.4
    a.bar(x - wd / 2, bm.pnl_ex_spike, wd, color=[COL[k] for k in bm.ticker], label="without spike")
    a.bar(x + wd / 2, bm.pnl_actual, wd, color=[COL[k] for k in bm.ticker], alpha=0.35, label="actual")
    a.set_xticks(x); a.set_xticklabels(lab, fontsize=8)
    a.axhline(0, color=INK2, lw=0.8)
    a.set_yscale("symlog", linthresh=1e4)
    a.yaxis.set_major_formatter(money)
    a.set_title(f"{NAMES[key]}\nP&L by ticker and mode (solid = without spike, faded = actual)")
    a.grid(axis="x", visible=False)
fig.tight_layout()
fig.savefig(os.path.join(OUT, "fig4_pnl_by_ticker_mode.png"), dpi=150)
plt.close(fig)
print("done ->", OUT)
