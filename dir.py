#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 RIT ALGO 2e  -  v3  "fast"  market-making + trend bot
==============================================================================

RUN (Anaconda Prompt) - nothing else to set, it adapts on its own:
    python algo2e_v3.py abcde 15000 20      <- key, port, how many MINUTES the case lasts
    python algo2e_v3.py abcde 15000         <- without minutes it learns the clock itself

    Offline test without RIT (fake exchange):
    python algo2e_v3.py --mock trend --seconds 60

WHAT IT DOES (lessons from the 1 Oct practice logs)
  1. Fast quoting at the top of the book on every name (cancel/replace the
     moment the touch moves).  The run that made +$14k (19:18) did exactly this
     and earned ~$1.6k/min, almost all of it on RY.  Own orders are removed from
     the book before pricing, so the bot never "pennies itself" (the 20:06 run
     walked its own quotes down 9.99 -> 9.90 that way).
  2. NO market orders, ever.  Every aggressive order is a LIMIT a couple of
     ticks through the touch AND capped near fair value.  The old bot lost
     ~$28k twice in one second by sending market orders into a thin AC book
     (spread $4-$13, ask printed at $1,000).
  3. Inventory that goes against us is cut fast with aggressive limits.  The
     20:09 run sat short 6,722 AC while it ran 37 -> 48, posting stale bids that
     never filled: -$67k.  Now a stop fires within a few ticks.
  4. Trend engine: when a name moves hard and steadily (like AC 37 -> 48) the
     bot switches that name to directional mode and rides it up to ~90% of the
     limit, with a trailing stop.  This is where the large profits are.
  5. Wide/thin books: quotes sit around a robust fair value instead of the
     garbage touch, so sweeps through a thin book fill us at good prices.
  7. Self-detecting regime, per name, every 0.25 s: efficiency ratio over 10 s
     (|net move| / total path).  >=0.45 with a real move = TREND (trend engine
     may fire), <0.25 = chop (pure market making).  It also learns: each losing
     trend ride raises that name's entry bar x1.4 (up to x3); 3 losers in a row
     switch the trend engine off on that name for 60 s; wins relax the bar.
     3 MM stop-outs in 60 s = toxic flow -> half size, stop stepping inside.
  8. Volatility regimes (Bollinger, 30 s bands vs their 2-min baseline):
     calm + range-bound -> 5,000-share quotes, stepped inside the spread;
     bands blowing out / trend -> half size, one tick behind the touch.
     Range-bound: leans against prices stretched beyond +/-2 std devs.
  9. Inventory brake: adding-side size shrinks exponentially (x e^-3r), is
     pulled completely at 85% of the per-name cap, and its price fades back
     up to 4 ticks; the reducing side gets bigger and priced to trade.
  6. Position limits: every order is checked against WORST-CASE exposure
     (position + all resting orders on that side) and kept under 90% of the
     gross/net limit read from the server.  No breaches, no fines.

LOGS
  Console: fills, mode changes, stops, and a status line every second.
  Files (./logs/):  v3_ticks_<time>.csv   one row per loop (prices, positions, P&L)
                    v3_events_<time>.csv  every order, cancel, fill and decision
==============================================================================
"""
from __future__ import annotations

import argparse
import collections
import csv
import math
import os
import random
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

# =============================================================================
# CONFIG  (everything tunable is here)
# =============================================================================
# Case brief fees: (taker fee you PAY per share, maker rebate you GET per share)
# RY is inverted: taking EARNS 0.0014, resting COSTS 0.0020.
# Values are overwritten by the server's own numbers if /securities reports them.
FEES = {"CNR": (0.0027, 0.0023), "RY": (-0.0014, -0.0020), "AC": (0.0015, 0.0011)}
DEFAULT_TICKERS = ["CNR", "RY", "AC"]

MAX_ORDER = 5000            # brief: max shares per order
DEFAULT_LIMIT = 25000       # brief: gross and net limit (overwritten from /limits)
CAP_FRACTION = 0.93         # worst-case exposure never above 93% of the limit (23,250)

# --- speed ---
LOOP_MIN_DT = 0.025         # seconds; loop runs as fast as the server answers, max ~40 Hz
SLOW_POLL_SEC = 0.5         # /case and /trader refresh
HTTP_TIMEOUT = 1.5

# --- market making ---
QUOTE_SIZE = 3000           # shares per side at zero inventory (normal volatility)
QUOTE_SIZE_CALM = 5000      # calm, range-bound market: max size to harvest spread + rebates
WIDE_OK_MIN, WIDE_OK_MAX = 2, 6   # "healthy wide" spread (ticks): quote full 5,000 here;
                                  # the widest such name each loop also gets first call on limit room
SAFETY_FRACTION = 0.96      # if ACTUAL gross/net ever exceeds 96% of the limit (24,000), the bot
                            # stops all adding and crosses to cut the excess immediately
EXP_K = 3.0                 # adding-side size = size * exp(-EXP_K * inventory_ratio)
HALT_FRAC = 0.85            # adding side pulled completely at 85% of MM inventory cap
FADE_MAX_TICKS = 4          # adding-side quote fades back up to this many ticks at full inventory
BB_WINDOW_SEC = 30.0        # Bollinger window (mid samples every 0.25s)
BB_Z = 2.0                  # (kept for logs)
MR_MAX_INV = 0              # OFF: tested (8k/12k) and it LOST vs plain inventory-to-zero MM
                            # range-bound market: target inventory against stretched prices
                            # (long at the bottom of the band, short at the top), up to this
MR_Z_FULL = 2.0             # band z at which the mean-reversion target is full size
BB_LONG_TAU = 120.0         # baseline band width (seconds) to judge calm vs stressed
CALM_RATIO = 1.3            # band width / baseline below this = calm
STRESS_RATIO = 2.0          # above this = bands blowing out -> defensive quoting
MM_INV_CAP = 9000           # per-name inventory where the adding side stops quoting
INV_SKEW_TICKS = 2.0        # quote shift (ticks) at full MM inventory
LEAN_MAX_INV = 3000         # in a building trend, lean with it only up to this inventory
IMPROVE_MIN_SPREAD = 2      # step inside the touch when spread >= this many ticks
KEEP_FRAC = 0.35            # keep a resting quote (queue priority) while >= 35% unfilled
WIDE_SPREAD_TICKS = 12      # spread at/above this = thin book -> quote around fair
WIDE_EDGE_TICKS = 4         # min distance from fair for thin-book quotes
WIDE_SIZE = 2000            # size for thin-book quotes
# --- sweep catcher (the +$154k AC window in rit_algo2e_log): when a name's book has shown
# dislocations, rest small orders FAR from fair value. Someone's market order sweeping a thin
# book fills them at extreme prices (AC sold ~33-36 vs fair ~30), and price snaps back.
LADDER_PCT = [0.03, 0.08, 0.15]   # distance from robust fair value
LADDER_QTY = [1500, 1500, 2000]   # shares per level
LADDER_MEMORY = 300.0       # seconds a name stays "dislocation-prone" after one is seen
DISLOC_PCT = 0.02           # |mid - fair| this far, or a WIDE spread, counts as a dislocation
LADDER_TOL = 0.004          # keep a resting level unless fair moved > 0.4%

# --- inventory stop (MM positions) ---
STOP_MIN_TICKS = 5          # cut MM inventory this far underwater (per share)...
STOP_VOL_K = 3.0            # ...or this many x short-term vol, whichever larger
STOP_COOLDOWN = 3.0         # seconds the adding side stays off after a stop

# --- trend / directional engine ---
FAST_TAU = 1.0              # seconds
SLOW_TAU = 8.0              # seconds
FAIR_TAU = 3.0              # robust fair value (ignores thin-book mids)
DIR_MIN_TICKS = 8          # fast-slow EMA gap (ticks) needed to call a trend...
DIR_VOL_K = 4.0             # ...or this many x vol, whichever larger
DIR_CONFIRM_SEC = 0.5       # trend must hold this long before entering
DIR_MAX_SPREAD_TICKS = 6    # don't enter while the book is that wide
DIR_FRACTION = 0.95         # directional target = this x cap (shared across names)
DIR_EXIT_FRAC = 0.25        # exit when the gap falls below this x entry threshold
DIR_TRAIL_TICKS = 15        # trailing stop from best price (ticks)...
DIR_TRAIL_VOL_K = 6.0       # ...or this x vol, whichever larger
DIR_COOLDOWN = 2.0          # seconds before re-entering the same name
DIR_STALL_SEC = 8.0         # exit if the trend makes no new high/low for this long
DIR_MIN_SIZE = 1000         # don't bother entering smaller than this
DIR_ENABLED = True
MM_ENABLED = False           # False = directional only (no resting quotes, no sweep catcher)
DIR_ENTRY_FRAC = 0.8        # first fast-trend clip = this x directional size

# --- automatic regime detection (no manual switches needed) ---
ER_WINDOW_SEC = 10.0        # look-back for the efficiency ratio
ER_TREND = 0.40             # |net move| / path >= this  -> price is trending cleanly
ER_CHOP = 0.25              # below this -> choppy (back-and-forth)
DIR_MULT_MAX = 3.0          # losing trend rides raise that name's entry bar up to 3x
CHOP_LOCKOUT_RIDES = 3      # this many losing rides in a row ...
CHOP_LOCKOUT_SEC = 60.0     # ... switch the trend engine off on that name for this long
TOXIC_STOPS = 3             # this many MM stop-outs inside TOXIC_WINDOW ...
TOXIC_WINDOW = 60.0         # ... means flow is running us over:
TOXIC_SEC = 30.0            # ... halve quote size and stop stepping inside for this long
MM_LOSS_WINDOW = 45.0       # rolling window for each name's market-making P&L estimate
MM_LOSS_LIMIT = 2000.0      # MM on a name losing more than this in the window ...
MM_PAUSE_SEC = [20.0, 45.0, 90.0, 180.0]   # ... pauses MM there (escalating) and only reduces;
                            # each pause also halves that name's quote size (recovers x1.25/min)
CALM_MAX_STD_TICKS = 4.0    # "calm" also needs small absolute bands, not just small vs baseline

# --- RIT is asynchronous (~0.25 s): orders appear late, cancels land late, positions lag ---
VISIBILITY_GRACE = 1.5      # a just-sent order counts as live this long even if not yet listed
GONE_HOLD = 1.0             # an order that vanished still counts in exposure this long (position lag)
CANCEL_RESEND = 1.0         # don't re-send a cancel for the same order within this time
AGG_INTERVAL = 1.0          # never re-send a crossing order on a stale (unchanged) position
AGG_TTL = 0.6               # leftovers of crossing orders are cancelled after this

# --- slow trends measured in CASE TICKS (a grind like CNR 177.7 -> 176.4 in the 10/01 sim) ---
SLOW_TICKS = 20             # window in case ticks
SLOW_T_ENTER = 2.5          # t-stat of the net move to ride it
SLOW_T_LEAN = 2.0           # t-stat at which market making stops building inventory against it
SLOW_T_EXIT = 0.5
SLOW_MIN_TICKS = 10         # net move (price ticks) needed over the window
SLOW_FRACTION = 0.8         # slow rides use half the directional size
SLOW_STALL_TICKS = 10       # exit if no new extreme for this many case ticks

# --- aggressive order protection ---
AGG_THROUGH_TICKS = 3       # aggressive limit = touch +/- this many ticks
AGG_MAX_DEV = 0.02          # never pay more than 2% away from the fast fair value
AGG_CHUNK = 5000
LATENCY_SEC = 0.05          # starting guess only: the bot MEASURES RIT's real order latency live
                            # (POST -> order listed) and uses that; a friend saw ~0.25 s in ALGO2
SPEED_PULL_TICKS = 3.0      # if price would run this many ticks in LATENCY_SEC, pull the run-over side

# --- account-level risk ---
BREAKER_DD = 40000.0        # flatten + pause if P&L falls this far from its peak
BREAKER_PAUSE = 8.0

# --- end of case ---
UNWIND_START_SEC = 20.0     # stop adding, work out of positions
UNWIND_HARD_SEC = 8.0       # cross the spread to finish flat

HEARTBEAT_SEC = 1.0
LOG_DIR = "logs"


# =============================================================================
# REST CLIENT  (thread-safe, keep-alive, handles 429)
# =============================================================================
class RIT:
    def __init__(self, key: str, base: str):
        import requests
        self.requests = requests
        self.key, self.base = key, base.rstrip("/")
        self.local = threading.local()
        self.lock = threading.Lock()
        self.reads = self.writes = self.n429 = self.errors = 0

    def _sess(self):
        s = getattr(self.local, "s", None)
        if s is None:
            s = self.requests.Session()
            s.headers.update({"X-API-Key": self.key})
            ad = self.requests.adapters.HTTPAdapter(pool_connections=8, pool_maxsize=32)
            s.mount("http://", ad)
            self.local.s = s
        return s

    def req(self, method, path, params=None, write=False):
        for attempt in range(4):
            try:
                r = self._sess().request(method, self.base + path, params=params,
                                         timeout=HTTP_TIMEOUT)
            except Exception:
                with self.lock:
                    self.errors += 1
                time.sleep(0.05 * (attempt + 1))
                continue
            with self.lock:
                if write:
                    self.writes += 1
                else:
                    self.reads += 1
            if r.status_code == 429:
                with self.lock:
                    self.n429 += 1
                wait = 0.05
                try:
                    wait = float(r.json().get("wait", wait))
                except Exception:
                    try:
                        wait = float(r.headers.get("Retry-After", wait))
                    except Exception:
                        pass
                time.sleep(min(max(wait, 0.01), 0.5))
                continue
            if r.status_code == 401:
                # RIT also answers 401 "Simulation must be running" between cases: not fatal.
                return {"_error": 401, "body": r.text[:160]}
            if r.ok:
                try:
                    return r.json()
                except Exception:
                    return {}
            return {"_error": r.status_code, "body": r.text[:160]}
        return {"_error": "no-response"}

    # reads
    def case(self): return self.req("GET", "/case")
    def trader(self): return self.req("GET", "/trader")
    def limits(self): return self.req("GET", "/limits")
    def securities(self): return self.req("GET", "/securities")
    def book(self, t): return self.req("GET", "/securities/book", {"ticker": t, "limit": 20})
    def open_orders(self): return self.req("GET", "/orders", {"status": "OPEN"})

    # writes
    def place(self, t, action, qty, price):
        return self.req("POST", "/orders", {"ticker": t, "type": "LIMIT", "quantity": int(qty),
                                            "action": action, "price": round(price, 4)}, write=True)

    def cancel(self, oid): return self.req("DELETE", f"/orders/{oid}", write=True)
    def cancel_all(self): return self.req("POST", "/commands/cancel", {"all": 1}, write=True)


# =============================================================================
# PER-SECURITY STATE
# =============================================================================
class Sec:
    def __init__(self, t):
        self.t = t
        self.tick = 0.01
        self.fee_take, self.fee_make = FEES.get(t, (0.002, 0.0))
        self.pos = 0
        self.vwap = 0.0
        self.realized = self.unrealized = 0.0
        self.bid = self.ask = 0.0           # best bid/ask EXCLUDING our own orders
        self.bid_sz = self.ask_sz = 0
        self.last = 0.0
        self.fast = self.slow = self.fair = None
        self.vol = 1.0                      # noise: ticks per 0.5 s around the drift
        self.drift = 0.0
        self.vel = 0.0                      # signed price speed, ticks per second (~1 s memory)
        self.prev_mid = None
        self.vol_ref_mid = None
        self.vol_ref_t = 0.0
        self.last_t = None
        self.mode = "mm"                    # mm | dir | cut
        self.dir_side = 0
        self.dir_target = 0
        self.dir_best = 0.0
        self.dir_best_t = 0.0
        self.last_exit = None               # (side, best price) of the last trend ride
        self.trend_since = None
        self.cool_until = 0.0               # directional re-entry cooldown
        self.no_buy_until = 0.0             # MM stop cooldowns
        self.no_sell_until = 0.0
        self.orders = []                    # our live orders on this name (from the registry)
        self.agg_block_until = 0.0
        self.agg_pos_ref = None
        self.tick_mids = collections.deque(maxlen=SLOW_TICKS + 1)
        self.last_case_tick = None
        self.t_slow = 0.0
        self.net_slow = 0.0                 # price ticks over the slow window
        self.sd_slow = 1.0                  # per-case-tick sd (price ticks)
        self.dir_kind = "fast"
        self.gap = 0.0                      # fast-slow in ticks
        self.hist = collections.deque()     # (t, mid) for the efficiency ratio
        self.hist_t = 0.0
        self.er = 0.0                       # efficiency ratio 0..1
        self.net_ticks = 0.0                # net move over the window
        self.regime = "warmup"
        self.dir_mult = 1.0                 # learned: >1 after losing trend rides
        self.lose_streak = 0
        self.dir_off_until = 0.0
        self.dir_entry_mid = 0.0
        self.rides = [0, 0]                 # [wins, losses]
        self.stop_times = collections.deque()
        self.toxic_until = 0.0
        self.est_pnl = 0.0                  # own MTM estimate (robust to odd server fields)
        self.est_mid = None
        self.est_pos = 0
        self.pnl_hist = collections.deque() # (t, est_pnl) sampled 1/s
        self.pnl_hist_t = 0.0
        self.mm_off_until = 0.0
        self.mm_pauses = 0
        self.size_mult = 1.0
        self.mr_tgt = 0
        self.disloc_t = -1e9                # last time the book looked dislocated
        self.ladder = []
        self.size_t = 0.0
        self.trend_hold = False             # regime hysteresis
        self.bbq = collections.deque()      # Bollinger samples
        self.bb_t = 0.0
        self.bb_z = 0.0
        self.bb_std = 0.0                   # ticks
        self.bw_long = None                 # baseline band width (ticks)
        self.vstate = "normal"              # calm | normal | stressed

    @property
    def spread_ticks(self):
        if self.bid > 0 and self.ask > 0:
            return round((self.ask - self.bid) / self.tick)
        return 999

    @property
    def mid(self):
        if self.bid > 0 and self.ask > 0:
            return 0.5 * (self.bid + self.ask)
        return self.fair or self.last or 0.0

    def rnd(self, p):
        return round(round(p / self.tick) * self.tick, 6)

    def update_slow(self, case_tick):
        if case_tick is None or case_tick == self.last_case_tick:
            return
        self.last_case_tick = case_tick
        good = self.bid > 0 and self.ask > self.bid and self.spread_ticks < WIDE_SPREAD_TICKS
        if not good:
            return
        self.tick_mids.append(self.mid)
        if len(self.tick_mids) >= 12:
            xs = list(self.tick_mids)
            d = [(b - a) / self.tick for a, b in zip(xs, xs[1:])]
            n = len(d)
            mu = sum(d) / n
            sd = math.sqrt(sum((x - mu) ** 2 for x in d) / max(1, n - 1))
            self.sd_slow = max(sd, 0.5)
            self.net_slow = (xs[-1] - xs[0]) / self.tick
            self.t_slow = self.net_slow / (self.sd_slow * math.sqrt(n))

    def update_signals(self, now):
        good = self.bid > 0 and self.ask > self.bid and self.spread_ticks < WIDE_SPREAD_TICKS
        m = self.mid
        if m <= 0:
            return
        if self.fast is None:
            self.fast = self.slow = self.fair = m
            self.vol_ref_mid, self.vol_ref_t, self.last_t = m, now, now
            return
        dt = max(1e-3, now - self.last_t)
        self.last_t = now
        if good:
            if self.est_mid is not None:
                self.est_pnl += self.est_pos * (m - self.est_mid)
            d = self.pos - self.est_pos
            if d:
                # assume fills at our side of the touch: earn half the spread vs mid
                self.est_pnl += abs(d) * 0.5 * (self.ask - self.bid) * (1 if self.mode == "mm" else -1)
            self.est_mid, self.est_pos = m, self.pos
            if now - self.pnl_hist_t >= 1.0:
                self.pnl_hist_t = now
                self.pnl_hist.append((now, self.est_pnl))
                while self.pnl_hist and now - self.pnl_hist[0][0] > MM_LOSS_WINDOW:
                    self.pnl_hist.popleft()
        if good:
            if self.prev_mid is not None:
                inst = (m - self.prev_mid) / self.tick / dt
                self.vel += (1 - math.exp(-dt / 1.0)) * (max(-200.0, min(200.0, inst)) - self.vel)
            self.prev_mid = m
            self.fast += (1 - math.exp(-dt / FAST_TAU)) * (m - self.fast)
            self.slow += (1 - math.exp(-dt / SLOW_TAU)) * (m - self.slow)
            self.fair += (1 - math.exp(-dt / FAIR_TAU)) * (m - self.fair)
            if now - self.vol_ref_t >= 0.5:
                d = (m - self.vol_ref_mid) / self.tick
                d = max(-50.0, min(50.0, d))
                self.drift = 0.9 * self.drift + 0.1 * d            # ticks / 0.5s (trend part)
                self.vol = 0.9 * self.vol + 0.1 * abs(d - self.drift)  # noise around the trend
                self.vol_ref_mid, self.vol_ref_t = m, now
        self.gap = (self.fast - self.slow) / self.tick
        if self.fair and (self.spread_ticks >= WIDE_SPREAD_TICKS
                          or (m > 0 and abs(m - self.fair) >= DISLOC_PCT * self.fair)):
            self.disloc_t = now
        if good and now - self.bb_t >= 0.25:
            self.bb_t = now
            self.bbq.append((now, m))
            while self.bbq and now - self.bbq[0][0] > BB_WINDOW_SEC:
                self.bbq.popleft()
            if len(self.bbq) >= 20:
                xs = [x[1] for x in self.bbq]
                mu = sum(xs) / len(xs)
                sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / len(xs))
                self.bb_std = max(sd / self.tick, 0.5)
                self.bb_z = (m - mu) / (self.bb_std * self.tick)
                if self.bw_long is None:
                    self.bw_long = self.bb_std
                else:
                    self.bw_long += (1 - math.exp(-0.25 / BB_LONG_TAU)) * (self.bb_std - self.bw_long)
                ratio = self.bb_std / max(self.bw_long, 0.5)
                self.vstate = ("stressed" if ratio > STRESS_RATIO or self.regime == "TREND"
                               else "calm" if (ratio < CALM_RATIO and self.regime == "chop"
                                               and self.bb_std <= CALM_MAX_STD_TICKS) else "normal")
        if good and now - self.hist_t >= 0.25:
            self.hist_t = now
            self.hist.append((now, m))
            while self.hist and now - self.hist[0][0] > ER_WINDOW_SEC:
                self.hist.popleft()
            if len(self.hist) >= 8 and now - self.hist[0][0] >= 0.6 * ER_WINDOW_SEC:
                mids = [x[1] for x in self.hist]
                path = sum(abs(b - a) for a, b in zip(mids, mids[1:]))
                net = mids[-1] - mids[0]
                self.er = abs(net) / path if path > 0 else 0.0
                self.net_ticks = net / self.tick
                enter = self.er >= ER_TREND and abs(self.net_ticks) >= DIR_MIN_TICKS
                stay = self.regime == "TREND" and self.er >= ER_TREND - 0.12 and abs(self.net_ticks) >= 0.6 * DIR_MIN_TICKS
                if enter or stay:
                    self.regime = "TREND"
                elif self.er < ER_CHOP:
                    self.regime = "chop"
                else:
                    self.regime = "mixed"

    def dir_threshold(self):
        return max(DIR_MIN_TICKS, DIR_VOL_K * self.vol) * self.dir_mult


# =============================================================================
# LOGGING
# =============================================================================
class Log:
    def __init__(self, tickers, tag="v3"):
        os.makedirs(LOG_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{os.environ.get('ALGO_TAG', '')}pid{os.getpid()}"
        self.tick_path = os.path.join(LOG_DIR, f"{tag}_ticks_{stamp}.csv")
        self.ev_path = os.path.join(LOG_DIR, f"{tag}_events_{stamp}.csv")
        self.tf = open(self.tick_path, "w", newline="")
        self.ef = open(self.ev_path, "w", newline="")
        self.tw = csv.writer(self.tf)
        self.ew = csv.writer(self.ef)
        hdr = ["t", "case_tick", "sec_left", "pnl", "nlv", "gross", "net"]
        for t in tickers:
            hdr += [f"{t}_bid", f"{t}_ask", f"{t}_fair", f"{t}_gap", f"{t}_vol", f"{t}_er", f"{t}_regime",
                    f"{t}_bbz", f"{t}_vstate", f"{t}_tslow",
                    f"{t}_pos", f"{t}_mode", f"{t}_pnl"]
        self.tw.writerow(hdr)
        self.ew.writerow(["t", "case_tick", "event", "ticker", "side", "qty", "price", "pos", "note"])
        self.last_flush = time.time()
        self.lock = threading.Lock()

    def tick_row(self, row):
        with self.lock:
            self.tw.writerow(row)
            self._maybe_flush()

    def event(self, t, ctick, ev, ticker="", side="", qty="", price="", pos="", note="",
              echo=False):
        with self.lock:
            self.ew.writerow([f"{t:.3f}", ctick, ev, ticker, side, qty,
                              f"{price:.4f}" if isinstance(price, float) else price, pos, note])
            self._maybe_flush()
        if echo:
            px = f" @ {price:.2f}" if isinstance(price, float) and price else ""
            q = f" {qty}" if qty != "" else ""
            print(f"[{t:7.1f}s] {ev.upper():<8} {ticker:<4} {side}{q}{px}  {note}", flush=True)

    def _maybe_flush(self):
        if time.time() - self.last_flush > 1.0:
            self.tf.flush()
            self.ef.flush()
            self.last_flush = time.time()

    def close(self):
        with self.lock:
            self.tf.flush(); self.ef.flush()
            self.tf.close(); self.ef.close()


# =============================================================================
# BOT
# =============================================================================
# Time windows that should stretch with the case clock (sqrt-scaled, clamped, so fast shocks
# are still caught when the case is stretched). Reference: 300 ticks in 10 min = 2 s/tick.
SPT_REF = 2.0
_SCALED = ["ER_WINDOW_SEC", "BB_WINDOW_SEC", "BB_LONG_TAU", "SLOW_TAU", "FAIR_TAU",
           "DIR_STALL_SEC", "MM_LOSS_WINDOW", "TOXIC_WINDOW"]
_BASE = {}


def apply_time_scale(spt):
    """Rescale time windows to the case speed (seconds per case tick)."""
    g = globals()
    if not _BASE:
        _BASE.update({k: g[k] for k in _SCALED})
    k = max(0.6, min(1.8, math.sqrt(max(spt, 0.05) / SPT_REF)))
    for name in _SCALED:
        g[name] = _BASE[name] * k
    return k


class Bot:
    def __init__(self, api, tickers=None, minutes=None):
        self.api = api
        self.pool = ThreadPoolExecutor(max_workers=16)
        self.secs = {}
        self.tickers = list(tickers or [])
        self.trader_id = None
        self.gross_limit = self.net_limit = DEFAULT_LIMIT
        self.cap_gross = self.cap_net = int(CAP_FRACTION * DEFAULT_LIMIT)
        self.t0 = time.time()
        self.case = {}
        self.case_tick = 0
        self.tpp = 300
        self.status = "?"
        self.sec_per_tick = None
        self._tick_anchor = None
        self.nlv0 = None
        self.nlv = None
        self.pnl = 0.0
        self.peak = 0.0
        self.paused_until = 0.0
        self.last_slow = 0.0
        self.last_beat = 0.0
        self.running = True
        self.flattening = False
        self.widest = None
        self.live = {}                      # order_id -> record (our own order registry)
        self.lat_est = LATENCY_SEC          # measured live
        self.over = 0                       # actual exposure above cap (shares)
        self.loops = 0
        self.places = 0
        self.cancels = 0
        self.log = None
        self.unwind_announced = False
        self.hard_announced = False
        self.period = None
        self.minutes = minutes              # user-supplied case length (wall minutes), optional
        self.time_scale = None

    # ------------------------------------------------------------------ setup
    def now(self):
        return time.time() - self.t0

    def setup(self):
        print("=" * 78)
        print(" RIT ALGO 2e DIR-AGGRESSIVE - directional only (earlier entries, bigger size, no quoting)")
        print("=" * 78)
        while True:
            c = self.api.case()
            if isinstance(c, dict) and not c.get("_error"):
                break
            print(f"[setup] cannot reach RIT ({c}); retrying...", flush=True)
            time.sleep(1.0)
        self.case = c
        print(f"[case] {c.get('name', '?')}  status={c.get('status')}  tick={c.get('tick')}"
              f"/{c.get('ticks_per_period')}  limits enforced={c.get('is_enforce_trading_limits')}")
        self.tpp = int(c.get("ticks_per_period") or self.tpp)
        if self.minutes:
            self.sec_per_tick = self.minutes * 60.0 / self.tpp
            self.time_scale = apply_time_scale(self.sec_per_tick)
            print(f"[clock] you said {self.minutes:g} min for {self.tpp} ticks -> {self.sec_per_tick:.2f} s/tick;"
                  f" time windows x{self.time_scale:.2f}. The bot keeps checking the real clock.")
        else:
            print("[clock] no duration given: learning seconds-per-tick from the case clock")
        tr = self.api.trader()
        if isinstance(tr, dict):
            self.trader_id = tr.get("trader_id")
            print(f"[trader] id={self.trader_id}  NLV={tr.get('nlv')}")
        lim = self.api.limits()
        if isinstance(lim, list) and lim:
            g = sum(float(x.get("gross_limit") or 0) for x in lim) or DEFAULT_LIMIT
            n = sum(float(x.get("net_limit") or 0) for x in lim) or DEFAULT_LIMIT
            self.gross_limit, self.net_limit = int(g), int(n)
            fines = [(x.get("gross_fine"), x.get("net_fine")) for x in lim]
            print(f"[limits] gross {self.gross_limit:,}  net {self.net_limit:,}  fines {fines}")
        self.cap_gross = int(CAP_FRACTION * self.gross_limit)
        self.cap_net = int(CAP_FRACTION * self.net_limit)
        print(f"[limits] bot hard caps (worst case incl. resting orders): gross {self.cap_gross:,}"
              f"  net {self.cap_net:,}")
        secs = self.api.securities()
        if isinstance(secs, list) and secs:
            found = [s.get("ticker") for s in secs if s.get("ticker")]
            if not self.tickers:
                self.tickers = [x["ticker"] for x in secs if x.get("ticker")
                                and str(x.get("is_tradeable", True)).lower() != "false"]
            print(f"[sec] server lists: {found}")
        if not self.tickers:
            self.tickers = list(DEFAULT_TICKERS)
        for t in self.tickers:
            self.secs[t] = Sec(t)
        self._apply_securities(secs if isinstance(secs, list) else [], first=True)
        for t, s in self.secs.items():
            print(f"[sec] {t:<4} tick {s.tick}  taker fee {s.fee_take:+.4f}  maker rebate"
                  f" {s.fee_make:+.4f}  pos {s.pos}")
        self.log = Log(self.tickers)
        print(f"[log] ticks  -> {self.log.tick_path}")
        print(f"[log] events -> {self.log.ev_path}")
        print("-" * 78, flush=True)

    # ------------------------------------------------------------- data intake
    def _apply_securities(self, secs, first=False):
        for row in secs:
            t = row.get("ticker")
            s = self.secs.get(t)
            if not s:
                continue
            old = s.pos
            s.pos = int(row.get("position") or 0)
            s.vwap = float(row.get("vwap") or 0)
            s.realized = float(row.get("realized") or 0)
            s.unrealized = float(row.get("unrealized") or 0)
            s.last = float(row.get("last") or 0)
            if first:
                qd = row.get("quoted_decimals")
                if qd is not None:
                    s.tick = 10 ** (-int(qd))
                tf, rb = row.get("trading_fee"), row.get("limit_order_rebate")
                if tf is not None and rb is not None:
                    s.fee_take, s.fee_make = float(tf), float(rb)
            elif s.pos != old and self.log:
                d = s.pos - old
                self.log.event(self.now(), self.case_tick, "fill", t, "BUY" if d > 0 else "SELL",
                               abs(d), s.mid, s.pos, f"mode={s.mode}",
                               echo=abs(d) >= 1000 or s.mode != "mm")

    def _apply_book(self, s, book):
        if not isinstance(book, dict) or book.get("_error"):
            return
        mine = {oid for oid, r in self.live.items() if r["ticker"] == s.t}

        def best(levels):
            for lv in levels or []:
                if lv.get("order_id") in mine:
                    continue
                if self.trader_id and lv.get("trader_id") == self.trader_id:
                    continue
                rem = float(lv.get("quantity", 0)) - float(lv.get("quantity_filled", 0))
                if rem <= 0:
                    continue
                return float(lv["price"]), int(rem)
            return 0.0, 0

        s.bid, s.bid_sz = best(book.get("bids"))
        s.ask, s.ask_sz = best(book.get("asks"))

    def refresh(self):
        now = self.now()
        futs = {}
        if now - self.last_slow >= SLOW_POLL_SEC:
            futs["case"] = self.pool.submit(self.api.case)
            futs["trader"] = self.pool.submit(self.api.trader)
            self.last_slow = now
        futs["orders"] = self.pool.submit(self.api.open_orders)   # snapshot BEFORE positions
        futs["secs"] = self.pool.submit(self.api.securities)
        books = {t: self.pool.submit(self.api.book, t) for t in self.tickers}

        t_snap = time.time()
        orders = futs["orders"].result()
        if isinstance(orders, list):
            self._sync_orders(orders, t_snap)
        secs = futs["secs"].result()
        if isinstance(secs, list):
            self._apply_securities(secs)
        for t, f in books.items():
            self._apply_book(self.secs[t], f.result())
        if "case" in futs:
            c = futs["case"].result()
            if isinstance(c, dict) and not c.get("_error"):
                self.case = c
                self.status = c.get("status", "?")
                tick = int(c.get("tick") or 0)
                self.tpp = int(c.get("ticks_per_period") or self.tpp)
                per = c.get("period")
                if per != self.period:
                    self.period = per
                    self._tick_anchor = None
                if tick > 0:
                    if self._tick_anchor is None or tick < self._tick_anchor[1]:
                        self._tick_anchor = (time.time(), tick)
                    elif tick - self._tick_anchor[1] >= 3:
                        measured = (time.time() - self._tick_anchor[0]) / (tick - self._tick_anchor[1])
                        if not self.minutes or tick - self._tick_anchor[1] >= 10:
                            # trust the real clock once it has 10 ticks (or at once if no input)
                            if (self.sec_per_tick and abs(measured / self.sec_per_tick - 1) > 0.25
                                    and tick - self._tick_anchor[1] in (10, 11)):
                                print(f"[clock] measured {measured:.2f} s/tick differs from expected "
                                      f"{self.sec_per_tick:.2f}: using measured", flush=True)
                            self.sec_per_tick = measured
                            if self.time_scale is None or abs(apply_time_scale(measured) - self.time_scale) > 0.1:
                                self.time_scale = apply_time_scale(measured)
                self.case_tick = tick
            tr = futs["trader"].result()
            if isinstance(tr, dict) and tr.get("nlv") is not None:
                self.nlv = float(tr["nlv"])
                if self.nlv0 is None:
                    self.nlv0 = self.nlv
        now = self.now()
        for s in self.secs.values():
            before = s.regime
            s.update_signals(now)
            s.update_slow(self.case_tick if self.status == "ACTIVE" else None)
            if s.regime != before and self.log and before != "warmup":
                loud = (s.regime == "TREND" or before == "TREND") and now - getattr(s, "_last_echo", -9) > 3
                if loud:
                    s._last_echo = now
                self.log.event(now, self.case_tick, "regime", s.t, note=
                               f"{before} -> {s.regime} (er={s.er:.2f}, net {s.net_ticks:+.0f}t over "
                               f"{ER_WINDOW_SEC:.0f}s)", echo=loud)
        if self.nlv is not None and self.nlv0 is not None:
            self.pnl = self.nlv - self.nlv0
        else:
            self.pnl = sum(s.realized + s.unrealized for s in self.secs.values())
        self.peak = max(self.peak, self.pnl)

    def unwind_windows(self):
        total = self.tpp * (self.sec_per_tick or 1.0)
        return (min(UNWIND_START_SEC, max(6.0, 0.05 * total)),
                min(UNWIND_HARD_SEC, max(3.0, 0.02 * total)))

    def _sync_orders(self, snapshot, t_snap):
        """Merge RIT's open-order snapshot into our registry. Orders RIT hasn't listed yet
        (sent < VISIBILITY_GRACE ago) stay live; orders that vanished keep counting in
        exposure for GONE_HOLD (their fill may not be in the position yet)."""
        seen = set()
        for o in snapshot:
            oid = o.get("order_id")
            if oid is None:
                continue
            seen.add(oid)
            rec = self.live.get(oid)
            if rec is None:
                rec = {"order_id": oid, "ticker": o.get("ticker"), "action": o.get("action"),
                       "price": float(o.get("price") or 0), "t_sent": t_snap, "kind": "quote"}
                self.live[oid] = rec
            rec["quantity"] = int(o.get("quantity") or 0)
            rec["quantity_filled"] = int(o.get("quantity_filled") or 0)
            if not rec.get("seen") and rec.get("state") == "new":
                lat = t_snap - rec["t_sent"]            # POST -> first listed (upper bound)
                if 0 <= lat < 3:
                    self.lat_est += 0.2 * (lat - self.lat_est)
            rec["seen"] = True
            rec["state"] = "open"
        for oid, rec in list(self.live.items()):
            if oid in seen:
                continue
            if rec["state"] == "new" and t_snap - rec["t_sent"] < VISIBILITY_GRACE:
                continue                                    # not listed yet: still live
            if rec["state"] != "gone":
                rec["state"] = "gone"
                rec["t_gone"] = t_snap
            elif t_snap - rec["t_gone"] > GONE_HOLD:
                del self.live[oid]
        for s in self.secs.values():
            s.orders = [r for r in self.live.values() if r["ticker"] == s.t and r["state"] in ("new", "open")]

    def sec_left(self):
        spt = self.sec_per_tick or 1.0
        return max(0.0, (self.tpp - self.case_tick) * spt)

    # --------------------------------------------------------------- exposure
    def _resting(self, s, side):
        """Shares that could still fill on this side: listed, not-yet-listed, cancel-pending,
        and just-vanished orders (whose fill may not be in the position yet)."""
        # FULL order size, not the unfilled remainder: a partial fill may not be in the
        # (lagging) reported position yet, so the filled part must still be counted
        return sum(int(r["quantity"])
                   for r in self.live.values() if r["ticker"] == s.t and r["action"] == side)

    def _inflight_agg(self, s, side):
        t_wall = time.time()
        return sum(int(r["quantity"]) for r in self.live.values()
                   if r["ticker"] == s.t and r["action"] == side and r.get("kind") == "agg"
                   and t_wall - r["t_sent"] < AGG_INTERVAL)

    def exposure_ok(self, t, side, qty, pending):
        """Worst case: every order we have (resting, not yet listed, cancel-pending, or just
        filled but not yet in the lagging position) fills on the SAME side as this one.
        A buy may never push the all-buys-fill net or gross above the cap, and a sell the
        all-sells-fill net or gross, unless it only shrinks a short (long) on that name."""
        gross = 0
        nl = ns = 0
        L_t = S_t = 0
        for name, s in self.secs.items():
            rb = self._resting(s, "BUY") + pending.get((name, "BUY"), 0)
            rs = self._resting(s, "SELL") + pending.get((name, "SELL"), 0)
            L, S = s.pos + rb, s.pos - rs
            if name == t:
                if side == "BUY":
                    L += qty
                else:
                    S -= qty
                L_t, S_t = L, S
            gross += max(abs(L), abs(S)); nl += L; ns += S
        if side == "BUY":
            if nl > self.cap_net:
                return False
            return gross <= self.cap_gross or L_t <= 0
        if ns < -self.cap_net:
            return False
        return gross <= self.cap_gross or S_t >= 0

    def fit_qty(self, t, side, qty, pending):
        qty = int(min(qty, MAX_ORDER))
        while qty >= 1:
            if self.exposure_ok(t, side, qty, pending):
                return qty
            if qty <= 100:
                return 0
            qty = max(100, int(qty * 0.6) // 100 * 100)
        return 0

    # --------------------------------------------------------------- decisions
    def agg_price(self, s, side):
        """Marketable limit with price protection. Returns None if the book is crazy."""
        ref = s.fast or s.mid
        dev = max(AGG_MAX_DEV * ref, 10 * s.tick)
        if side == "BUY":
            if s.ask <= 0:
                return None
            run = max(0.0, s.vel) * self.lat_est * 1.5        # price runs away while the order travels
            px = s.ask + (AGG_THROUGH_TICKS + math.ceil(run)) * s.tick
            if s.ask > ref + dev:
                return None
            return s.rnd(min(px, ref + dev))
        if s.bid <= 0:
            return None
        run = max(0.0, -s.vel) * self.lat_est * 1.5
        px = s.bid - (AGG_THROUGH_TICKS + math.ceil(run)) * s.tick
        if s.bid < ref - dev:
            return None
        return s.rnd(max(px, ref - dev))

    def decide(self, s, now, sec_left):
        """Returns (passive: list of (side, price, qty), aggressive: list of (side, price, qty))."""
        passive, aggressive = [], []
        s.ladder = []
        if s.fast is None or (s.bid <= 0 and s.ask <= 0):
            return passive, aggressive

        u_start, u_hard = self.unwind_windows()
        unwinding = sec_left <= u_start
        hard = sec_left <= u_hard or self.flattening or now < self.paused_until

        # ---------- end of case / breaker: get flat
        if hard:
            if s.pos != 0:
                side = "SELL" if s.pos > 0 else "BUY"
                px = self.agg_price(s, side)
                if px is not None:
                    aggressive.append((side, px, min(abs(s.pos), AGG_CHUNK)))
            s.mode = "mm"
            return passive, aggressive

        thr = s.dir_threshold()
        tick = s.tick

        # ---------- directional engine
        if DIR_ENABLED and not unwinding:
            if s.mode == "dir":
                m = s.mid
                if s.dir_side * (m - s.dir_best) > 0:
                    s.dir_best, s.dir_best_t = m, now
                drawdown = s.dir_side * (s.dir_best - m) / tick
                # a fast trend that shows up while riding a slow one upgrades the ride
                if s.dir_kind == "slow" and s.dir_side * s.gap > thr and s.er >= ER_TREND:
                    s.dir_kind = "fast"
                if s.dir_kind == "slow":
                    spt = self.sec_per_tick or 1.0
                    trail = max(DIR_TRAIL_TICKS, 3.0 * s.sd_slow * math.sqrt(5))
                    fading = s.dir_side * s.t_slow < SLOW_T_EXIT
                    stall_sec = SLOW_STALL_TICKS * spt
                else:
                    trail = max(DIR_TRAIL_TICKS, DIR_TRAIL_VOL_K * s.vol)
                    # fast ride ends when the fast gap fades, unless the slow trend still holds
                    fading = (s.dir_side * s.gap < DIR_EXIT_FRAC * thr
                              and s.dir_side * s.t_slow < SLOW_T_ENTER)
                    stall_sec = DIR_STALL_SEC
                stalled = now - s.dir_best_t > stall_sec
                if drawdown > trail or fading or stalled:
                    why = (f"{s.dir_kind} trail {drawdown:.0f}>{trail:.0f}t" if drawdown > trail else
                           f"{s.dir_kind} trend faded (gap={s.gap:.1f}t, t_slow={s.t_slow:.1f})" if fading else
                           f"{s.dir_kind} stalled {stall_sec:.0f}s without new extreme")
                    self.log.event(now, self.case_tick, "dir_exit", s.t, "", s.pos, s.mid, s.pos, why, echo=True)
                    s.mode = "cut"
                    s.cool_until = now + DIR_COOLDOWN
                    s.last_exit = (s.dir_side, s.dir_best)
                    self.learn_ride(s, now)
                elif s.dir_kind == "fast":
                    # grow target with strength, never shrink while trend holds
                    strength = min(1.0, 0.6 + 0.4 * (abs(s.gap) / thr - 1.0))
                    tgt = int(self.dir_cap(s) * strength)
                    s.dir_target = s.dir_side * max(abs(s.dir_target), tgt)
            elif (now >= s.cool_until and now >= s.dir_off_until and abs(s.gap) > thr
                  and s.er >= ER_TREND and s.net_ticks * s.gap > 0
                  and s.spread_ticks <= DIR_MAX_SPREAD_TICKS and self.dir_cap(s) >= DIR_MIN_SIZE):
                side = 1 if s.gap > 0 else -1
                fresh = (s.last_exit is None or s.last_exit[0] != side
                         or side * (s.mid - s.last_exit[1]) > 0.5 * thr * tick)
                if not fresh:
                    s.trend_since = None
                elif s.trend_since is None or s.trend_since[1] != side:
                    s.trend_since = (now, side)
                elif now - s.trend_since[0] >= DIR_CONFIRM_SEC:
                    s.mode, s.dir_side, s.dir_best, s.dir_best_t = "dir", side, s.mid, now
                    s.dir_entry_mid = s.mid
                    s.dir_kind = "fast"
                    s.dir_target = side * int(self.dir_cap(s) * DIR_ENTRY_FRAC)
                    self.log.event(now, self.case_tick, "dir_enter", s.t, "LONG" if side > 0 else "SHORT",
                                   abs(s.dir_target), s.mid, s.pos,
                                   f"gap={s.gap:.1f}t thr={thr:.1f}t er={s.er:.2f} vol={s.vol:.1f}", echo=True)
            elif (now >= s.cool_until and now >= s.dir_off_until
                  and abs(s.t_slow) >= SLOW_T_ENTER * s.dir_mult and abs(s.net_slow) >= SLOW_MIN_TICKS
                  and s.spread_ticks <= DIR_MAX_SPREAD_TICKS and self.dir_cap(s) >= DIR_MIN_SIZE
                  and (s.last_exit is None or s.last_exit[0] != (1 if s.t_slow > 0 else -1)
                       or (1 if s.t_slow > 0 else -1) * (s.mid - s.last_exit[1]) > 0)):
                side = 1 if s.t_slow > 0 else -1
                s.mode, s.dir_side, s.dir_best, s.dir_best_t = "dir", side, s.mid, now
                s.dir_entry_mid = s.mid
                s.dir_kind = "slow"
                s.dir_target = side * int(self.dir_cap(s) * SLOW_FRACTION)
                self.log.event(now, self.case_tick, "dir_enter", s.t, "LONG" if side > 0 else "SHORT",
                               abs(s.dir_target), s.mid, s.pos,
                               f"SLOW trend t={s.t_slow:.1f} net={s.net_slow:+.0f}t over {len(s.tick_mids)} case ticks",
                               echo=True)
            else:
                s.trend_since = None
        elif s.mode == "dir":
            s.mode = "cut"

        if s.mode == "dir":
            diff = s.dir_target - s.pos - (self._resting(s, "BUY") if s.dir_side > 0 else -self._resting(s, "SELL"))
            if s.dir_side * diff >= 200:
                side = "BUY" if s.dir_side > 0 else "SELL"
                px = self.agg_price(s, side)
                if px is not None:
                    aggressive.append((side, px, min(abs(diff), AGG_CHUNK)))
            return passive, aggressive

        if s.mode == "cut":
            if s.pos == 0:
                s.mode = "mm"
            else:
                side = "SELL" if s.pos > 0 else "BUY"
                px = self.agg_price(s, side)
                if px is not None:
                    aggressive.append((side, px, min(abs(s.pos), AGG_CHUNK)))
                return passive, aggressive

        if not MM_ENABLED:
            return passive, aggressive          # directional-only build: no quoting at all

        # ---------- self-check: is market making on this name bleeding?
        if s.pnl_hist and now >= s.mm_off_until:
            peak = max(v for _, v in s.pnl_hist)
            # faster case clock = bigger normal P&L swings per second: scale the limit
            # (sample sims ran ~9 s/tick; a 10-20 min case runs ~2-4 s/tick)
            speed = min(4.0, max(1.0, 9.0 / self.sec_per_tick)) if self.sec_per_tick else 1.0
            if peak - s.est_pnl > MM_LOSS_LIMIT * speed:
                pause = MM_PAUSE_SEC[min(s.mm_pauses, len(MM_PAUSE_SEC) - 1)]
                s.mm_pauses += 1
                s.mm_off_until = now + pause
                s.size_mult = max(0.25, s.size_mult * 0.5)
                s.size_t = now
                s.pnl_hist.clear()
                self.log.event(now, self.case_tick, "regime", s.t, note=
                               f"MM lost ${peak - s.est_pnl:,.0f} (limit ${MM_LOSS_LIMIT * speed:,.0f}) in <{MM_LOSS_WINDOW:.0f}s ({s.regime}) -> "
                               f"pause quoting {pause:.0f}s, reduce only", echo=True)
        mm_paused = now < s.mm_off_until

        # ---------- MM inventory stop
        if s.pos != 0:
            per_share = s.unrealized / abs(s.pos) if s.unrealized else (
                (s.mid - s.vwap) * (1 if s.pos > 0 else -1) if s.vwap else 0.0)
            if abs(per_share) > 0.5 * max(s.mid, 1):        # nonsense number from server
                per_share = (s.mid - s.vwap) * (1 if s.pos > 0 else -1) if s.vwap else 0.0
            loss_ticks = -per_share / tick
            stop = max(STOP_MIN_TICKS, STOP_VOL_K * s.vol)
            if s.regime != "TREND" and abs(s.t_slow) < SLOW_T_LEAN and s.mr_tgt * s.pos > 0:
                stop = max(stop, 1.5 * s.bb_std)     # deliberate range position: give it the band
            against_trend = (s.pos > 0 and s.gap < -0.7 * thr) or (s.pos < 0 and s.gap > 0.7 * thr)
            if loss_ticks > stop or against_trend:
                side = "SELL" if s.pos > 0 else "BUY"
                px = self.agg_price(s, side)
                if px is not None:
                    aggressive.append((side, px, min(abs(s.pos), AGG_CHUNK)))
                    if s.pos > 0:
                        s.no_buy_until = now + STOP_COOLDOWN
                    else:
                        s.no_sell_until = now + STOP_COOLDOWN
                    if self._inflight_agg(s, side) == 0:
                        s.stop_times.append(now)
                    while s.stop_times and now - s.stop_times[0] > TOXIC_WINDOW:
                        s.stop_times.popleft()
                    if len(s.stop_times) >= TOXIC_STOPS and now >= s.toxic_until:
                        s.toxic_until = now + TOXIC_SEC
                        s.stop_times.clear()
                        self.log.event(now, self.case_tick, "regime", s.t, note=
                                       f"{TOXIC_STOPS} stop-outs in {TOXIC_WINDOW:.0f}s -> toxic flow: half size,"
                                       f" no stepping inside for {TOXIC_SEC:.0f}s", echo=True)
                    if self._inflight_agg(s, side) == 0:
                        self.log.event(now, self.case_tick, "stop", s.t, side, min(abs(s.pos), AGG_CHUNK), px,
                                       s.pos, f"loss={loss_ticks:.1f}t stop={stop:.1f}t trend_against={against_trend}",
                                       echo=True)
                    return passive, aggressive

        # ---------- market making quotes
        bb, ba = s.bid, s.ask
        fair = s.fair or s.mid
        # mean-reversion target: in a range-bound name, WANT to be long near the bottom of the
        # Bollinger band and short near the top; quotes skew toward that target instead of 0
        range_ok = (s.regime != "TREND" and abs(s.t_slow) < SLOW_T_LEAN and s.vstate != "stressed"
                    and len(s.bbq) >= 40 and now >= s.no_buy_until and now >= s.no_sell_until)
        mr_tgt = int(-MR_MAX_INV * max(-1.0, min(1.0, s.bb_z / MR_Z_FULL))) if range_ok else 0
        s.mr_tgt = mr_tgt
        inv = (s.pos - mr_tgt) / MM_INV_CAP
        r = min(1.0, abs(inv))
        toxic = now < s.toxic_until
        stressed = toxic or s.vstate == "stressed"
        calm = s.vstate == "calm" and not toxic
        if bb <= 0 or ba <= 0 or s.spread_ticks >= WIDE_SPREAD_TICKS:
            # thin / one-sided book: quote around the robust fair value
            edge = max(WIDE_EDGE_TICKS, 2 * s.vol) * tick
            bid = fair - edge
            ask = fair + edge
            if bb > 0:
                bid = max(bid, bb + tick)
            if ba > 0:
                ask = min(ask, ba - tick)
            size = WIDE_SIZE
        else:
            if s.spread_ticks >= IMPROVE_MIN_SPREAD and not stressed:
                bid, ask = bb + tick, ba - tick
                if ask - bid < tick:          # 2-tick spread: step inside on the reducing side only
                    if inv > 0:
                        bid = bb
                    else:
                        ask = ba
            else:
                bid, ask = bb, ba
            if stressed:                      # bands blowing out: defensive, one tick behind
                bid -= tick
                ask += tick
            healthy_wide = WIDE_OK_MIN <= s.spread_ticks <= WIDE_OK_MAX and s.regime != "TREND"
            size = QUOTE_SIZE_CALM if (calm or healthy_wide or self.widest == s.t) else QUOTE_SIZE
        if stressed:
            size = size // 2
        if s.size_mult < 1.0 and now - s.size_t > 60.0:
            s.size_mult, s.size_t = min(1.0, s.size_mult * 1.25), now
        size = int(size * s.size_mult)
        # session governor: deep in the red -> smaller market making (trend engine unaffected)
        if self.pnl < -50000:
            size = size // 4
        elif self.pnl < -25000:
            size = size // 2
        # inventory fading: adding side fades deeper, reducing side priced to trade
        fade = int(round(FADE_MAX_TICKS * r ** 1.5))
        if inv > 0:
            bid -= fade * tick
            if r > 0.4:
                ask -= tick
        elif inv < 0:
            ask += fade * tick
            if r > 0.4:
                bid += tick
        # fast market: our quote lands ~LATENCY_SEC late; step the side being run over
        # out of the way by the distance price travels meanwhile (or pull it, below)
        run = s.vel * self.lat_est
        if run > 0.5:
            ask += math.ceil(run) * tick
        elif run < -0.5:
            bid -= math.ceil(-run) * tick
        # never cross / never lock
        if ba > 0:
            bid = min(bid, ba - tick)
        if bb > 0:
            ask = max(ask, bb + tick)
        if ask - bid < tick:
            return passive, aggressive
        # exponential size throttle + explicit halt on the side that adds inventory
        add_q = 0.0 if r >= HALT_FRAC else size * math.exp(-EXP_K * r)
        red_q = min(MAX_ORDER, size * (1.0 + r))
        if inv > 0:
            bid_q, ask_q = add_q, red_q
        elif inv < 0:
            bid_q, ask_q = red_q, add_q
        else:
            bid_q = ask_q = size
        # trend lean: in a building trend, don't offer against it
        lean = s.gap / thr if thr else 0.0
        if (lean > 0.5 or s.t_slow >= SLOW_T_LEAN) and 0 <= s.pos < LEAN_MAX_INV:
            ask_q = 0
        if (lean < -0.5 or s.t_slow <= -SLOW_T_LEAN) and -LEAN_MAX_INV < s.pos <= 0:
            bid_q = 0
        # slow grind against our inventory: stop adding to the losing side at all
        if s.t_slow <= -SLOW_T_LEAN and s.pos > 0:
            bid_q = 0
        if s.t_slow >= SLOW_T_LEAN and s.pos < 0:
            ask_q = 0
        if run >= SPEED_PULL_TICKS:
            ask_q = min(ask_q, max(0, s.pos))       # price racing up: don't sell into it
        if run <= -SPEED_PULL_TICKS:
            bid_q = min(bid_q, max(0, -s.pos))
        if unwinding or mm_paused or self.over > 0:
            bid_q = min(bid_q, max(0, -s.pos))
            ask_q = min(ask_q, max(0, s.pos))
        if now < s.no_buy_until:
            bid_q = min(bid_q, max(0, -s.pos))
        if now < s.no_sell_until:
            ask_q = min(ask_q, max(0, s.pos))
        if bid_q >= 100:
            passive.append(("BUY", s.rnd(bid), int(bid_q) // 100 * 100))
        if ask_q >= 100:
            passive.append(("SELL", s.rnd(ask), int(ask_q) // 100 * 100))
        # sweep catcher: far resting levels on dislocation-prone names
        if (now - s.disloc_t < LADDER_MEMORY and not unwinding and not mm_paused
                and s.fair and len(s.bbq) >= 20):
            for pct, q in zip(LADDER_PCT, LADDER_QTY):
                if s.pos < MM_INV_CAP // 2:
                    pb = s.rnd(s.fair * (1 - pct))
                    if pb < (bid if bid_q >= 100 else bb) - tick and (ba <= 0 or pb < ba - tick):
                        s.ladder.append(("BUY", pb, q))
                if s.pos > -MM_INV_CAP // 2:
                    pa = s.rnd(s.fair * (1 + pct))
                    if pa > (ask if ask_q >= 100 else ba) + tick and pa > bb + tick:
                        s.ladder.append(("SELL", pa, q))
        return passive, aggressive

    def learn_ride(self, s, now):
        """Self-tuning: losing trend rides make that name's trend bar stricter (choppy
        market); winning rides relax it again. Several losers in a row switch the trend
        engine off on that name for a while."""
        ride = s.dir_side * (s.mid - s.dir_entry_mid) / s.tick
        s.pnl_hist.clear()          # trend P&L must not trigger the MM bleed check
        if ride <= 0:
            s.rides[1] += 1
            s.lose_streak += 1
            s.dir_mult = min(DIR_MULT_MAX, s.dir_mult * 1.4)
            note = f"losing ride {ride:+.0f}t -> entry bar x{s.dir_mult:.2f}"
            if s.lose_streak >= CHOP_LOCKOUT_RIDES:
                s.dir_off_until = now + CHOP_LOCKOUT_SEC
                s.lose_streak = 0
                note += f"; {CHOP_LOCKOUT_RIDES} losers in a row -> CHOPPY, trend engine off {CHOP_LOCKOUT_SEC:.0f}s"
        else:
            s.rides[0] += 1
            s.lose_streak = 0
            s.dir_mult = max(1.0, s.dir_mult * 0.8)
            note = f"winning ride {ride:+.0f}t -> entry bar x{s.dir_mult:.2f}"
        self.log.event(now, self.case_tick, "regime", s.t, note=note, echo=True)

    def dir_cap(self, s):
        """Directional size for one name: share of cap left after other names' positions."""
        others = sum(abs(x.pos) for x in self.secs.values() if x is not s)
        room = int(DIR_FRACTION * self.cap_gross) - others
        return max(0, min(room, int(DIR_FRACTION * self.cap_net)))

    # --------------------------------------------------------------- execution
    def execute(self, plans):
        now = self.now()
        cancels, places = [], []
        pending = {}
        for t, (passive, aggressive) in plans.items():
            s = self.secs[t]
            want = {side: (px, q) for side, px, q in passive}
            lad = list(s.ladder)
            agg_sides = {side for side, _, _ in aggressive}
            t_wall = time.time()
            for o in s.orders:
                side = o["action"]
                if o.get("t_cancel"):
                    if t_wall - o["t_cancel"] > CANCEL_RESEND and o["state"] == "open":
                        cancels.append((s, o))      # cancel didn't land: re-send
                    continue
                if o.get("kind") == "agg":
                    if t_wall - o["t_sent"] > AGG_TTL and o["state"] == "open":
                        cancels.append((s, o))      # leftover of a crossing order
                    continue
                if o.get("kind") == "ladder":
                    hit = None
                    for i, (lside, lpx, lq) in enumerate(lad):
                        if lside == side and abs(float(o["price"]) - lpx) <= LADDER_TOL * lpx:
                            hit = i
                            break
                    if hit is not None:
                        lad.pop(hit)                # level already resting
                    elif o["state"] == "open":
                        cancels.append((s, o))
                    continue
                rem = int(o["quantity"]) - int(o.get("quantity_filled") or 0)
                w = want.get(side)
                keep = (w is not None and side not in agg_sides
                        and abs(float(o["price"]) - w[0]) < s.tick / 2
                        and rem >= KEEP_FRAC * w[1])
                if keep:
                    want[side] = None           # satisfied (queue priority kept)
                elif o["state"] == "open":
                    cancels.append((s, o))
                else:
                    # sent but not listed yet: can't cancel by id reliably; it is still
                    # counted in exposure, so just don't add a duplicate on that side
                    if w is not None and abs(float(o["price"]) - w[0]) < s.tick / 2:
                        want[side] = None
            for side, v in want.items():
                if v is not None:
                    places.append((s, side, v[0], v[1], "quote"))
            for side, px, q in lad:
                places.append((s, side, px, q, "ladder"))
            for side, px, q in aggressive:
                # decide() sized this from the reported position, which lags RIT by ~0.3 s:
                # subtract crossing orders sent in the last AGG_INTERVAL on the same side
                q = int(q) - self._inflight_agg(s, side)
                if q >= 100 or (q > 0 and q >= abs(s.pos) - self._inflight_agg(s, side) and s.pos != 0):
                    places.append((s, side, px, q, "agg"))

        # cancels first (frees exposure), all in parallel
        if cancels:
            futs = [self.pool.submit(self.api.cancel, o["order_id"]) for _, o in cancels]
            for (s, o), f in zip(cancels, futs):
                f.result()
                o["t_cancel"] = time.time()
                # Keep counting a just-cancelled order in worst-case exposure until the next
                # refresh: it may have filled a moment before the cancel landed. This closes
                # the cancel/replace race that could otherwise double-fill past the cap.
                self.cancels += 1
        # aggressive first (they matter most), then quotes
        # aggressive first, then the widest-spread name's quotes get first call on limit room
        places.sort(key=lambda x: 0 if x[4] == "agg" else 3 if x[4] == "ladder"
                    else (1 if x[0].t == self.widest else 2))
        jobs = []
        for s, side, px, q, kind in places:
            reducing = kind == "agg" and ((side == "BUY" and s.pos < 0) or (side == "SELL" and s.pos > 0))
            if reducing:
                # cutting a real position lowers exposure: checked against positions plus
                # in-flight crosses only (not the pessimistic pile of quotes), never more than held
                q = min(int(q), abs(s.pos))
                net_now = sum(x.pos for x in self.secs.values())
                infl = sum(self._inflight_agg(x, side) for x in self.secs.values())
                if side == "BUY" and net_now + infl + q > self.cap_net:
                    q = max(0, self.cap_net - net_now - infl)
                if side == "SELL" and net_now - infl - q < -self.cap_net:
                    q = max(0, net_now - infl + self.cap_net)
            else:
                q = self.fit_qty(s.t, side, q, pending)
            if q < 1:
                continue
            pending[(s.t, side)] = pending.get((s.t, side), 0) + q
            if kind == "agg":
                s.agg_block_until = time.time() + AGG_INTERVAL
                s.agg_pos_ref = s.pos
            jobs.append((s, side, px, q, kind, time.time(), self.pool.submit(self.api.place, s.t, side, q, px)))
        for s, side, px, q, kind, t_sent, f in jobs:
            r = f.result()
            self.places += 1
            ok = isinstance(r, dict) and not r.get("_error")
            if ok and r.get("order_id") is not None:
                self.live[r["order_id"]] = {
                    "order_id": r["order_id"], "ticker": s.t, "action": side, "price": px,
                    "quantity": q, "quantity_filled": int(r.get("quantity_filled") or 0),
                    "t_sent": t_sent, "kind": kind, "state": "new", "seen": False}
            elif not ok:
                s.agg_block_until = 0.0
            self.log.event(now, self.case_tick, "place", s.t, side, q, px, s.pos,
                           kind if ok else f"{kind} REJECTED {r}", echo=(kind == "agg" or not ok))

    # --------------------------------------------------------------- main loop
    def heartbeat(self, now, sl):
        if now - self.last_beat < HEARTBEAT_SEC:
            return
        dt = now - self.last_beat if self.last_beat else 1.0
        self.last_beat = now
        gross = sum(abs(s.pos) for s in self.secs.values())
        net = sum(s.pos for s in self.secs.values())
        parts = []
        for s in self.secs.values():
            tags = (s.regime + "/" + s.vstate + (" trendOFF" if now < s.dir_off_until else "")
                    + (" toxic" if now < s.toxic_until else "") + (" mmPAUSE" if now < s.mm_off_until else "")
                    + (" LADDER" if now - s.disloc_t < LADDER_MEMORY else ""))
            parts.append(f"{s.t} {s.pos:+6d} {s.bid:.2f}/{s.ask:.2f} {s.mode}{'' if s.mode=='mm' else '!'}"
                         f" [{tags} er{s.er:.2f} t{s.t_slow:+.1f} z{s.bb_z:+.1f} tgt{s.mr_tgt:+d}]")
        spt = f"{self.sec_per_tick:.2f}s/tk" if self.sec_per_tick else "spt?"
        print(f"[{now:7.1f}s] tick {self.case_tick}/{self.tpp} ~{sl:5.0f}s left {spt} | "
              f"P&L ${self.pnl:+,.0f} (peak {self.peak:+,.0f}) | gross {gross:,} net {net:+,} | "
              + " | ".join(parts)
              + f" | {self.loops/dt:.0f} loops/s lat {self.lat_est*1000:.0f}ms 429s={self.api.n429}", flush=True)
        self.loops = 0

    def write_tick(self, now, sl):
        gross = sum(abs(s.pos) for s in self.secs.values())
        net = sum(s.pos for s in self.secs.values())
        row = [f"{now:.3f}", self.case_tick, f"{sl:.1f}", f"{self.pnl:.2f}",
               f"{self.nlv or 0:.2f}", gross, net]
        for t in self.tickers:
            s = self.secs[t]
            row += [s.bid, s.ask, f"{(s.fair or 0):.4f}", f"{s.gap:.2f}", f"{s.vol:.2f}", f"{s.er:.2f}", s.regime,
                    f"{s.bb_z:.2f}", s.vstate, f"{s.t_slow:.2f}",
                    s.pos, s.mode, f"{s.realized + s.unrealized:.2f}"]
        self.log.tick_row(row)

    def run(self):
        self.setup()
        waiting_printed = 0.0
        was_active = False
        while self.running:
            t_loop = time.time()
            try:
                self.refresh()
            except Exception as e:  # never die on a bad read
                print(f"[warn] refresh error: {e!r}", flush=True)
                time.sleep(0.2)
                continue
            now = self.now()
            if self.status != "ACTIVE":
                if was_active:
                    print(f"[case] status {self.status} - case over. Final P&L ${self.pnl:+,.2f}", flush=True)
                    was_active = False
                if now - waiting_printed > 3:
                    print(f"[wait] case status={self.status} tick={self.case_tick} - waiting for ACTIVE...", flush=True)
                    waiting_printed = now
                time.sleep(0.2)
                continue
            if not was_active:
                print(f"[case] ACTIVE at tick {self.case_tick} - trading.", flush=True)
                was_active = True
                self.unwind_announced = self.hard_announced = False
            sl = self.sec_left()
            u_start, u_hard = self.unwind_windows()
            if sl <= u_start and not self.unwind_announced and self.sec_per_tick:
                print(f"[unwind] ~{sl:.0f}s left: no new risk, working out of positions", flush=True)
                self.unwind_announced = True
            if sl <= u_hard and not self.hard_announced and self.sec_per_tick:
                print(f"[unwind] ~{sl:.0f}s left: crossing to finish flat", flush=True)
                self.hard_announced = True
            if not self.sec_per_tick:
                sl = 1e9            # don't unwind before we know the clock
            # account breaker
            if self.pnl < self.peak - BREAKER_DD and now >= self.paused_until:
                self.paused_until = now + BREAKER_PAUSE
                self.log.event(now, self.case_tick, "breaker", note=f"pnl {self.pnl:,.0f} peak {self.peak:,.0f}",
                               echo=True)
                self.peak = self.pnl
            # rank by healthy spread: widest gets the full size and first call on room
            cands = [x for x in self.secs.values()
                     if WIDE_OK_MIN <= x.spread_ticks <= WIDE_OK_MAX and x.regime != "TREND"]
            self.widest = max(cands, key=lambda x: x.spread_ticks).t if cands else None
            # safety net on ACTUAL positions (fills can land between our checks)
            gross = sum(abs(x.pos) for x in self.secs.values())
            net = abs(sum(x.pos for x in self.secs.values()))
            self.over = max(gross - self.cap_gross, net - self.cap_net, 0)
            hard_line = int(SAFETY_FRACTION * min(self.gross_limit, self.net_limit))
            plans = {}
            for t in self.tickers:
                try:
                    plans[t] = self.decide(self.secs[t], now, sl)
                except Exception as e:
                    print(f"[warn] decide {t}: {e!r}", flush=True)
                    plans[t] = ([], [])
            if max(gross, net) > hard_line:
                big = max(self.secs.values(), key=lambda x: abs(x.pos))
                side = "SELL" if big.pos > 0 else "BUY"
                px = self.agg_price(big, side) or (big.bid - 3 * big.tick if side == "SELL" else big.ask + 3 * big.tick)
                cut = min(AGG_CHUNK, max(gross, net) - self.cap_gross + 500, abs(big.pos))
                if cut > 0 and px > 0:
                    pas, agg = plans.get(big.t, ([], []))
                    plans[big.t] = ([p for p in pas if p[0] == side], agg + [(side, px, cut)])
                    self.log.event(now, self.case_tick, "safety", big.t, side, cut, px, big.pos,
                                   f"actual gross {gross:,} net {net:,} above {hard_line:,} -> cutting", echo=True)
            try:
                self.execute(plans)
            except Exception as e:
                print(f"[warn] execute error: {e!r}", flush=True)
            self.write_tick(now, sl)
            self.loops += 1
            self.heartbeat(now, sl)
            el = time.time() - t_loop
            if el < LOOP_MIN_DT:
                time.sleep(LOOP_MIN_DT - el)

    def shutdown(self, flatten=True):
        print("\n[stop] cancelling all orders" + (" and flattening" if flatten else ""), flush=True)
        try:
            self.api.cancel_all()
            if flatten:
                self.flattening = True
                t_end = time.time() + 6
                while time.time() < t_end:
                    self.refresh()
                    if all(s.pos == 0 for s in self.secs.values()):
                        break
                    if self.status != "ACTIVE":
                        break
                    self.execute({t: self.decide(self.secs[t], self.now(), 0) for t in self.tickers})
                    time.sleep(0.1)
                self.api.cancel_all()
                self.refresh()
        except Exception as e:
            print(f"[stop] {e!r}")
        for t, s in self.secs.items():
            print(f"[stop] {t}: trend rides won {s.rides[0]} lost {s.rides[1]}, final entry bar x{s.dir_mult:.2f}")
        pos = {t: s.pos for t, s in self.secs.items()}
        print(f"[stop] final positions {pos}  P&L ${self.pnl:+,.2f}  "
              f"orders placed {self.places:,}  cancelled {self.cancels:,}", flush=True)
        if self.log:
            self.log.event(self.now(), self.case_tick, "end", note=f"pnl {self.pnl:.2f} pos {pos}")
            self.log.close()
            print(f"[log] saved {self.log.tick_path} and {self.log.ev_path}", flush=True)


# =============================================================================
# MOCK EXCHANGE  (offline test of the code paths; NOT a P&L forecast)
# =============================================================================
class MockRIT:
    """Tiny in-process imitation of the RIT REST API. Scenarios: chop, trend, spike."""

    def __init__(self, scenario="chop", seconds=60, seed=1):
        self.rng = random.Random(int(os.environ.get("MOCK_SEED", seed)))
        self.scn, self.T = scenario, seconds
        self.t0 = time.time()
        self.px = {"CNR": 176.60, "RY": 91.90, "AC": 29.80}
        self.p0 = dict(self.px)
        self.pos = {t: 0 for t in self.px}
        self.vwap = {t: 0.0 for t in self.px}
        self.cash = 0.0
        self.orders = {}
        self.oid = 0
        self.lock = threading.Lock()
        self.n429 = 0
        self.last_step = 0.0
        self.max_gross = 0
        self.max_net = 0
        self.fees = {"CNR": (0.0027, 0.0023), "RY": (-0.0014, -0.0020), "AC": (0.0015, 0.0011)}
        # RIT-like asynchrony: orders/cancels take effect LAT later, positions are reported POS_LAG late
        self.LAT = float(os.environ.get("MOCK_LAT", "0.25")); self.POS_LAG = float(os.environ.get("MOCK_POSLAG", "0.30"))
        self.q_new, self.q_cancel = [], []
        self.pos_hist = collections.deque()
        self.sweep = {}                     # ticker -> (until, side, depth)

    def el(self): return time.time() - self.t0

    def _process_queues(self, now):
        for item in [x for x in self.q_new if x[0] <= now]:
            self.q_new.remove(item)
            o = item[1]
            t, price, qty = o["ticker"], o["price"], o["quantity"]
            bb, ba = self._touch(t)
            if o["action"] == "BUY" and price >= ba:
                self._fill(o, qty, ba, passive=False)
            elif o["action"] == "SELL" and price <= bb:
                self._fill(o, qty, bb, passive=False)
            else:
                self.orders[o["order_id"]] = o
        for item in [x for x in self.q_cancel if x[0] <= now]:
            self.q_cancel.remove(item)
            if item[1] is None:
                self.orders.clear()
            else:
                self.orders.pop(item[1], None)

    def _step(self):
        now = self.el()
        dt = now - self.last_step
        if dt < 0.05:
            return
        self.last_step = now
        self._process_queues(now)
        self.pos_hist.append((now, dict(self.pos), dict(self.vwap)))
        while len(self.pos_hist) > 2 and self.pos_hist[1][0] <= now - self.POS_LAG:
            self.pos_hist.popleft()
        for t in self.px:
            noise = self.rng.gauss(0, 0.01 * math.sqrt(dt / 0.5))
            drift = 0.0
            if self.scn == "trend" and t == "AC" and 0.25 * self.T < now < 0.6 * self.T:
                drift = 0.25 * dt            # $0.25 / s like the 20:09 AC run
            if self.scn == "trend" and t == "CNR" and 0.5 * self.T < now < 0.8 * self.T:
                drift = -0.08 * dt
            if self.scn == "reversal" and t == "AC":
                if 0.25 * self.T < now < 0.45 * self.T:
                    drift = 0.25 * dt
                elif 0.45 * self.T < now < 0.65 * self.T:
                    drift = -0.35 * dt
            if self.scn in ("meanrev", "arch", "crash", "flood", "sweep"):
                drift = -0.08 * (self.px[t] - self.p0[t]) * dt          # pulled back to the mean
            if self.scn == "arch" and t in ("AC", "CNR") and 0.15 * self.T < now < 0.85 * self.T:
                ph = (now - 0.15 * self.T) / (0.7 * self.T)              # inverted U over 70% of run
                self.p0[t] = (29.80 if t == "AC" else 176.60) + (3.0 if t == "AC" else 4.0) * math.sin(math.pi * ph)
            if self.scn == "crash" and t == "RY" and 0.3 * self.T < now < 0.5 * self.T:
                self.p0[t] -= 0.15 * dt                                  # multi-minute sell-off
            if self.scn == "grind" and t == "CNR":
                self.p0[t] = 176.60 - 1.3 * min(1.0, now / self.T)       # slow $1.30 slide (10/01 sim)
                drift = -0.08 * (self.px[t] - self.p0[t]) * dt
            if self.scn == "whipsaw" and t in ("AC", "CNR"):
                drift = (0.15 if int(now / 4) % 2 == 0 else -0.15) * dt   # 4s up, 4s down, forever
            if self.scn == "reversal" and t == "RY" and int(now) % 6 == 0:
                drift = self.rng.choice([-1, 1]) * 0.05 * dt     # fake-out jolts
            self.px[t] = max(1.0, self.px[t] + drift + noise)
            if self.scn == "sweep" and t == "AC":
                drift = -0.08 * (self.px[t] - self.p0[t]) * dt
                if self.rng.random() < 0.25 * dt and now > self.sweep.get(t, (0,))[0] + 1.0:
                    side = self.rng.choice(["BUY", "SELL"])     # anonymous market order sweeping a thin book
                    depth = self.rng.uniform(0.03, 0.25)
                    self.sweep[t] = (now + 1.0, side, depth)
                    left = self.rng.choice([3000, 6000, 9000])
                    lim = self.px[t] * (1 + depth) if side == "BUY" else self.px[t] * (1 - depth)
                    mine = [o for o in self.orders.values() if o["ticker"] == t
                            and o["action"] == ("SELL" if side == "BUY" else "BUY")
                            and (o["price"] <= lim if side == "BUY" else o["price"] >= lim)]
                    mine.sort(key=lambda o: o["price"] if side == "BUY" else -o["price"])
                    for o in mine:
                        if left <= 0:
                            break
                        q = min(left, o["quantity"] - o["quantity_filled"])
                        self._fill(o, q, o["price"], passive=True)
                        left -= q
            # anonymous takers hit resting orders at the touch
            for o in list(self.orders.values()):
                if o["ticker"] != t:
                    continue
                bb, ba = self._touch(t)
                hit = False
                if o["action"] == "BUY" and o["price"] >= bb - 1e-9 and self.rng.random() < 0.05 * dt / 0.05:
                    hit = True
                if o["action"] == "SELL" and o["price"] <= ba + 1e-9 and self.rng.random() < 0.05 * dt / 0.05:
                    hit = True
                # adverse fills when price moves through our order
                if o["action"] == "BUY" and self.px[t] < o["price"] - 0.01:
                    hit = True
                if o["action"] == "SELL" and self.px[t] > o["price"] + 0.01:
                    hit = True
                if self.scn == "flood" and self.rng.random() < 0.5:
                    hit = True                     # stress test: orders filled hard and fast
                if hit:
                    lot = 5000 if self.scn == "flood" else self.rng.choice([500, 1000, 2500])
                    q = min(o["quantity"] - o["quantity_filled"], lot)
                    self._fill(o, q, o["price"], passive=True)
        g = sum(abs(v) for v in self.pos.values())
        self.max_gross = max(self.max_gross, g)
        self.max_net = max(self.max_net, abs(sum(self.pos.values())))

    def _touch(self, t):
        p = self.px[t]
        half = 0.01 if t != "AC" else 0.02
        sw = self.sweep.get(t)
        if sw and self.el() < sw[0]:
            if sw[1] == "BUY":
                return round(p - half, 2), round(p * (1 + sw[2]), 2)   # asks swept away
            return round(p * (1 - sw[2]), 2), round(p + half, 2)
        if self.scn == "spike" and t == "AC" and int(self.el()) % 10 in (3, 4):
            half = 3.0                          # thin book: spread ~$6
        return round(p - half, 2), round(p + half, 2)

    def _fill(self, o, q, px, passive):
        sgn = 1 if o["action"] == "BUY" else -1
        t = o["ticker"]
        p0 = self.pos[t]
        p1 = p0 + sgn * q
        if p0 == 0 or (p0 > 0) != (p1 > 0) and p1 != 0:
            self.vwap[t] = px
        elif abs(p1) > abs(p0):
            self.vwap[t] = (self.vwap[t] * abs(p0) + px * q) / abs(p1)
        self.pos[t] = p1
        tf, rb = self.fees[o["ticker"]]
        self.cash += -sgn * q * px + (rb * q if passive else -tf * q)
        o["quantity_filled"] += q
        if o["quantity_filled"] >= o["quantity"]:
            self.orders.pop(o["order_id"], None)

    # API surface
    def case(self):
        with self.lock:
            self._step()
            tick = int(self.el() * 300 / self.T)
            return {"name": f"MOCK {self.scn}", "status": "ACTIVE" if tick < 300 else "STOPPED",
                    "tick": min(tick, 300), "ticks_per_period": 300, "period": 1,
                    "is_enforce_trading_limits": False}

    def trader(self):
        with self.lock:
            nlv = 1e6 + self.cash + sum(self.pos[t] * self.px[t] for t in self.px)
            return {"trader_id": "me", "nlv": nlv}

    def limits(self):
        return [{"name": "limit", "gross_limit": 25000, "net_limit": 25000, "gross_fine": 1, "net_fine": 1}]

    def securities(self):
        with self.lock:
            self._step()
            out = []
            _, lp, lv = self.pos_hist[0] if self.pos_hist else (0, self.pos, self.vwap)
            for t in self.px:
                bb, ba = self._touch(t)
                out.append({"ticker": t, "position": lp[t], "vwap": lv[t], "last": self.px[t],
                            "bid": bb, "ask": ba, "realized": 0,
                            "unrealized": lp[t] * (self.px[t] - lv[t]), "quoted_decimals": 2,
                            "trading_fee": self.fees[t][0], "limit_order_rebate": self.fees[t][1]})
            return out

    def book(self, t):
        with self.lock:
            bb, ba = self._touch(t)
            bids = [{"price": bb, "quantity": 5000, "quantity_filled": 0, "trader_id": "anon"}]
            asks = [{"price": ba, "quantity": 5000, "quantity_filled": 0, "trader_id": "anon"}]
            for o in self.orders.values():
                if o["ticker"] == t:
                    lv = {"price": o["price"], "quantity": o["quantity"], "quantity_filled": o["quantity_filled"],
                          "trader_id": "me", "order_id": o["order_id"]}
                    (bids if o["action"] == "BUY" else asks).append(lv)
            bids.sort(key=lambda x: -x["price"]); asks.sort(key=lambda x: x["price"])
            return {"bids": bids, "asks": asks}

    def open_orders(self):
        with self.lock:
            return [dict(o) for o in self.orders.values()]

    def place(self, t, action, qty, price):
        with self.lock:
            self._step()
            self.oid += 1
            o = {"order_id": self.oid, "ticker": t, "type": "LIMIT", "action": action, "quantity": qty,
                 "quantity_filled": 0, "price": price}
            self.q_new.append((self.el() + self.LAT, o))
            return {"order_id": self.oid, "quantity_filled": 0, "status": "OPEN"}

    def cancel(self, oid):
        with self.lock:
            self.q_cancel.append((self.el() + self.LAT, oid))
            return {"success": True}

    def cancel_all(self):
        with self.lock:
            self.q_cancel.append((self.el() + self.LAT, None))
            return {"success": True}


# =============================================================================
# MAIN
# =============================================================================
def _env_overrides():
    """Testing hook: CFG_NAME=value overrides a config constant (not needed live)."""
    for k, v in os.environ.items():
        if k.startswith("CFG_") and k[4:] in globals():
            cur = globals()[k[4:]]
            globals()[k[4:]] = type(cur)(float(v)) if isinstance(cur, (int, float)) and not isinstance(cur, bool) else v


def main():
    global DIR_ENABLED, QUOTE_SIZE
    _env_overrides()
    ap = argparse.ArgumentParser(description="RIT ALGO 2e v3 bot")
    ap.add_argument("pos_key", nargs="?", default=None, help="API key (positional form)")
    ap.add_argument("pos_port", nargs="?", type=int, default=None, help="port (positional form)")
    ap.add_argument("pos_minutes", nargs="?", type=float, default=None,
                    help="how many minutes the whole case (e.g. 300 ticks) lasts, e.g. 10 or 20")
    ap.add_argument("--key", "--api-key", dest="key", default=os.environ.get("RIT_API_KEY", ""),
                    help="RIT API key (e.g. abcde)")
    ap.add_argument("--port", type=int, default=9999, help="RIT API port (e.g. 15000)")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--minutes", type=float, default=None, help="case length in wall minutes (optional)")
    ap.add_argument("--no-dir", action="store_true", help="disable the trend/directional engine")
    ap.add_argument("--size", type=int, default=None, help=f"quote size per side (default {QUOTE_SIZE})")
    ap.add_argument("--no-flatten-on-exit", action="store_true")
    ap.add_argument("--mock", choices=["chop", "trend", "spike", "reversal", "whipsaw", "meanrev", "arch", "crash", "flood", "grind", "sweep"], help="offline test against a fake exchange")
    ap.add_argument("--seconds", type=float, default=60, help="mock run length")
    args = ap.parse_args()
    if args.pos_key:
        args.key = args.pos_key
    if args.pos_port:
        args.port = args.pos_port
    if args.pos_minutes:
        args.minutes = args.pos_minutes
    if args.no_dir:
        DIR_ENABLED = False
    if args.size:
        QUOTE_SIZE = max(100, min(MAX_ORDER, args.size))

    if args.mock:
        api = MockRIT(args.mock, args.seconds)
    else:
        if not args.key:
            sys.exit("Usage:  python algo2e_v3.py abcde 15000 20    (key, port, case minutes)")
        os.environ["ALGO_TAG"] = f"port{args.port}_"       # log files name the port they traded
        api = RIT(args.key, f"http://{args.host}:{args.port}/v1")
        print(f"[api] http://{args.host}:{args.port}/v1")

    bot = Bot(api, minutes=args.minutes if not args.mock else (args.minutes or args.seconds / 60.0))

    def on_sigint(sig, frm):
        bot.running = False
    signal.signal(signal.SIGINT, on_sigint)

    try:
        if args.mock:
            end = time.time() + args.seconds + 3
            th = threading.Thread(target=bot.run, daemon=True)
            th.start()
            while th.is_alive() and time.time() < end and bot.running:
                time.sleep(0.2)
            bot.running = False
            th.join(timeout=3)
        else:
            bot.run()
    finally:
        bot.shutdown(flatten=not args.no_flatten_on_exit)
        if args.mock:
            print(f"[mock] true P&L ${api.cash + sum(api.pos[t]*api.px[t] for t in api.px):+,.0f}  "
                  f"max gross {api.max_gross:,}  max net {api.max_net:,}  final pos {api.pos}")


if __name__ == "__main__":
    main()
