"""Builds analysis_6M/RIT_ALGO2e_speaking_script.pdf. Run from repo root."""
import os, matplotlib
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

FD = os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data/fonts/ttf")
pdfmetrics.registerFont(TTFont("DV", f"{FD}/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-B", f"{FD}/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DV-I", f"{FD}/DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")

INK, MUTED, ACC = colors.HexColor("#1B2430"), colors.HexColor("#5B6572"), colors.HexColor("#1F5FAE")
H1 = ParagraphStyle("H1", fontName="DV-B", fontSize=20, leading=25, textColor=INK, spaceAfter=4)
SUB = ParagraphStyle("SUB", fontName="DV", fontSize=10, leading=14, textColor=MUTED, spaceAfter=10)
H2 = ParagraphStyle("H2", fontName="DV-B", fontSize=13.5, leading=17, textColor=ACC, spaceBefore=14, spaceAfter=2)
TIME = ParagraphStyle("TIME", fontName="DV-I", fontSize=9, leading=12, textColor=MUTED, spaceAfter=5)
BODY = ParagraphStyle("BODY", fontName="DV", fontSize=10.5, leading=15.5, textColor=INK, spaceAfter=7)
NOTE = ParagraphStyle("NOTE", fontName="DV", fontSize=9.5, leading=13.5, textColor=INK, backColor=colors.HexColor("#F3EFE4"),
                      borderPadding=(6, 8, 6, 8), spaceBefore=12, spaceAfter=10)
CELL = ParagraphStyle("CELL", fontName="DV", fontSize=9.5, leading=13, textColor=INK)
CELLB = ParagraphStyle("CELLB", parent=CELL, fontName="DV-B")
BUL = ParagraphStyle("BUL", parent=BODY, leftIndent=14, bulletIndent=2, spaceAfter=3, bulletFontName="DV")

def P(t, s=BODY): return Paragraph(t, s)

story = [P("RIT ALGO2e: full speaking script", H1),
         P("Main strategy: algo2e_fin.py  |  10 slides, about 12 minutes  |  Real P&amp;L: $6,288,771", SUB),
         P("<b>How to use this:</b> each section matches one slide. Speak it in your own words; the numbers are the ones to keep exact. "
           "Bold phrases are the points that answer your professor's likely questions.", BODY)]

# topic map
rows = [["Question", "Slide"],
        ["Strategy as a whole; where we expected the money to come from", "2"],
        ["Handling multiple securities, fees and rebates", "3"],
        ["Trend (directional) strategy and how it worked", "4, 5"],
        ["Sizing", "5, 6"],
        ["Limits and unwinding", "6"],
        ["What happened in the simulation", "7, 8"],
        ["Why market making did not make money", "5, 8"],
        ["Mean reversion in this market, and its P&amp;L effect", "2, 10"]]
t = Table([[Paragraph(a, CELLB if i == 0 else CELL), Paragraph(b, CELLB if i == 0 else CELL)] for i, (a, b) in enumerate(rows)],
          colWidths=[5.6 * inch, 1.0 * inch])
t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ECE8DD")), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#D5D1C5")),
                       ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
story += [Spacer(1, 4), t,
          P("<b>Check before you present:</b> the code reads each stock's fees from the server but does not change its quotes because of them, so do not say "
            "the bot adjusts quotes for rebates. The without-spike figure is an estimate. The mean-reversion tilt was off in the run.", NOTE)]

slides = [
 ("Slide 1: Cover", "30 seconds", [
  "Good [morning]. We are presenting our algorithm for RIT ALGO2e. The three numbers up front: <b>$6.29 million</b> final P&amp;L, <b>zero limit breaches</b>, "
  "and about <b>half a million dollars</b> if you take away one event in RY. I will explain what the strategy was, where we expected the money to come from, "
  "what actually happened, and what we would change."]),
 ("Slide 2: Premise and the strategy as a whole", "1 min 30 s", [
  "The strategy has three parts. First, a <b>market maker</b>: it posts bids and offers on all three stocks and keeps the gap. Second, a <b>trend engine</b>: if a price "
  "starts moving hard in one direction, it takes a big position and rides it. Third, a <b>risk layer</b> that sits over both and keeps us under the position limit, so no fines.",
  "<b>Where we expected the money to come from.</b> Honestly, we expected most of it from market making: the bid-ask spread plus maker rebates, in a market where prices bounce "
  "around a level. That was our guess. Nobody told us in advance which path prices would follow, so we guessed mean reversion. The trend engine was our insurance in case the guess "
  "was wrong, and in case the professor added a spike or a trend.",
  "<b>Mean-reversion tilt.</b> [point at the box] We also built a directional version: hold shares when price looks stretched, long near the bottom of its range, short near the top. "
  "It only pays if price snaps back. We tested it, it lost to plain market making, and it was <b>off</b> in the run. If it had been on, our estimate is about +$5k to +$55k on $6.29M. "
  "I will come back to that.",
  "The panel on the right lists the concepts we used, like market making with inventory skewing, a Kaufman efficiency ratio, Bollinger z-scores and trailing stops. "
  "I will show each one in the slides that follow."]),
 ("Slide 3: Design rules, multiple securities, fees", "1 min 45 s", [
  "The top strip is the whole algorithm in one line, repeated up to 40 times a second: refresh data, classify the regime, decide per stock, safety net, execute, log. "
  "The six cards are the rules we settled on, each with a reason. For example, we strip our own orders from the book before pricing, otherwise the bot sees its own bid as the best "
  "price and keeps improving on it. We use limit orders only, so a thin book cannot make us pay an absurd price.",
  "<b>Handling multiple securities.</b> Each stock has its own state: its own signals, regime, mode, stops and learned entry bar. Tick size and fees are read per stock from the server. "
  "But the three share one set of limits. Every order is checked against worst-case exposure across all three names together. The trend engine's size is the share of the cap left "
  "after the other names' positions. And when limit room is tight, the stock with the healthiest wide spread gets first call, and aggressive orders go before passive ones.",
  "<b>Fees and rebates.</b> The fees are different for each stock: CNR and AC pay a rebate for resting orders, but RY is reversed, resting there costs $0.0020 a share. "
  "The bot reads them per stock. To be honest, our decision logic does not change quotes based on them: our response to rebates was to quote the biggest size when the market is calm, "
  "to harvest spread and rebates. RY's reversed fee is a weakness we would fix next time by not quoting RY at all."]),
 ("Slide 4: Regime detection", "1 min 15 s", [
  "This is how the bot decides which mode to be in. Look at RY, ticks 196 to 207. Before tick 200, the efficiency ratio is zero: the price is going nowhere, so the label is chop and the "
  "bot makes markets. At tick 200 the ratio jumps to 1.0, a straight-line move, the label becomes TREND and the volatility state turns from calm to stressed. At tick 201.6 the EMA gap, "
  "the difference between a 1-second and an 8-second average, passes 12 ticks and stays there for 0.8 seconds. That is when RY switches from market making to the trend engine and the "
  "bot starts buying.",
  "Two protections to point out. The thresholds are in units of volatility, so noise does not trigger a trade. And it takes a stronger signal to enter TREND than to stay in it, called "
  "hysteresis, so it does not flicker. One honest caveat: the label alone is noisy. CNR was labelled TREND for about 39% of its first 200 ticks even though it never trended, so the entry "
  "rules and the learned entry bar do the real protecting."]),
 ("Slide 5: The two engines and sizing", "2 min", [
  "<b>Market making sizing.</b> We quote 5,000 shares per side when the market is calm, 3,000 normally, half of that when stressed, and 2,000 in a thin book. The left chart is the "
  "inventory brake. We measure inventory as a ratio, r, of position over 9,000 shares. As r rises, the size on the side that adds inventory shrinks exponentially, the quote moves away by "
  "up to four ticks, and at r of 0.85, about 7,650 shares, that side is switched off. The side that reduces inventory gets bigger and closer to the market. It is the same idea as the "
  "inventory-skew quoting in academic market-making models.",
  "<b>Why market making did not make money.</b> The spread was one tick, one cent, on all three stocks. A one-cent margin leaves almost no room for being wrong. And the price moved in "
  "jumps larger than a cent, so the bot was stopped out again and again: 86 times on CNR. Each stop gives away the spread. Result: about minus $15,000 across the three stocks, CNR minus "
  "$16k, RY minus $4k, AC plus $5k. On RY the reversed fee, which makes resting orders cost money, is consistent with that, but we have not proven it.",
  "<b>Trend strategy.</b> [right chart] It enters when the gap exceeds the larger of 12 ticks or five times volatility, the efficiency ratio is at least 0.45, the spread is under 6 ticks, "
  "and the signal has held 0.8 seconds. The first order is 60% of the cap, then it grows with the strength of the signal, up to about 22,000 shares. It exits on a trailing stop, the larger of "
  "15 ticks or six times volatility from the best price, or when the move fades or stalls. It also learns: a losing trade raises that stock's entry bar by 1.4 times. This AC chart shows it: "
  "bought at the start of the climb, held 22,000 shares, and sold in the end-of-case unwind."]),
 ("Slide 6: Limits, sizing and unwinding", "1 min 45 s", [
  "We set out to make money without fines, and we stayed under the limits even when aggressive. The limit is 25,000 shares gross and net. Before every order the bot assumes all resting "
  "orders, all in-flight orders and the new order fill at once, and requires that to stay under <b>93%</b> of the limit, 23,250 shares. If it does not fit, the order shrinks by 40% at a "
  "time and is then dropped. Second, a safety net: if the actual position ever passes 96%, the bot cuts the biggest position immediately. Third, a circuit breaker: if P&amp;L falls $40,000 "
  "from its peak, it flattens and pauses for 8 seconds. It fired once, at tick 38, after the early CNR losses.",
  "<b>Unwinding.</b> About 20 seconds before the end, the bot stops adding risk. About 8 seconds before the end it crosses to finish flat. After a trend exit, a 'cut' step sells the remaining "
  "position with capped limit orders. This is how the AC position was closed at tick 296.",
  "The chart is the evidence: <b>peak gross 23,088 against 25,000</b>, zero moments above 24,000, and the final account value equals the sum of the three stock P&amp;Ls to the cent. So, "
  "in this run, no fines were deducted."]),
 ("Slide 7: What happened, stock by stock", "2 min", [
  "Here is the simulation, one stock at a time, with the P&amp;L with and without the spike underneath each.",
  "<b>CNR.</b> It stayed between about $159.1 and $160.8 all case, so it was mean-reverting. It lost $53,000. Three trend calls in the first 13 ticks reversed immediately, minus $37,000, "
  "and market-making stop-outs added minus $16,000. The circuit breaker fired at tick 38. Same with or without the spike.",
  "<b>RY.</b> Flat at $100 for 200 ticks. At tick 200 it started to drift up. Our engine bought 22,062 shares between $100.2 and $105.5 starting at tick 201 and held them as the price reached "
  "$118. At tick 217 the book became one-sided because of Group 12's activity: bids jumped to $346 and then $402. We sold the whole position in five orders over about four seconds. That trade made "
  "<b>$6.22 million</b>. If you value the exit at the last normal bid, $121, the same trade is about $0.45 million.",
  "<b>AC.</b> Flat near $25 until tick 264, then a steady climb to $31.5. We entered at tick 265, held about 22,000 shares and closed in the end-of-case unwind. Plus $117,000, same either way."]),
 ("Slide 8: Total P&amp;L of the three algorithms", "1 min", [
  "We ran three versions in the same market at the same time. The main strategy, <b>algo2e_fin.py</b>, finished at $6,288,771. <b>dir.py</b>, which is only the trend engine with earlier "
  "entries, finished at $6,278,408. The <b>market-making-only</b> version finished at <b>minus $28,433</b>. It was flat in RY when the book broke, so the spike changed nothing for it.",
  "This is the clearest result: the same trend engine produced the same profit, and market making on its own lost money in a market that was mean-reverting for 200 ticks. The faster-entry "
  "version also lost more on CNR, minus $78,000 against minus $53,000, which shows that earlier entries mean more false signals."]),
 ("Slide 9: With and without the spike", "1 min 15 s", [
  "The left panel is the real result, $6.29 million. The right panel is our estimate without the spike: we replace the RY exit with a sale at the last normal bid, $121, and leave CNR and AC "
  "alone. It ends at about <b>$511,000</b>. Depending on the exit price you assume, between $109 and $123, the range is $244,000 to $559,000.",
  "Two points. The spike added $5.78 million, 92% of the total, and it came from Group 12's move in RY, not from anything we did. But we took it systematically: the position was already "
  "built by rule about 16 ticks before the book broke. Second, the estimate assumes the RY drift would still have happened without the spike, so treat $511,000 as the optimistic reading. "
  "Even then it is positive, and the method is identical in both panels."]),
 ("Slide 10: What paid, what did not, and mean reversion", "2 min", [
  "What paid: regime detection that put RY into trend mode within about a tick of the drift, thresholds scaled to volatility, fast sizing and a wide trailing stop so we were still long "
  "when the book broke, and limit-only orders that kept us under 25,000.",
  "What did not: market making, about minus $15,000; the early CNR trend calls, minus $37,000; and our dependence on one event for 92% of the P&amp;L.",
  "<b>How the mean-reversion tilt would have acted.</b> It targets a position opposite to how stretched the price is: long when the Bollinger z-score is low, short when it is high, up to "
  "8,000 or 12,000 shares. It only operates when the market is not in a TREND, not stressed, and after the first 10 seconds. In this market it would have been active for roughly half the time "
  "on each stock, mostly in the first 200 ticks, when prices were bouncing, and it would have switched itself off the moment RY started trending. So it would not have held a short into the spike.",
  "<b>Impact on P&amp;L.</b> From a replay of the logged signals: about <b>+$37,000 at 8,000 shares and +$56,000 at 12,000</b>, before costs, and about +$5,000 to +$20,000 after trading costs. "
  "That is under 1% of $6.29 million. On the roughly $0.5 million you would have without the spike, it is a few percent after costs. It is an upper bound because the real bot would reach those "
  "positions slowly. So we expect it to matter a little and not change the story.",
  "What we would change: a warm-up filter on the trend engine, quote only where resting earns a rebate, and cap exposure when a book turns one-sided, because a spike against a long position "
  "would cost about as much as this one paid. Thank you. Questions?"]),
]
for title, tm, paras in slides:
    block = [P(title, H2), P(f"Time: {tm}", TIME)] + [P(x) for x in paras[:1]]
    story.append(KeepTogether(block))
    story += [P(x) for x in paras[1:]]

# ----------------------------------------------------------------------------- Q&A
QA = [
 ("1. What was the strategy as a whole, and where did we expect to make money?", [
  "The bot has three parts working together: a <b>market maker</b> for quiet markets, a <b>trend engine</b> for breakouts, and a <b>risk layer</b> over both. A regime detector (efficiency ratio, "
  "EMA gap, Bollinger z-score) decides which part is in charge for each stock.",
  "<b>Expected money, in order of how much we planned on it:</b>",
  "- <b>Market making (the base income).</b> We expected prices to bounce around an anchor (mean reversion, a guess, since nobody told us the path). A market maker buys at the bid and sells at the ask "
  "and keeps the spread plus the maker rebate. With a 1-tick spread ($0.01) that is about $10 per 1,000 shares round trip, plus a few dollars of rebate, so it only works with large size and many trades.",
  "- <b>Trend engine (the insurance).</b> If a price moved hard one way, a market maker loses, so the trend engine switches to riding the move instead.",
  "- <b>Sweep-catcher ladder (small extra).</b> Far-from-fair limit orders that fill if a thin book gets run over.",
  "<b>What actually paid:</b> the opposite order. Market making lost about $15k. The trend engine made about $6.3M, almost all of it from one RY event."]),
 ("2. What changes did we make to handle multiple securities and fees/rebates?", [
  "<b>Multiple securities.</b>",
  "- Each stock has its own state: signals, regime, mode (market making, trend or cut), stops and learned entry bar. Tick size and fees are read per stock from the server.",
  "- The three stocks share one set of limits. Every order is checked against worst-case exposure across all three together.",
  "- The trend engine's size is the share of the cap left after the other stocks' positions (95% of the cap minus the others' positions).",
  "- When limit room is tight, aggressive orders go first, then the quotes of the stock with the healthiest wide spread, then the other quotes, then the ladder.",
  "<b>Fees and rebates.</b> CNR and AC pay a rebate for resting orders (about $0.0023 and $0.0011 per share); RY is inverted: resting costs about $0.0020 per share and taking earns $0.0014. "
  "The bot reads each stock's fees from the server, but, to be accurate, its quoting decisions do not change with them. Our response was to quote the largest size (5,000) in calm markets to "
  "harvest spread and rebates. The weakness: it also quoted RY, where resting costs money. Next time we would not quote RY."]),
 ("3. What happened during the simulation?", [
  "- <b>Ticks 0 to 13:</b> three trend calls on CNR reversed straight away, about -$37k.",
  "- <b>Tick 38:</b> the circuit breaker fired once after those CNR losses (P&amp;L about -$40k from its peak), flattened, and paused for 8 s.",
  "- <b>Ticks 0 to 199:</b> quiet and mean-reverting on all three stocks. Market making earned nothing; P&amp;L sat near -$52k.",
  "- <b>Tick 200 to 201:</b> RY started drifting up. The efficiency ratio went from 0 to 1.0, the regime became TREND, and at tick 201.6 the bot started buying RY.",
  "- <b>Ticks 201 to 216:</b> it held 22,062 RY shares as price went from $100 to $118 (open profit about $0.37M).",
  "- <b>Tick 217:</b> RY's book turned one-sided (Group 12's activity): bids at $346, then $402, no asks. The bot sold all 22,062 shares in five orders over about 4 s: about +$5.8M. A second RY jump at tick 261 added only about +$6k.",
  "- <b>Tick 265:</b> AC began a steady climb from $25.1; the bot bought, held about 22k shares, and closed in the end-of-case unwind at tick 296: +$117k.",
  "<b>Final:</b> $6,288,771 (RY +$6.22M, AC +$117k, CNR -$53k)."]),
 ("4. What was the sizing strategy?", [
  "<b>Rule: be big when the evidence is strong or the risk is small, small when the market is stressed.</b>",
  "- <b>Market making:</b> 5,000 shares per side when calm or in a healthy wide spread, 3,000 in normal conditions, half of that when stressed, 2,000 in thin books. Per-stock inventory cap 9,000 shares.",
  "- <b>Inventory brake:</b> with r = position / 9,000, the size on the side that adds inventory is multiplied by e^(-3r), and that side is switched off at r of 0.85 (7,650 shares). "
  "The reducing side gets larger, up to size x (1 + r), capped at 5,000.",
  "- <b>Trend engine:</b> first order 60% of the cap, growing with signal strength up to about 95% of the cap (about 22k shares), shared across stocks, in chunks of at most 5,000 shares.",
  "- <b>Sweep ladder:</b> 1,500, 1,500 and 2,000 shares at 3%, 8% and 15% from fair value.",
  "- <b>Session governor:</b> quote size is halved if total P&amp;L is below -$25k, and quartered below -$50k."]),
 ("5. Why did market making not make money?", [
  "- <b>The spread was one tick.</b> In the first 200 ticks the median spread was 1 tick ($0.01) on all three stocks. That is about $0.01 per share of gross income per trade.",
  "- <b>The losses are bigger than the gains.</b> The stop-loss on inventory is the larger of 5 ticks or 3x volatility. Rough break-even arithmetic: winning 1 tick and losing 5 ticks needs "
  "about 5 wins out of every 6 trades just to break even. Prices moved in jumps larger than a cent, so stops fired often: 86 times on CNR. Each stop crosses the spread and gives it back.",
  "- <b>Adverse selection.</b> The orders that fill are disproportionately the ones before a price move, so the market maker tends to be on the wrong side.",
  "- <b>RY fees.</b> Resting orders on RY cost money, which is consistent with its small loss (-$3.7k). We have not proven that was the cause.",
  "<b>Evidence:</b> market making in the main run lost about $15k (CNR -$16.2k, RY -$3.7k, AC +$5.1k). The market-making-only build, in the same market, finished at -$28.4k (CNR -$28.7k, RY -$6.1k, AC +$6.4k)."]),
 ("6. How would the mean-reversion strategy have acted in this market?", [
  "<b>What it is.</b> A target inventory based on the Bollinger z-score: target = -MAX x clip(z / 2, -1, 1), where MAX is 8,000 or 12,000 shares. If price is low in its band (negative z), the target is long; "
  "if high, short. The quotes are skewed toward that target instead of toward zero.",
  "<b>When it runs.</b> Only outside TREND, when the slow t-stat is small and the volatility state is not stressed, after a 10 s warm-up, and only while the stock is in market-making mode.",
  "<b>In this market.</b> Prices bounced inside narrow bands for 200 ticks (CNR standard deviation about $0.29, RY about $0.08, AC about $0.04), so the tilt would have been active about 45% of the time on CNR, "
  "54% on RY and 44% on AC. At tick 200 RY became TREND, so the tilt would have switched off at once and not held a short into the drift or the spike. In the replay, almost all of its gain comes from ticks 0 to 199."]),
 ("7. Do we expect it to affect P&amp;L, and by how much?", [
  "<b>Estimate (a replay of the logged signals, not a rerun of the bot):</b>",
  "- At 8,000 shares: about <b>+$37k</b> gross (CNR +$23k, RY +$12k, AC +$2k). At 12,000 shares: about <b>+$56k</b> gross.",
  "- After trading costs (half to a full tick on about 3M shares traded at 8,000): about <b>+$5k to +$20k</b>.",
  "- That is <b>under 1% of $6.29M</b>. Against the about $511k without the spike, roughly 7% to 11% gross and 1% to 4% after costs.",
  "<b>Caveats:</b> it is an upper bound because it assumes the position is at target instantly (the real bot reaches it slowly through quotes), it ignores interaction with the stops, and our earlier tests said the tilt "
  "lost to plain market making. So we expect a small effect and no change to the story. It was off in the run."]),
 ("8. What was the directional (trend) strategy, and how did it work?", [
  "<b>Idea:</b> when a price moves steadily in one direction, take a large position in that direction and hold it with a trailing stop (trend following / momentum).",
  "<b>Entry (all must hold):</b> EMA gap (fast 1 s minus slow 8 s) above max(12 ticks, 5x volatility); efficiency ratio at least 0.45 in the same direction; spread at most 6 ticks; signal held 0.8 s; "
  "room under the cap (at least 2,000 shares); not in cooldown or lockout.",
  "<b>Size and orders:</b> 60% of the cap first, growing to about 95%; capped limit orders (3 ticks through the touch), chunks of up to 5,000.",
  "<b>Exit (any):</b> trailing stop of max(15 ticks, 6x volatility) from the best price; gap falls below 25% of the entry threshold; no new high or low for about 8 s; end-of-case unwind.",
  "<b>Learning:</b> a losing ride raises that stock's entry bar by 1.4x (up to 3x); a winning ride lowers it by 0.8x; three losers in a row switch it off for that stock for 60 s.",
  "<b>How it worked:</b> RY: entry at tick 201, +$451k on the ride before the spike, then +$5.78M selling into the spike. AC: +$112k on the climb. CNR: three early false calls, -$36k, after which the bar rose and it did not fire on CNR again."]),
 ("9. How did we plan sizing, limits and unwinding?", [
  "<b>Limits.</b> The case limit is 25,000 shares gross and net.",
  "- <b>Planning cap 93%</b> (23,250). Before every order: assume all resting orders, in-flight orders and this order fill at once, for all three stocks together. If it does not fit, shrink by 40% at a time down to 100 shares, then drop it.",
  "- <b>Safety net 96%</b> (24,000): if actual gross or net passes it, stop adding and cut the biggest position at once.",
  "- <b>Circuit breaker:</b> P&amp;L down $40,000 from its peak means flatten and pause for 8 s. It fired once, at tick 38.",
  "- <b>Orders:</b> limit orders only, within 2% (at least 10 ticks) of fair value; refuse if the touch is further out; leftovers cancelled after 0.6 s.",
  "<b>Unwinding.</b> About 20 s before the end, stop adding risk; about 8 s before the end, cross the spread to finish flat (both scaled to the case length). After a trend exit the position is sold down in 'cut' mode. "
  "Ctrl-C cancels all orders and flattens.",
  "<b>Result:</b> peak gross 23,088 and peak net 22,837 against 25,000, no samples above 24,000, and the AC position was closed at tick 296."]),
]
story += [P("Questions answered in basic, technical terms", H2),
          P("Each answer below is self-contained, so you can rehearse it separately from the slide script.", TIME)]
for q, parts in QA:
    block = [P(q, ParagraphStyle("QH", parent=BODY, fontName="DV-B", textColor=ACC, spaceBefore=8, spaceAfter=3))]
    first = parts[0]
    block.append(Paragraph(first[2:], BUL, bulletText="\u2022") if first.startswith("- ") else P(first))
    story.append(KeepTogether(block))
    for x in parts[1:]:
        story.append(Paragraph(x[2:], BUL, bulletText="•") if x.startswith("- ") else P(x))

story += [P("Do not say", H2),
          P("&bull; \"The mean-reversion flag was on.\" It was off.", BUL),
          P("&bull; \"We predicted the spike.\" The rules positioned us; we predicted nothing.", BUL),
          P("&bull; \"$511k is what we would have made.\" It is an estimate.", BUL),
          P("&bull; \"Fees are built into our quoting.\" They are read per stock but not used in decisions.", BUL),
          P("&bull; \"No fines ever.\" We checked this run only.", BUL),
          P("&bull; Exact RY exit prices. The average of about $380 per share is inferred from the P&amp;L jump; the logged fill price is the mid.", BUL)]

def footer(c, d):
    c.saveState(); c.setFont("DV", 8); c.setFillColor(MUTED)
    c.drawString(0.8 * inch, 0.5 * inch, "RIT ALGO2e speaking script  |  algo2e_fin.py"); c.drawRightString(letter[0] - 0.8 * inch, 0.5 * inch, f"Page {d.page}")
    c.restoreState()

out = "analysis_6M/RIT_ALGO2e_speaking_script.pdf"
SimpleDocTemplate(out, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch, topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                  title="RIT ALGO2e speaking script", author="Team").build(story, onFirstPage=footer, onLaterPages=footer)
print(out)
