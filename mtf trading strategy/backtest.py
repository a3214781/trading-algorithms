"""
LucidFlex 25K — Multi-Timeframe Eval Bot v2
=============================================
THREE TIMEFRAMES:
  Daily  → Overall trend (above/below 10 SMA)
  1-Hour → Session momentum (EMA slope + price position)
  5-Min  → Entry triggers (ORB, VWAP pullback, EMA touch, PDHL break)

RULE: All three must AGREE on direction before entry.
  Daily LONG + 1H LONG + 5M long trigger = TAKE THE TRADE
  Any disagreement = SIT OUT

This is how institutional traders operate:
  "If the 1-minute chart looks bullish but the 4-hour chart is hitting
   major resistance, the smart move is to stay on the sidelines."

Data from yfinance (all free):
  Daily → 1 year (trend context)
  1H    → 730 days (but we only use last 60 days to match 5m)
  5M    → 60 days (entry signals)

Run: python3 backtest.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import warnings
warnings.filterwarnings("ignore")

PARAMS = {
    "initial_capital": 25_000,
    "profit_target": 3_000,
    "max_loss_limit": 2_000,
    "mll_buffer": 80,
    "daily_goal": 625,
    "consistency_cap": 0.49,
    "mnq_point_value": 2.0,
    "max_contracts": 2,
    "commission": 0.50,
    "max_trades_day": 3,

    # Session
    "no_trade_before_h": 9, "no_trade_before_m": 50,
    "eod_flatten_h": 15, "eod_flatten_m": 50,
    "no_new_after_h": 15, "no_new_after_m": 40,

    # TF1: Daily trend
    "daily_sma": 10,

    # TF2: 1-Hour momentum
    "h1_ema_fast": 9,
    "h1_ema_slow": 21,

    # TF3: 5-Min entries (TradingView optimized — $2k+ profit)
    "orb_minutes": 1,
    "orb_stop": 80, "orb_rr": 1.9,
    "orb_min_range": 8, "orb_max_range": 160,

    "vwap_zone": 15,
    "vwap_stop": 65, "vwap_rr": 1.5,

    "ema5_period": 21,
    "ema5_zone": 12,
    "ema5_stop": 45, "ema5_rr": 1.0,

    "pdhl_buffer": 5,
    "pdhl_stop": 50, "pdhl_rr": 1.5,
}


# ============================================================
# 1. DATA — fetch all three timeframes
# ============================================================
def fetch_all_data(ticker="NQ=F"):
    print(f"📥 Fetching {ticker} across 3 timeframes...")

    # Daily (1 year)
    dfd = yf.download(ticker, period="1y", interval="1d", auto_adjust=True, progress=False)
    if isinstance(dfd.columns, pd.MultiIndex): dfd.columns = dfd.columns.get_level_values(0)
    dfd = dfd[["Open", "High", "Low", "Close"]].dropna()
    print(f"   Daily: {len(dfd)} bars | {dfd.index[0].date()} → {dfd.index[-1].date()}")

    # 1-Hour (730 days)
    df1h = yf.download(ticker, period="730d", interval="1h", auto_adjust=True, progress=False)
    if isinstance(df1h.columns, pd.MultiIndex): df1h.columns = df1h.columns.get_level_values(0)
    if df1h.index.tz is None: df1h.index = df1h.index.tz_localize("UTC")
    df1h.index = df1h.index.tz_convert("America/New_York")
    df1h = df1h[["Open", "High", "Low", "Close", "Volume"]].dropna()
    print(f"   1H:    {len(df1h)} bars | {df1h.index[0].date()} → {df1h.index[-1].date()}")

    # 5-Minute (60 days)
    df5m = yf.download(ticker, period="60d", interval="5m", auto_adjust=True, progress=False)
    if isinstance(df5m.columns, pd.MultiIndex): df5m.columns = df5m.columns.get_level_values(0)
    if df5m.index.tz is None: df5m.index = df5m.index.tz_localize("UTC")
    df5m.index = df5m.index.tz_convert("America/New_York")
    df5m = df5m[["Open", "High", "Low", "Close", "Volume"]].dropna()
    days5 = len(df5m.groupby(df5m.index.date))
    print(f"   5M:    {len(df5m)} bars, {days5} days | {df5m.index[0].date()} → {df5m.index[-1].date()}")

    return dfd, df1h, df5m


# ============================================================
# 2. TF1: DAILY BIAS
# ============================================================
def compute_daily_bias(dfd, p):
    """
    +1 = LONG bias | -1 = SHORT bias
    Logic: previous day's close vs 10-day SMA
    """
    dfd = dfd.copy()
    dfd["sma"] = dfd["Close"].rolling(p["daily_sma"]).mean()
    bias = {}
    for i in range(1, len(dfd)):
        d = dfd.index[i]
        if isinstance(d, pd.Timestamp): d = d.date()
        prev_close = dfd["Close"].iloc[i - 1]
        prev_sma = dfd["sma"].iloc[i - 1]
        if pd.isna(prev_sma):
            bias[d] = 0
        elif prev_close > prev_sma:
            bias[d] = 1
        else:
            bias[d] = -1
    return bias


# ============================================================
# 3. TF2: 1-HOUR MOMENTUM (per-bar, mapped to 5m bars)
# ============================================================
def compute_hourly_momentum(df1h, p):
    """
    For each hour, compute momentum direction:
      +1 = bullish (fast EMA > slow EMA and rising)
      -1 = bearish (fast EMA < slow EMA and falling)
       0 = choppy/neutral

    Returns dict: timestamp → momentum direction
    We'll map each 5m bar to its containing hour's momentum.
    """
    df = df1h.copy()
    df["ema_f"] = df["Close"].ewm(span=p["h1_ema_fast"], adjust=False).mean()
    df["ema_s"] = df["Close"].ewm(span=p["h1_ema_slow"], adjust=False).mean()
    df["ema_f_prev"] = df["ema_f"].shift(1)

    momentum = {}
    for i in range(1, len(df)):
        ts = df.index[i]
        ef = df["ema_f"].iloc[i]
        es = df["ema_s"].iloc[i]
        ef_prev = df["ema_f_prev"].iloc[i]

        if pd.isna(ef) or pd.isna(es) or pd.isna(ef_prev):
            momentum[ts] = 0
        elif ef > es and ef > ef_prev:  # above slow + rising
            momentum[ts] = 1
        elif ef < es and ef < ef_prev:  # below slow + falling
            momentum[ts] = -1
        else:
            momentum[ts] = 0

    return momentum


def get_hourly_momentum_for_bar(bar_time, h1_momentum):
    """Find the most recent hourly momentum reading for a given 5m bar time."""
    # Round down to the hour
    hour_key = bar_time.floor("h")

    # Try exact match first, then search backwards
    if hour_key in h1_momentum:
        return h1_momentum[hour_key]

    # Search for closest previous hour
    for offset in range(1, 4):
        check = hour_key - pd.Timedelta(hours=offset)
        if check in h1_momentum:
            return h1_momentum[check]

    return 0  # neutral if no data


# ============================================================
# 4. 5-MIN INDICATORS
# ============================================================
def add_5m_indicators(df, p):
    df["ema"] = df["Close"].ewm(span=p["ema5_period"], adjust=False).mean()

    # VWAP
    df["vwap"] = np.nan
    for date, day_df in df.groupby(df.index.date):
        tp = (day_df["High"] + day_df["Low"] + day_df["Close"]) / 3
        cv = (tp * day_df["Volume"]).cumsum()
        v = day_df["Volume"].cumsum().replace(0, np.nan)
        df.loc[day_df.index, "vwap"] = cv / v

    # ORB
    df["orb_high"] = np.nan; df["orb_low"] = np.nan; df["orb_range"] = np.nan
    for date, day_df in df.groupby(df.index.date):
        start = pd.Timestamp(date).tz_localize("America/New_York").replace(hour=9, minute=30)
        end = start + pd.Timedelta(minutes=p["orb_minutes"])
        orb = day_df[(day_df.index >= start) & (day_df.index < end)]
        if orb.empty: continue
        oh, ol = orb["High"].max(), orb["Low"].min()
        post = day_df[day_df.index >= end]
        df.loc[post.index, "orb_high"] = oh
        df.loc[post.index, "orb_low"] = ol
        df.loc[post.index, "orb_range"] = oh - ol

    # Previous day H/L
    df["pdh"] = np.nan; df["pdl"] = np.nan
    dates = sorted(set(df.index.date))
    for i in range(1, len(dates)):
        prev = df[df.index.date == dates[i - 1]]
        if prev.empty: continue
        mask = df.index.date == dates[i]
        df.loc[mask, "pdh"] = prev["High"].max()
        df.loc[mask, "pdl"] = prev["Low"].min()

    df["prev_close"] = df["Close"].shift(1)
    return df


# ============================================================
# 5. BACKTEST
# ============================================================
def run_backtest(df5m, daily_bias, h1_momentum, p):
    ptv, qty = p["mnq_point_value"], p["max_contracts"]
    equity = float(p["initial_capital"])
    day_start_eq = equity; day_pnl = 0.0; trades_today = 0
    total_eval = 0.0; current_date = None; position = None
    strat_used = {}
    trades, eq_curve, daily_log = [], [], []

    alignment_stats = {"aligned": 0, "not_aligned": 0}

    for i in range(5, len(df5m)):
        bar = df5m.iloc[i]; bt = df5m.index[i]; bd = bt.date()
        bh, bm = bt.hour, bt.minute

        if bd != current_date:
            if current_date is not None:
                daily_log.append({"date": current_date, "pnl": day_pnl,
                                  "trades": trades_today, "equity": equity,
                                  "bias": daily_bias.get(current_date, 0)})
                if day_pnl > 0: total_eval += day_pnl
            current_date = bd; day_start_eq = equity
            day_pnl = 0.0; trades_today = 0; strat_used = {}

        day_pnl = equity - day_start_eq

        # === THREE TIMEFRAME ALIGNMENT ===
        tf1_bias = daily_bias.get(bd, 0)                              # Daily
        tf2_mom = get_hourly_momentum_for_bar(bt, h1_momentum)        # 1H
        # TF3 (5m) is the entry itself — checked per-strategy below

        # All three must agree. If daily=0 or hourly=0, skip.
        if tf1_bias == 0 or tf2_mom == 0:
            alignment_stats["not_aligned"] += 1
            # Still manage existing position
            pass
        elif tf1_bias == tf2_mom:
            alignment_stats["aligned"] += 1
        else:
            alignment_stats["not_aligned"] += 1

        # Direction we're allowed to trade (only when daily + 1H agree)
        if tf1_bias == tf2_mom and tf1_bias != 0:
            allowed_side = "long" if tf1_bias == 1 else "short"
        else:
            allowed_side = None

        # EOD flatten
        is_eod = bh == p["eod_flatten_h"] and bm >= p["eod_flatten_m"]
        if is_eod and position:
            pnl = _pnl(position, bar["Close"], p); equity += pnl
            trades.append({**position, "exit_price": bar["Close"],
                           "exit_time": bt, "pnl": pnl, "exit_reason": "EOD"})
            position = None; day_pnl = equity - day_start_eq

        # Manage position
        if position:
            s = position["side"]
            hs = bar["Low"] <= position["stop"] if s == "long" else bar["High"] >= position["stop"]
            ht = bar["High"] >= position["target"] if s == "long" else bar["Low"] <= position["target"]
            if ht or hs:
                ep = position["target"] if ht else position["stop"]
                er = "Target" if ht else "Stop"
                pnl = _pnl(position, ep, p); equity += pnl
                trades.append({**position, "exit_price": ep,
                               "exit_time": bt, "pnl": pnl, "exit_reason": er})
                position = None; day_pnl = equity - day_start_eq

        eq_curve.append({"time": bt, "equity": equity})
        if position: continue
        if allowed_side is None: continue  # TFs not aligned

        # Time guards
        is_rth = (bh > 9 or (bh == 9 and bm >= 30)) and bh < 16
        if not is_rth: continue
        if bh < p["no_trade_before_h"] or (bh == p["no_trade_before_h"] and bm < p["no_trade_before_m"]): continue
        if bh > p["no_new_after_h"] or (bh == p["no_new_after_h"] and bm >= p["no_new_after_m"]): continue

        # Risk gates
        dd = p["initial_capital"] - equity
        proj = total_eval + max(day_pnl, 0)
        consist = max(day_pnl, 0) / proj if proj > 0 else 0
        ok = (dd < p["max_loss_limit"] and (p["max_loss_limit"] - dd) > p["mll_buffer"]
              and day_pnl < p["daily_goal"] and total_eval < p["profit_target"]
              and trades_today < p["max_trades_day"] and consist < p["consistency_cap"]
              and not is_eod)
        if not ok: continue

        close = bar["Close"]
        side = allowed_side  # already validated by TF alignment

        def can(s, mx=1): return strat_used.get(s, 0) < mx
        def fire(s): strat_used[s] = strat_used.get(s, 0) + 1

        # ═══ A: ORB BREAKOUT ═══
        if can("ORB"):
            oh = bar["orb_high"]; ol = bar["orb_low"]; orr = bar.get("orb_range", np.nan)
            if not pd.isna(oh) and not pd.isna(orr) and p["orb_min_range"] <= orr <= p["orb_max_range"]:
                if side == "long" and close > oh:
                    position = _e("long", close, p["orb_stop"], p["orb_rr"], qty, bt, "ORB")
                    trades_today += 1; fire("ORB")
                elif side == "short" and close < ol:
                    position = _e("short", close, p["orb_stop"], p["orb_rr"], qty, bt, "ORB")
                    trades_today += 1; fire("ORB")
                if position: continue

        # ═══ B: VWAP PULLBACK ═══
        if can("VWAP", 2):
            vwap = bar["vwap"]; pc = bar["prev_close"]
            if not pd.isna(vwap) and vwap > 0 and not pd.isna(pc):
                dist = close - vwap
                near = abs(dist) <= p["vwap_zone"]
                resume_long = side == "long" and close > pc and dist >= 0
                resume_short = side == "short" and close < pc and dist <= 0
                if near and (resume_long or resume_short):
                    position = _e(side, close, p["vwap_stop"], p["vwap_rr"], qty, bt, "VWAP-PB")
                    trades_today += 1; fire("VWAP")
                    continue

        # ═══ C: EMA TREND TOUCH ═══
        if can("EMA", 2):
            ema = bar["ema"]; pc = bar["prev_close"]
            if not pd.isna(ema) and not pd.isna(pc):
                dist = close - ema
                near = abs(dist) <= p["ema5_zone"]
                trend_long = side == "long" and dist >= 0 and close > pc
                trend_short = side == "short" and dist <= 0 and close < pc
                if near and (trend_long or trend_short):
                    position = _e(side, close, p["ema5_stop"], p["ema5_rr"], qty, bt, "EMA-T")
                    trades_today += 1; fire("EMA")
                    continue

        # ═══ D: PREVIOUS DAY H/L BREAK ═══
        if can("PDHL"):
            pdh = bar.get("pdh", np.nan); pdl = bar.get("pdl", np.nan)
            if not pd.isna(pdh):
                buf = p["pdhl_buffer"]
                if side == "long" and close > pdh + buf:
                    position = _e("long", close, p["pdhl_stop"], p["pdhl_rr"], qty, bt, "PDHL")
                    trades_today += 1; fire("PDHL")
                elif side == "short" and close < pdl - buf:
                    position = _e("short", close, p["pdhl_stop"], p["pdhl_rr"], qty, bt, "PDHL")
                    trades_today += 1; fire("PDHL")

    if current_date:
        daily_log.append({"date": current_date, "pnl": day_pnl,
                          "trades": trades_today, "equity": equity,
                          "bias": daily_bias.get(current_date, 0)})

    tdf = pd.DataFrame(trades)
    edf = pd.DataFrame(eq_curve).set_index("time") if eq_curve else pd.DataFrame()
    ddf = pd.DataFrame(daily_log)

    total_bars = alignment_stats["aligned"] + alignment_stats["not_aligned"]
    if total_bars > 0:
        print(f"\n🔄 TF Alignment: {alignment_stats['aligned']}/{total_bars} bars aligned "
              f"({alignment_stats['aligned']/total_bars*100:.1f}%)")

    return tdf, edf, ddf


def _e(side, price, stop, rr, qty, time, strat):
    if side == "long":
        return {"side": "long", "entry_price": price, "entry_time": time,
                "qty": qty, "stop": price - stop, "target": price + stop * rr, "strategy": strat}
    return {"side": "short", "entry_price": price, "entry_time": time,
            "qty": qty, "stop": price + stop, "target": price - stop * rr, "strategy": strat}

def _pnl(pos, ep, p):
    q, pt = pos["qty"], p["mnq_point_value"]
    raw = (ep - pos["entry_price"]) * pt * q if pos["side"] == "long" \
        else (pos["entry_price"] - ep) * pt * q
    return raw - p["commission"] * q


# ============================================================
# STATS
# ============================================================
def compute_stats(tdf, edf, ddf, p):
    if tdf.empty: print("⚠️ No trades."); return {}
    t = tdf; w = t[t["pnl"] > 0]; l = t[t["pnl"] <= 0]
    net = t["pnl"].sum(); gp = w["pnl"].sum() if len(w) else 0
    gl = abs(l["pnl"].sum()) if len(l) else 0.01; wr = len(w) / len(t)
    mdd = (edf["equity"] - edf["equity"].cummax()).min() if not edf.empty else 0
    td = len(ddf) if not ddf.empty else 1
    ad = len(ddf[ddf["trades"] > 0]) if not ddf.empty else 0
    adp = net / td if td > 0 else 0
    est = int(np.ceil(p["profit_target"] / adp)) if adp > 0 else 999
    best = ddf["pnl"].max() if not ddf.empty else 0
    worst = ddf["pnl"].min() if not ddf.empty else 0
    consist = best / net if net > 0 else 0
    passed = net >= p["profit_target"] and consist < 0.50

    # Direction breakdown
    longs = t[t["side"] == "long"]; shorts = t[t["side"] == "short"]

    strats = {}
    for s in t["strategy"].unique():
        st = t[t["strategy"] == s]; sw = st[st["pnl"] > 0]
        strats[s] = {"n": len(st), "wr": len(sw)/len(st)*100 if len(st) else 0, "pnl": st["pnl"].sum()}

    s = {"Total Trades": len(t), "Win Rate": f"{wr*100:.1f}%",
         "Profit Factor": f"{gp/gl:.2f}", "Net P&L": f"${net:,.0f}",
         "Expectancy": f"${net/len(t):.1f}/trade",
         "Avg Win": f"${w['pnl'].mean():.0f}" if len(w) else "—",
         "Avg Loss": f"${l['pnl'].mean():.0f}" if len(l) else "—",
         "Max Drawdown": f"${mdd:,.0f}", "": "",
         "Total Days": td,
         "Active Days": f"{ad} ({ad/td*100:.0f}%)",
         "Trades / Day": f"{len(t)/td:.1f}",
         "Trades / Active": f"{len(t)/ad:.1f}" if ad > 0 else "—",
         "Long Trades": f"{len(longs)} ({len(longs[longs['pnl']>0])}/{len(longs)} win)",
         "Short Trades": f"{len(shorts)} ({len(shorts[shorts['pnl']>0])}/{len(shorts)} win)",
         " ": ""}

    for nm, d in sorted(strats.items(), key=lambda x: -x[1]["pnl"]):
        s[f"  {nm}"] = f"{d['n']}t  {d['wr']:.0f}%WR  ${d['pnl']:,.0f}"

    s["  "] = ""
    s["Avg Daily P&L"] = f"${adp:.0f}"
    s["Est Days to Pass"] = f"{est}" if est < 999 else "N/A"
    s["Best Day"] = f"${best:.0f}"
    s["Worst Day"] = f"${worst:.0f}"
    s["Consistency"] = f"{consist:.0%} {'✅' if consist < 0.50 else '⚠️ >50%'}"
    s["   "] = ""
    s["VERDICT"] = "🎉 EVAL PASSED" if passed else \
                   "⚠️ TARGET HIT but consistency >50%" if net >= p["profit_target"] else \
                   f"❌ ${p['profit_target']-net:.0f} to go"
    return s


# ============================================================
# PLOT
# ============================================================
def plot_results(tdf, edf, ddf, stats, p):
    fig = plt.figure(figsize=(18, 14)); fig.patch.set_facecolor("#0d1117")
    gs = gridspec.GridSpec(3, 2, figure=fig, hspace=.45, wspace=.3, height_ratios=[1.2, .8, .8])
    tc = "#e6edf3"; gc = "#30363d"
    G, R, B, O, P = "#3fb950", "#f85149", "#58a6ff", "#d29922", "#bc8cff"
    SC = {"ORB": G, "VWAP-PB": B, "EMA-T": O, "PDHL": P}

    def sty(ax):
        ax.set_facecolor("#161b22"); ax.tick_params(colors=tc, labelsize=8)
        for s in ax.spines.values(): s.set_edgecolor(gc)
        ax.grid(color=gc, lw=.4, alpha=.4)
        ax.xaxis.label.set_color(tc); ax.yaxis.label.set_color(tc); ax.title.set_color(tc)

    ax1 = fig.add_subplot(gs[0, :]); sty(ax1); eq = edf["equity"]; ic = p["initial_capital"]
    ax1.plot(eq.index, eq.values, color=B, lw=1.5)
    ax1.axhline(ic, color="#8b949e", ls="--", lw=.8)
    ax1.axhline(ic - p["max_loss_limit"], color=R, ls=":", lw=1, label="MLL")
    ax1.axhline(ic + p["profit_target"], color=G, ls=":", lw=1, label="Target")
    ax1.fill_between(eq.index, ic, eq.values, where=eq.values >= ic, alpha=.1, color=G)
    ax1.fill_between(eq.index, ic, eq.values, where=eq.values < ic, alpha=.1, color=R)
    ax1.set_title("Equity — Multi-TF Eval Bot (Daily + 1H + 5M)", fontsize=13, fontweight="bold")
    ax1.legend(facecolor="#161b22", labelcolor=tc, fontsize=9)

    ax2 = fig.add_subplot(gs[1, 0]); sty(ax2)
    pnls = tdf["pnl"].values
    cols = [SC.get(tdf.iloc[j]["strategy"], G) if v > 0 else R for j, v in enumerate(pnls)]
    ax2.bar(range(len(pnls)), pnls, color=cols, alpha=.85, width=.7)
    ax2.axhline(0, color="#8b949e", lw=.6)
    ax2.set_title("Trade P&L", fontsize=11, fontweight="bold")
    for nm, cl in SC.items(): ax2.plot([], [], 's', color=cl, ms=6, label=nm)
    ax2.plot([], [], 's', color=R, ms=6, label="Loss"); ax2.legend(facecolor="#161b22", labelcolor=tc, fontsize=7, ncol=3)

    ax3 = fig.add_subplot(gs[1, 1]); sty(ax3); cum = tdf["pnl"].cumsum()
    ax3.plot(cum.values, color=B, lw=1.5)
    ax3.fill_between(range(len(cum)), 0, cum.values, where=cum.values >= 0, alpha=.1, color=G)
    ax3.fill_between(range(len(cum)), 0, cum.values, where=cum.values < 0, alpha=.1, color=R)
    ax3.axhline(p["profit_target"], color=G, ls="--", lw=1); ax3.axhline(-p["max_loss_limit"], color=R, ls="--", lw=1)
    ax3.set_title("Cumulative P&L", fontsize=11, fontweight="bold")

    ax4 = fig.add_subplot(gs[2, 0]); sty(ax4)
    if not ddf.empty:
        d = ddf[ddf["trades"] > 0]
        if not d.empty:
            ax4.bar(range(len(d)), d["pnl"].values,
                    color=[G if v > 0 else R for v in d["pnl"].values], alpha=.8)
            step = max(1, len(d) // 15)
            ax4.set_xticks(range(0, len(d), step))
            ax4.set_xticklabels([str(dt)[-5:] for dt in d["date"].values[::step]], rotation=45, fontsize=7)
    ax4.axhline(0, color="#8b949e", lw=.6); ax4.set_title("Daily P&L", fontsize=11, fontweight="bold")

    ax5 = fig.add_subplot(gs[2, 1]); ax5.axis("off"); ax5.set_facecolor("#161b22")
    txt = "\n".join([f"{k:<36} {v}" for k, v in stats.items()])
    ax5.text(.02, .97, txt, fontsize=7, color=tc, fontfamily="monospace",
             transform=ax5.transAxes, va="top",
             bbox=dict(facecolor="#161b22", edgecolor=gc, boxstyle="round,pad=.4"))
    fig.suptitle("LucidFlex 25K — Multi-TF Eval Bot (D+1H+5M)", color=tc, fontsize=14, fontweight="bold", y=1.01)
    plt.savefig("mtf_bot_results.png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print("📊 Chart → mtf_bot_results.png"); plt.show()


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    print("=" * 65)
    print("  LucidFlex 25K — Multi-Timeframe Eval Bot")
    print("  Daily (trend) + 1H (momentum) + 5M (entries)")
    print("  Only trades when ALL THREE timeframes agree")
    print("=" * 65)

    dfd, df1h, df5m = fetch_all_data("NQ=F")

    # Compute higher TF signals
    daily_bias = compute_daily_bias(dfd, PARAMS)
    h1_momentum = compute_hourly_momentum(df1h, PARAMS)

    # Show recent bias
    print("\n📊 DAILY BIAS (last 15 days):")
    for date in sorted(daily_bias.keys())[-15:]:
        b = daily_bias[date]
        print(f"  {date}  {'🟢 LONG' if b == 1 else '🔴 SHORT'}")

    # Add 5m indicators
    df5m = add_5m_indicators(df5m, PARAMS)
    df5r = df5m.between_time("09:00", "17:00").copy()

    # Run backtest
    t, e, d = run_backtest(df5r, daily_bias, h1_momentum, PARAMS)
    s = compute_stats(t, e, d, PARAMS)

    print("\n📈 RESULTS\n" + "-" * 60)
    for k, v in s.items(): print(f"  {k:<38} {v}")

    if not t.empty:
        print(f"\n📋 TRADES ({len(t)})\n" + "-" * 120)
        for _, tr in t.head(80).iterrows():
            ic = "🟢" if tr["side"] == "long" else "🔴"
            pi = "✅" if tr["pnl"] > 0 else "❌"
            print(f"  {ic} {str(tr['entry_time'])[:16]} | {tr['side']:>5} | "
                  f"{tr['entry_price']:.1f}→{tr['exit_price']:.1f} | "
                  f"${tr['pnl']:>8.1f} {pi} | {tr['exit_reason']:>6} | {tr['strategy']}")
        if len(t) > 80: print(f"  ... +{len(t) - 80} more")

    if not d.empty:
        print(f"\n📅 DAILY\n" + "-" * 80)
        for _, dd in d[d["trades"] > 0].head(30).iterrows():
            ic = "✅" if dd["pnl"] > 0 else "❌"
            b = "🟢L" if dd["bias"] == 1 else "🔴S"
            print(f"  {dd['date']} {b} | {dd['trades']}t | ${dd['pnl']:>8.1f} {ic} | eq ${dd['equity']:,.0f}")

    if not t.empty: plot_results(t, e, d, s, PARAMS)

    print("\n✅ Run: python3 backtest.py")
