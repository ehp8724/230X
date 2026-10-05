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
BUL = ParagraphStyle("BUL", parent=BODY, leftIndent=14, bulletIndent=2, spaceAfter=3)

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
  "$118. At tick 217 the book became one-sided because of Group 12's activity: bids jumped to $346 and then $402. We sold the whole position in about two seconds. That trade made "
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
