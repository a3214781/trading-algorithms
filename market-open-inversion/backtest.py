import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import warnings
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
SYMBOL          = "NQ=F"
END             = datetime.today().strftime("%Y-%m-%d")
START           = (datetime.today() - timedelta(days=59)).strftime("%Y-%m-%d")
INTERVAL        = "5m"

ACCOUNT_SIZE    = 50_000
CONTRACTS       = 20
TICK_SIZE       = 0.25
TICK_VALUE      = 5.00          # NQ full size $5/tick (MNQ = $0.50)

SESSION_START   = "09:30"
SESSION_END     = "16:00"
HTF_TF          = "30min"
REVERSAL_PCT    = 0.50          # 50% of opening candle size
TP_RR           = 0.5           # take profit = 0.5x risk
STOP_BUFFER_T   = 2             # ticks beyond wick
MAX_TRADES_DAY  = 1
CUTOFF_TIME     = "11:30"

# break-even settings
USE_BE          = True
BE_TRIGGER_RR   = 0.3           # move SL to BE when price reaches 30% of TP

# trailing stop
USE_TRAIL       = True
TRAIL_TICKS     = 10            # trail by 10 ticks once in profit

# ─────────────────────────────────────────────
# 1. FETCH DATA
# ─────────────────────────────────────────────
print(f"Fetching {SYMBOL} {INTERVAL} data...")
raw = yf.download(SYMBOL, start=START, end=END, interval=INTERVAL, progress=False)
raw.index = pd.to_datetime(raw.index)
if raw.index.tz is None:
    raw.index = raw.index.tz_localize("UTC")
raw.index = raw.index.tz_convert("America/New_York")

if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)

df = raw[["Open","High","Low","Close"]].copy()
df.columns = ["open","high","low","close"]
df.dropna(inplace=True)
print(f"Loaded {len(df)} bars from {df.index[0].date()} to {df.index[-1].date()}")

# ─────────────────────────────────────────────
# 2. HTF BIAS (30m opening candle direction)
# ─────────────────────────────────────────────
def get_htf_bias(df, htf="30min", session_start="09:30"):
    htf_df = df.resample(htf, origin="start_day").agg(
        {"open":"first","high":"max","low":"min","close":"last"}
    ).dropna()
    htf_df = htf_df.between_time(session_start, session_start)
    bias = {}
    for ts, row in htf_df.iterrows():
        bias[ts.date()] = "bull" if row["close"] > row["open"] else "bear"
    return bias

htf_bias = get_htf_bias(df, HTF_TF, SESSION_START)

# ─────────────────────────────────────────────
# 3. SESSION BARS
# ─────────────────────────────────────────────
session = df.between_time(SESSION_START, SESSION_END).copy()
session["date"] = session.index.date

# ─────────────────────────────────────────────
# 4. BACKTEST ENGINE
# ─────────────────────────────────────────────
STOP_BUFFER  = STOP_BUFFER_T * TICK_SIZE
TRAIL_DIST   = TRAIL_TICKS   * TICK_SIZE

trades = []

for day, day_df in session.groupby("date"):
    day_df = day_df.copy().reset_index()
    if len(day_df) < 3:
        continue

    bias = htf_bias.get(day)
    if bias is None:
        continue

    # opening candle
    oc        = day_df.iloc[0]
    oc_high   = oc["high"]
    oc_low    = oc["low"]
    oc_size   = oc_high - oc_low
    oc_bull   = oc["close"] > oc["open"]

    if oc_size == 0:
        continue

    cutoff = pd.Timestamp(f"{day} {CUTOFF_TIME}", tz="America/New_York")

    # direction: long if open candle bearish + HTF bearish, short if bullish + HTF bullish
    take_long  = (not oc_bull) and (bias == "bear")
    take_short = oc_bull       and (bias == "bull")

    trades_today    = 0
    stored_bull_fvg = None
    stored_bear_fvg = None
    bull_fvg_active = False
    bear_fvg_active = False

    for i in range(1, len(day_df)):
        if trades_today >= MAX_TRADES_DAY:
            break
        row = day_df.iloc[i]
        if row["Datetime"] > cutoff:
            break

        bar_open  = row["open"]
        bar_high  = row["high"]
        bar_low   = row["low"]
        bar_close = row["close"]
        bar_size  = bar_high - bar_low

        # update FVG zones
        if i >= 2:
            prev2 = day_df.iloc[i-2]
            if prev2["high"] < bar_low:                      # bullish FVG (gap up)
                stored_bull_fvg = (bar_low, prev2["high"])
                bull_fvg_active = True
            if prev2["low"] > bar_high:                      # bearish FVG (gap down)
                stored_bear_fvg = (prev2["low"], bar_high)
                bear_fvg_active = True

        # IFVG detection
        bull_ifvg = False
        bear_ifvg = False

        if bear_fvg_active and stored_bear_fvg:
            top, bot = stored_bear_fvg
            if bot <= bar_close <= top and bar_close > bar_open:
                bull_ifvg       = True
                bear_fvg_active = False

        if bull_fvg_active and stored_bull_fvg:
            top, bot = stored_bull_fvg
            if bot <= bar_close <= top and bar_close < bar_open:
                bear_ifvg       = True
                bull_fvg_active = False

        # 50% reversal candle
        threshold = oc_size * REVERSAL_PCT
        bull_rev  = (bar_close > bar_open) and (bar_size >= threshold)
        bear_rev  = (bar_close < bar_open) and (bar_size >= threshold)

        long_signal  = take_long  and (bull_ifvg or bull_rev)
        short_signal = take_short and (bear_ifvg or bear_rev)

        if not long_signal and not short_signal:
            continue

        # entry levels
        if long_signal:
            entry     = bar_close
            sl        = bar_low  - STOP_BUFFER
            risk      = entry - sl
            tp        = entry + risk * TP_RR
            direction = "long"
        else:
            entry     = bar_close
            sl        = bar_high + STOP_BUFFER
            risk      = sl - entry
            tp        = entry - risk * TP_RR
            direction = "short"

        if risk <= 0:
            continue

        be_level    = entry + risk * BE_TRIGGER_RR if direction == "long" else entry - risk * BE_TRIGGER_RR
        be_hit      = False
        current_sl  = sl
        trail_high  = entry if direction == "long" else entry   # tracks best price for trail

        # simulate bar by bar with BE + trailing
        outcome    = None
        exit_price = None
        exit_time  = None

        remaining = day_df.iloc[i+1:].iterrows()

        for _, fut in remaining:
            fut_high  = fut["high"]
            fut_low   = fut["low"]
            fut_close = fut["close"]

            if direction == "long":
                # update trailing stop
                if USE_TRAIL and fut_high > trail_high:
                    trail_high  = fut_high
                    trail_sl    = trail_high - TRAIL_DIST
                    current_sl  = max(current_sl, trail_sl)

                # move to break even
                if USE_BE and not be_hit and fut_high >= be_level:
                    current_sl = max(current_sl, entry)
                    be_hit     = True

                # check stop
                if fut_low <= current_sl:
                    exit_price = current_sl
                    exit_time  = fut["Datetime"]
                    outcome    = "win" if current_sl >= entry else "loss"
                    break

                # check TP
                if fut_high >= tp:
                    exit_price = tp
                    exit_time  = fut["Datetime"]
                    outcome    = "win"
                    break

            else:  # short
                if USE_TRAIL and fut_low < trail_high:
                    trail_high  = fut_low
                    trail_sl    = trail_high + TRAIL_DIST
                    current_sl  = min(current_sl, trail_sl)

                if USE_BE and not be_hit and fut_low <= be_level:
                    current_sl = min(current_sl, entry)
                    be_hit     = True

                if fut_high >= current_sl:
                    exit_price = current_sl
                    exit_time  = fut["Datetime"]
                    outcome    = "win" if current_sl <= entry else "loss"
                    break

                if fut_low <= tp:
                    exit_price = tp
                    exit_time  = fut["Datetime"]
                    outcome    = "win"
                    break

        # EOD close if no exit
        if outcome is None:
            eod        = day_df.iloc[-1]["close"]
            exit_price = eod
            exit_time  = day_df.iloc[-1]["Datetime"]
            if direction == "long":
                outcome = "win" if eod > entry else "loss"
            else:
                outcome = "win" if eod < entry else "loss"

        # P&L
        ticks = (exit_price - entry) / TICK_SIZE
        if direction == "short":
            ticks = -ticks
        pnl = ticks * TICK_VALUE * CONTRACTS

        trades.append({
            "date":       str(day),
            "entry_time": row["Datetime"],
            "exit_time":  exit_time,
            "direction":  direction,
            "bias":       bias,
            "signal":     "ifvg" if (bull_ifvg or bear_ifvg) else "50pct",
            "entry":      round(entry, 2),
            "sl":         round(sl, 2),
            "tp":         round(tp, 2),
            "exit_price": round(exit_price, 2),
            "be_hit":     be_hit,
            "outcome":    outcome,
            "pnl":        round(pnl, 2),
        })
        trades_today += 1

# ─────────────────────────────────────────────
# 5. RESULTS
# ─────────────────────────────────────────────
results = pd.DataFrame(trades)

if results.empty:
    print("No trades found — check session times or data availability.")
else:
    results["cumulative_pnl"] = results["pnl"].cumsum() + ACCOUNT_SIZE
    results["drawdown"]       = results["cumulative_pnl"].cummax() - results["cumulative_pnl"]

    total_trades  = len(results)
    wins          = (results["outcome"] == "win").sum()
    losses        = (results["outcome"] == "loss").sum()
    win_rate      = wins / total_trades * 100
    net_pnl       = results["pnl"].sum()
    max_dd        = results["drawdown"].max()
    avg_win       = results[results["outcome"]=="win"]["pnl"].mean()
    avg_loss      = results[results["outcome"]=="loss"]["pnl"].mean()
    be_saves      = results["be_hit"].sum()
    gross_win     = results[results["pnl"]>0]["pnl"].sum()
    gross_loss    = abs(results[results["pnl"]<0]["pnl"].sum())
    profit_factor = gross_win / gross_loss if gross_loss > 0 else float("inf")

    print("\n" + "═"*52)
    print("  MARKET OPEN INVERSION / IFVG — BACKTEST")
    print("═"*52)
    print(f"  Period          {START} → {END}")
    print(f"  Symbol          {SYMBOL}")
    print(f"  Account Size    ${ACCOUNT_SIZE:,.0f}")
    print(f"  Contracts       {CONTRACTS}")
    print(f"  Break Even      {'ON' if USE_BE else 'OFF'}  |  Trailing  {'ON' if USE_TRAIL else 'OFF'}")
    print("─"*52)
    print(f"  Total Trades    {total_trades}")
    print(f"  Wins            {wins}")
    print(f"  Losses          {losses}")
    print(f"  Win Rate        {win_rate:.1f}%")
    print(f"  BE Saves        {int(be_saves)}")
    print("─"*52)
    print(f"  Net P&L         ${net_pnl:,.0f}")
    print(f"  Return          {net_pnl/ACCOUNT_SIZE*100:.1f}%")
    print(f"  Max Drawdown    ${max_dd:,.0f}  ({max_dd/ACCOUNT_SIZE*100:.1f}%)")
    print(f"  Avg Win         ${avg_win:,.0f}")
    print(f"  Avg Loss        ${avg_loss:,.0f}")
    print(f"  Profit Factor   {profit_factor:.2f}")
    print("═"*52)

    print("\n  BY SIGNAL TYPE")
    print("─"*52)
    for sig, grp in results.groupby("signal"):
        wr  = (grp["outcome"]=="win").mean() * 100
        pnl = grp["pnl"].sum()
        print(f"  {sig.upper():<10} {len(grp):>3} trades  WR {wr:.0f}%  P&L ${pnl:,.0f}")

    # ─────────────────────────────────────────────
    # 6. CHARTS
    # ─────────────────────────────────────────────
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(14, 10), facecolor="#04040a")
    gs  = gridspec.GridSpec(3, 2, figure=fig, hspace=0.45, wspace=0.3)

    GREEN = "#00e5a0"
    RED   = "#ff4060"
    FAINT = "#30304a"
    MUTED = "#7070a0"

    ax_eq  = fig.add_subplot(gs[0, :])
    ax_dd  = fig.add_subplot(gs[1, 0])
    ax_pnl = fig.add_subplot(gs[1, 1])
    ax_mo  = fig.add_subplot(gs[2, 0])
    ax_wl  = fig.add_subplot(gs[2, 1])

    def style_ax(ax):
        ax.set_facecolor("#090912")
        for spine in ax.spines.values():
            spine.set_color(FAINT)
        ax.tick_params(colors=MUTED, labelsize=8)

    # equity curve
    style_ax(ax_eq)
    ax_eq.plot(results.index, results["cumulative_pnl"], color=GREEN, linewidth=1.5)
    ax_eq.fill_between(results.index, ACCOUNT_SIZE, results["cumulative_pnl"],
                       where=results["cumulative_pnl"] >= ACCOUNT_SIZE, alpha=0.15, color=GREEN)
    ax_eq.fill_between(results.index, ACCOUNT_SIZE, results["cumulative_pnl"],
                       where=results["cumulative_pnl"] < ACCOUNT_SIZE,  alpha=0.15, color=RED)
    ax_eq.axhline(ACCOUNT_SIZE, color=FAINT, linewidth=0.8, linestyle="--")
    ax_eq.set_title("Equity Curve", color="white", fontsize=10, pad=10)
    ax_eq.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x:,.0f}"))

    # drawdown
    style_ax(ax_dd)
    ax_dd.fill_between(results.index, 0, -results["drawdown"], color=RED, alpha=0.6)
    ax_dd.set_title("Drawdown", color="white", fontsize=10, pad=10)
    ax_dd.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x:,.0f}"))

    # per-trade P&L
    style_ax(ax_pnl)
    colors = [GREEN if p > 0 else RED for p in results["pnl"]]
    ax_pnl.bar(results.index, results["pnl"], color=colors, width=0.6)
    ax_pnl.axhline(0, color=FAINT, linewidth=0.8)
    ax_pnl.set_title("Per-Trade P&L", color="white", fontsize=10, pad=10)
    ax_pnl.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x:,.0f}"))

    # monthly
    style_ax(ax_mo)
    results["month"] = pd.to_datetime(results["date"]).dt.to_period("M")
    monthly = results.groupby("month")["pnl"].sum()
    mc = [GREEN if v >= 0 else RED for v in monthly.values]
    ax_mo.bar(range(len(monthly)), monthly.values, color=mc)
    ax_mo.set_xticks(range(len(monthly)))
    ax_mo.set_xticklabels([str(m) for m in monthly.index], rotation=45, fontsize=7)
    ax_mo.axhline(0, color=FAINT, linewidth=0.8)
    ax_mo.set_title("Monthly P&L", color="white", fontsize=10, pad=10)
    ax_mo.yaxis.set_major_formatter(plt.FuncFormatter(lambda x,_: f"${x:,.0f}"))

    # wins vs losses by signal
    style_ax(ax_wl)
    sig_data = results.groupby("signal")["outcome"].value_counts().unstack(fill_value=0)
    x = np.arange(len(sig_data))
    w = 0.35
    ax_wl.bar(x - w/2, sig_data.get("win",  pd.Series([0]*len(sig_data))).values, w, color=GREEN, alpha=0.85, label="Win")
    ax_wl.bar(x + w/2, sig_data.get("loss", pd.Series([0]*len(sig_data))).values, w, color=RED,   alpha=0.85, label="Loss")
    ax_wl.set_xticks(x)
    ax_wl.set_xticklabels([s.upper() for s in sig_data.index], fontsize=9)
    ax_wl.legend(fontsize=8, labelcolor=MUTED)
    ax_wl.set_title("Wins vs Losses by Signal", color="white", fontsize=10, pad=10)

    be_str    = f"BE={'ON' if USE_BE else 'OFF'}  Trail={'ON' if USE_TRAIL else 'OFF'}"
    fig.suptitle(f"MO Inversion / IFVG  ·  {SYMBOL}  ·  {START} → {END}  ·  {be_str}",
                 color="white", fontsize=11, y=0.98)

    plt.savefig("mo_inversion_backtest.png", dpi=150, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.show()
    print("\nChart saved → mo_inversion_backtest.png")