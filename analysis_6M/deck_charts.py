"""Presentation-size charts for the main strategy (algo2e_fin.py, 19:27 run).
Run from repo root: python3 analysis_6M/deck_charts.py"""
import pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt, matplotlib.ticker as mt

TK = "analysis_6M/raw/fin_v3_ticks_20261002_192708.csv"
EV = "analysis_6M/raw/fin_v3_events_20261002_192708.csv"
OUT = "analysis_6M/deck_charts"
INK, MUTED, GRID, BG = "#1b2430", "#5b6572", "#e4e2dc", "#fbfbf8"
BLUE, GREEN, RED, AMBER, ORANGE = "#2a78d6", "#1b8a5a", "#d6402a", "#eda100", "#e0662b"
plt.rcParams.update({"font.size": 15, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": .7, "figure.facecolor": BG,
    "axes.facecolor": BG, "font.family": "DejaVu Sans"})

d = pd.read_csv(TK); e = pd.read_csv(EV)
g = d.groupby("case_tick").t
d["x"] = d.case_tick + (d.t - g.transform("min")) / (g.transform("max") - g.transform("min") + 1e-9) * .999

def path(tk):
    b, a = d[tk+"_bid"], d[tk+"_ask"]
    ok = (b > 0) & ~((a > 0) & ((a-b) > .05*b))
    mid = np.where(a > 0, (a+b)/2, b)
    return d.x[ok].values, mid[ok], d.t[ok].values

def fills(tk, modes):
    f = e[(e.event == "fill") & (e.ticker == tk)].copy()
    f["mode"] = f.note.str.extract(r"mode=(\w+)")[0]; f = f[f["mode"].isin(modes)]
    x, y, t = path(tk); f["px"] = np.interp(f.t, t, y); f["x"] = np.interp(f.t, t, x)
    return f

def shade(ax, tk):
    m = d[tk+"_mode"].isin(["dir", "cut"]).values; x = d.x.values; i = 0
    while i < len(m):
        if m[i]:
            j = i
            while j+1 < len(m) and m[j+1]: j += 1
            ax.axvspan(x[i], x[j]+.15, color=AMBER, alpha=.2, lw=0); i = j+1
        else: i += 1

def trades(ax, tk):
    tr = fills(tk, ["dir", "cut"]); b, s = tr[tr.side == "BUY"], tr[tr.side == "SELL"]
    ax.scatter(b.x, b.px, marker="^", s=90, color=GREEN, edgecolor="white", lw=.8, zorder=5, label="trend BUY")
    ax.scatter(s.x, s.px, marker="v", s=90, color=RED, edgecolor="white", lw=.8, zorder=5, label="trend SELL")

def money(v, _=None):
    s = "-" if v < 0 else ""; v = abs(v)
    return f"{s}${v/1e6:.1f}M" if v >= 1e6 else f"{s}${v/1e3:.0f}k"

def save(fig, name): fig.tight_layout(); fig.savefig(f"{OUT}/{name}", dpi=120); plt.close(fig)

# A. three price paths side by side --------------------------------------
fig, ax = plt.subplots(1, 3, figsize=(16, 5.4))
for a, tk, c, ttl in zip(ax, ["CNR", "RY", "AC"], [BLUE, ORANGE, GREEN], ["CNR  (anchor ~$160)", "RY  (anchor ~$100, log axis)", "AC  (anchor ~$25)"]):
    x, y, _ = path(tk); pre = y[x < 200]
    a.axhspan(pre.mean()-2*pre.std(), pre.mean()+2*pre.std(), color=c, alpha=.15, lw=0)
    a.plot(x, y, color=c, lw=1.8); a.axvline(200, color=MUTED, ls="--", lw=1)
    a.set_title(ttl, loc="left", fontsize=16, fontweight="bold", color=INK); a.set_xlabel("case tick")
    a.set_xlim(0, 300)
    if tk == "RY": a.set_yscale("log"); a.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"${v:g}")); a.set_yticks([100, 150, 200, 300, 400])
    else: a.yaxis.set_major_formatter(mt.FormatStrFormatter("$%.2f" if tk == "CNR" else "$%.1f"))
ax[0].set_ylim(159.0, 161.0); ax[2].set_ylim(24.7, 32)
ax[0].text(205, 160.8, "tick 200", color=MUTED, fontsize=13)
save(fig, "A_price_paths.png")

# B. RY trade anatomy ---------------------------------------------------
fig, ax = plt.subplots(2, 2, figsize=(16, 6.1), gridspec_kw={"height_ratios": [2.0, 1.1]})
x, y, _ = path("RY")
for k, (lo, hi, log) in enumerate([(0, 300, True), (198, 221, False)]):
    a = ax[0][k]; a.plot(x, y, color=ORANGE, lw=2); shade(a, "RY"); trades(a, "RY"); a.set_xlim(lo, hi)
    mm = fills("RY", ["mm"]); a.scatter(mm.x, mm.px, s=6, color=MUTED, alpha=.35, zorder=3)
    if log: a.set_yscale("log"); a.set_yticks([100, 150, 200, 300, 400]); a.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"${v:g}"))
    else: a.yaxis.set_major_formatter(mt.FormatStrFormatter("$%.0f"))
    a.set_title("RY, whole case (log scale)" if log else "RY, zoom on ticks 198-221", loc="left", fontsize=16, fontweight="bold", color=INK)
    if k == 1: a.legend(loc="upper left", frameon=False, fontsize=13)
    b = ax[1][k]; b.step(d.x, d.RY_pos, where="post", color=INK, lw=1.5); b.fill_between(d.x, 0, d.RY_pos, step="post", color=BLUE, alpha=.18)
    shade(b, "RY"); b.set_xlim(lo, hi); b.set_xlabel("case tick"); b.set_ylabel("RY position")
    b.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))
ax[0][1].annotate("buys: \\$100.2 to \\$105.5\nover ticks 201-210", (205, 102), xytext=(199.3, 160), fontsize=13, color=INK, arrowprops=dict(arrowstyle="->", color=MUTED))
ax[0][1].annotate("sells into bids\n\\$346 to \\$402", (218.4, 400), xytext=(209, 330), fontsize=13, color=INK, arrowprops=dict(arrowstyle="->", color=MUTED))
save(fig, "B_RY_trade.png")

# C. AC and CNR ---------------------------------------------------------
fig, ax = plt.subplots(2, 2, figsize=(16, 6.1), gridspec_kw={"height_ratios": [2.0, 1.1]})
for k, (tk, c, ttl) in enumerate([("AC", GREEN, "AC: flat, then a climb from \\$25 to \\$31.5"), ("CNR", BLUE, "CNR: stuck near \\$160, early trend calls were wrong")]):
    x, y, _ = path(tk); a = ax[0][k]; a.plot(x, y, color=c, lw=1.8); shade(a, tk); trades(a, tk); a.set_xlim(0, 300)
    a.yaxis.set_major_formatter(mt.FormatStrFormatter("$%.1f" if tk == "AC" else "$%.2f"))
    if tk == "CNR": a.set_ylim(159.1, 160.8)
    a.set_title(ttl, loc="left", fontsize=16, fontweight="bold", color=INK)
    if k == 0: a.legend(loc="upper left", frameon=False, fontsize=13)
    b = ax[1][k]; b.plot(d.x, d[tk+"_pnl"], color=INK, lw=1.8); shade(b, tk); b.set_xlim(0, 300); b.axhline(0, color=MUTED, lw=.8)
    b.set_ylabel(f"{tk} P&L"); b.set_xlabel("case tick"); b.yaxis.set_major_formatter(mt.FuncFormatter(money))
    fin = d[tk+"_pnl"].iloc[-1]; b.annotate(f"final {money(fin)}", (299, fin), xytext=(-8, 14), textcoords="offset points", ha="right", color=INK, fontweight="bold")
save(fig, "C_AC_CNR.png")

# D. P&L with and without the spike -------------------------------------
p = pd.read_csv("analysis_6M/fin_pnl_by_case_tick.csv")
fig, ax = plt.subplots(1, 2, figsize=(16, 5.6))
a = ax[0]; a.plot(p.case_tick, p.nlv_true, color=INK, lw=2.4); a.axvline(217, color=ORANGE, ls="--", lw=1.4)
a.yaxis.set_major_formatter(mt.FuncFormatter(money)); a.set_title("Actual: \\$6.29M", loc="left", fontsize=17, fontweight="bold", color=INK)
a.text(212, 3.0e6, "RY spike\ntick 217", ha="right", color=ORANGE, fontsize=14)
a.annotate("+$0.3M just\nbefore the spike", (216, 3.3e5), xytext=(120, 1.4e6), fontsize=13, color=MUTED, arrowprops=dict(arrowstyle="->", color=MUTED))
a = ax[1]; a.fill_between([299, 299.01], 0, 0)  # keep axes
a.plot(p.case_tick, p.nlv_cf, color=BLUE, lw=2.4); a.axvline(217, color=ORANGE, ls="--", lw=1.4)
a.errorbar([298], [511116], yerr=[[511116-243989], [558990-511116]], color=MUTED, capsize=6, lw=2)
a.yaxis.set_major_formatter(mt.FuncFormatter(money)); a.set_title("Without the spike: about \\$511k", loc="left", fontsize=17, fontweight="bold", color=INK)
a.text(10, 300000, "RY exit assumed at the last normal bid (\\$121).\nBar: exit anywhere from \\$109 to \\$123\ngives \\$244k to \\$559k", fontsize=13, color=MUTED)
for a in ax: a.set_xlabel("case tick"); a.set_xlim(0, 300)
save(fig, "D_pnl_with_without.png")

# E. where the money came from ------------------------------------------
parts = [("RY: exit into the spike", 5777656, ORANGE), ("RY: trend ride before the spike", 450870, BLUE), ("AC: trend ride + exit", 111511, GREEN),
         ("AC: market making", 5079, GREEN), ("RY: market making", -3698, ORANGE), ("CNR: market making", -16152, BLUE), ("CNR: trend calls (ticks 3-13)", -36494, BLUE)]
fig, ax = plt.subplots(figsize=(16, 5.2))
names = [p_[0] for p_ in parts][::-1]; vals = [p_[1] for p_ in parts][::-1]; cols = [p_[2] for p_ in parts][::-1]
ax.barh(names, vals, color=cols, height=.62); ax.set_xscale("symlog", linthresh=10000, linscale=.6)
ax.set_xticks([-100000, -10000, 0, 10000, 100000, 1000000, 6000000]); ax.xaxis.set_major_formatter(mt.FuncFormatter(money))
for i, v in enumerate(vals): ax.text(v + (v and np.sign(v)*0.15*abs(v)**0.0)+0, i, "  "+f"{'-' if v<0 else '+'}${abs(v):,.0f}", va="center", ha="left" if v >= 0 else "right", fontsize=14, color=INK)
ax.axvline(0, color=MUTED, lw=1); ax.set_xlim(-2.5e5, 3e7); ax.set_xlabel("P&L, symmetric-log axis (the spike bar is 13x the next one)")
ax.grid(axis="y", visible=False)
save(fig, "E_breakdown.png")

# F. limits ---------------------------------------------------------------
fig, ax = plt.subplots(figsize=(16, 5.2))
ax.plot(d.x, d.gross, color=BLUE, lw=1.4, label="gross position"); ax.plot(d.x, d.net.abs(), color=ORANGE, lw=1.4, label="|net| position")
ax.axhline(25000, color=RED, lw=2.2); ax.axhline(23250, color=AMBER, lw=2, ls="--")
ax.text(2, 25250, "case limit 25,000", color=RED, fontsize=14); ax.text(2, 23450, "bot's own cap 23,250 (93%)", color="#9a6b00", fontsize=14)
ax.set_ylim(0, 27500); ax.set_xlim(0, 300); ax.set_xlabel("case tick"); ax.set_ylabel("shares"); ax.legend(loc="center left", frameon=False)
ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))
ax.annotate(f"peak gross {d.gross.max():,.0f}", (d.x[d.gross.idxmax()], d.gross.max()), xytext=(150, 17000), fontsize=14, color=INK, arrowprops=dict(arrowstyle="->", color=MUTED))
save(fig, "F_limits.png")
print("ok", d.gross.max(), d.net.abs().max())

# G. regime detection around the RY breakout ----------------------------
w = d[(d.x >= 196) & (d.x <= 207)]
fig, ax = plt.subplots(3, 1, figsize=(16, 6.1), sharex=True, gridspec_kw={"height_ratios": [1.3, 1.1, 1.1]})
x, y, _ = path("RY"); m = (x >= 196) & (x <= 207)
ax[0].plot(x[m], y[m], color=ORANGE, lw=2.2); ax[0].set_ylabel("RY price"); ax[0].yaxis.set_major_formatter(mt.FormatStrFormatter("$%.2f"))
ax[1].plot(w.x, w.RY_gap, color=BLUE, lw=2.2); ax[1].axhline(12, color=RED, ls="--", lw=1.6); ax[1].set_ylabel("EMA gap (ticks)")
ax[1].text(196.1, 13.5, "entry threshold: 12 ticks", color=RED, fontsize=13)
ax[2].plot(w.x, w.RY_er, color=GREEN, lw=2.2); ax[2].axhline(0.45, color=RED, ls="--", lw=1.6); ax[2].set_ylabel("efficiency ratio"); ax[2].set_ylim(-.05, 1.15)
ax[2].text(196.1, 0.5, "TREND needs 0.45", color=RED, fontsize=13); ax[2].set_xlabel("case tick")
col = {"chop": "#9AA3AF", "mixed": "#d9d4c4", "TREND": AMBER}
reg = w.RY_regime.values; xs = w.x.values; i = 0
while i < len(reg):
    j = i
    while j+1 < len(reg) and reg[j+1] == reg[i]: j += 1
    for a in ax: a.axvspan(xs[i], xs[min(j+1, len(xs)-1)], color=col.get(reg[i], BG), alpha=.28, lw=0)
    i = j+1
fb = fills("RY", ["dir"]); fb = fb[fb.side == "BUY"].x.min()
for a in ax: a.axvline(fb, color=GREEN, lw=1.8, ls=":")
ax[0].text(196.15, ax[0].get_ylim()[1]*0.999, "chop / calm: market making", fontsize=13, color=INK, va="top")
ax[0].text(fb+0.1, 100.12, f"first trend buy (tick {fb:.1f}): gap held above 12 ticks for 0.8 s", fontsize=13, color=INK, va="bottom")
ax[0].set_xlim(196, 207)
save(fig, "G_regime.png")
