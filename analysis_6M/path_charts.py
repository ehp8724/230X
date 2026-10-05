"""Price path + entries/exits + position + P&L charts for the two ~$6M runs.
Run from repo root: python3 analysis_6M/path_charts.py"""
import pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mt

RUNS = {
 "fin": ("analysis_6M/raw/fin_v3_ticks_20261002_192708.csv",
         "analysis_6M/raw/fin_v3_events_20261002_192708.csv",
         "algo2e_fin.py (market making + trend)"),
 "dir": ("analysis_6M/raw/dir_v3_ticks_20261002_192712_port17000_pid129560.csv",
         "analysis_6M/raw/dir_v3_events_20261002_192712_port17000_pid129560.csv",
         "dir.py (trend only)"),
}
OUT = "analysis_6M/path_charts"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e1"
PRICE, BUY, SELL, SHADE = "#2a78d6", "#008300", "#d6402a", "#eda100"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False,
    "axes.spines.right": False, "axes.grid": True, "grid.color": GRID, "grid.linewidth": .6,
    "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})

def load(tk_f, ev_f):
    d = pd.read_csv(tk_f)
    g = d.groupby("case_tick").t
    d["x"] = d.case_tick + (d.t - g.transform("min")) / (g.transform("max") - g.transform("min") + 1e-9) * 0.999
    e = pd.read_csv(ev_f)
    return d, e

def path(d, tk):
    b, a = d[tk+"_bid"], d[tk+"_ask"]
    ok = b > 0
    mid = np.where(a > 0, (a+b)/2, b)           # one-sided book -> show the bid
    # drop thin-book garbage mids (spread > 5%) except one-sided spike books
    wide = (a > 0) & ((a-b) > 0.05*b)
    ok &= ~wide
    return d.x[ok].values, mid[ok], d.t[ok].values

def fill_xy(d, e, tk, modes):
    f = e[(e.event == "fill") & (e.ticker == tk)].copy()
    f["mode"] = f.note.str.extract(r"mode=(\w+)")[0]
    f = f[f["mode"].isin(modes)]
    x, y, t = path(d, tk)
    f["px"] = np.interp(f.t, t, y); f["x"] = np.interp(f.t, t, x)
    return f

def shade(ax, d, tk):
    m = d[tk+"_mode"].isin(["dir", "cut"]).values
    x = d.x.values
    i = 0
    while i < len(m):
        if m[i]:
            j = i
            while j+1 < len(m) and m[j+1]: j += 1
            ax.axvspan(x[i], x[j]+0.15, color=SHADE, alpha=.18, lw=0)
            i = j+1
        else: i += 1

def ticker_fig(name, d, e, tk, title, xlim=None, log=False, fn=None, note=None):
    fig, ax = plt.subplots(3, 1, figsize=(13, 9.5), sharex=True,
                           gridspec_kw={"height_ratios": [3, 1.4, 1.4]})
    x, y, t = path(d, tk)
    ax[0].plot(x, y, color=PRICE, lw=1.4, label=f"{tk} mid (bid when book is one-sided)")
    shade(ax[0], d, tk); shade(ax[1], d, tk); shade(ax[2], d, tk)
    tr = fill_xy(d, e, tk, ["dir", "cut"])
    b, s = tr[tr.side == "BUY"], tr[tr.side == "SELL"]
    ax[0].scatter(b.x, b.px, marker="^", s=46, color=BUY, edgecolor="white", lw=.6, zorder=5, label="trend BUY")
    ax[0].scatter(s.x, s.px, marker="v", s=46, color=SELL, edgecolor="white", lw=.6, zorder=5, label="trend / exit SELL")
    mm = fill_xy(d, e, tk, ["mm"])
    ax[0].scatter(mm.x, mm.px, marker=".", s=7, color=MUTED, alpha=.35, zorder=3, label="market-making fills")
    if log: ax[0].set_yscale("log"); ax[0].yaxis.set_major_formatter(mt.FormatStrFormatter("$%g"))
    else: ax[0].yaxis.set_major_formatter(mt.FormatStrFormatter("$%.2f"))
    ax[0].set_ylabel("price")
    ax[0].legend(loc="upper left", frameon=False, ncol=2, fontsize=9)
    ax[0].set_title(title, loc="left", fontsize=13, fontweight="bold", color=INK, pad=24)
    ax[0].text(0, 1.02, f"{name}  ·  amber band = trend/directional mode (bot is riding the move)",
               transform=ax[0].transAxes, color=MUTED, fontsize=9.5)
    if note: ax[0].text(.99, .04, note, transform=ax[0].transAxes, ha="right", color=INK, fontsize=10,
                        bbox=dict(boxstyle="round", fc="white", ec=GRID))
    ax[1].step(d.x, d[tk+"_pos"], where="post", color=INK, lw=1.2)
    ax[1].fill_between(d.x, 0, d[tk+"_pos"], step="post", color=PRICE, alpha=.15)
    ax[1].axhline(0, color=MUTED, lw=.8); ax[1].set_ylabel("position (shares)")
    ax[1].yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))
    ax[2].plot(d.x, d[tk+"_pnl"], color=INK, lw=1.4); ax[2].axhline(0, color=MUTED, lw=.8)
    ax[2].set_ylabel(f"{tk} P&L ($)"); ax[2].set_xlabel("case tick (0-300)")
    ax[2].yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: (("-" if v<0 else "")+(f"${abs(v)/1e6:.2f}M" if abs(v) >= 1e6 else f"${abs(v)/1e3:.0f}k"))))
    fin = d[tk+"_pnl"].iloc[-1]
    ax[2].annotate(f"final {'-' if fin<0 else ''}\\${abs(fin):,.0f}", (d.x.iloc[-1], fin), xytext=(-8, 10), textcoords="offset points",
                   ha="right", color=INK, fontweight="bold")
    ax[0].set_xlim(*(xlim or (0, 300)))
    fig.tight_layout(); fig.savefig(f"{OUT}/{fn}", dpi=130); plt.close(fig)

def anchors_fig(name, d, run):
    """The mean-reversion evidence: all three names, % deviation from the pre-event mean."""
    fig, ax = plt.subplots(3, 1, figsize=(13, 8.5), sharex=True)
    for a, tk, c in zip(ax, ["CNR", "RY", "AC"], ["#2a78d6", "#eb6834", "#1baf7a"]):
        x, y, _ = path(d, tk)
        base = y[x < 200].mean()
        a.plot(x, (y/base-1)*100, color=c, lw=1.3)
        sd = ((y[x < 200]/base-1)*100).std()
        a.axhspan(-2*sd, 2*sd, color=c, alpha=.12, lw=0)
        a.axhline(0, color=MUTED, lw=.8)
        a.set_ylabel(f"{tk}  % vs ${base:,.2f}")
        a.text(.01, .86, f"{tk}: anchor ${base:,.2f}; ±2 sd band (ticks 0-199) = ±{2*sd:.2f}%",
               transform=a.transAxes, color=INK, fontsize=10)
    ax[0].set_ylim(-1.5, 1.5); ax[1].set_yscale("symlog", linthresh=1); ax[2].set_ylim(-1, 30)
    ax[1].set_ylabel("RY  % vs $100.01 (symlog)")
    for a in ax: a.axvline(200, color=MUTED, ls="--", lw=.8)
    ax[0].set_xlim(0, 300)
    ax[1].text(185, 30, "tick 200: RY breaks out →", color=MUTED, fontsize=9)
    ax[2].text(205, 20, "tick 264: AC trend starts →", color=MUTED, fontsize=9)
    ax[2].set_xlabel("case tick (0-300)")
    ax[0].set_title("Price paths vs. their anchors: mean-reverting until tick 200, then RY and AC leave",
                    loc="left", fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout(); fig.savefig(f"{OUT}/{run}_anchors_mean_reversion.png", dpi=130); plt.close(fig)

for run, (tkf, evf, name) in RUNS.items():
    d, e = load(tkf, evf)
    ticker_fig(name, d, e, "RY", "RY: full path (log scale) - entry on the drift, exit into the spike",
               log=True, fn=f"{run}_RY_full.png",
               note="entry ~tick 201 at ~\\$100.2-105\nexit tick 217-218 into bids \\$346-\\$402")
    ticker_fig(name, d, e, "RY", "RY zoom: ticks 196-222 (drift, then the one-sided book)",
               xlim=(196, 222), fn=f"{run}_RY_zoom.png")
    ticker_fig(name, d, e, "CNR", "CNR: pinned near \\$160 - trend entries were false signals",
               fn=f"{run}_CNR.png")
    ticker_fig(name, d, e, "AC", "AC: flat at \\$25 until tick 264, then a steady climb to \\$31.5",
               fn=f"{run}_AC.png")
    if run == "fin": anchors_fig(name, d, run)
print("done")
