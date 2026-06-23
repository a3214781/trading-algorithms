# Multi-Timeframe Trading Strategy

An algorithmic trading system for **MNQ (Micro E-mini NASDAQ-100) futures** designed to pass prop firm evaluation accounts. Uses three-timeframe alignment to filter trades directionally, then executes entries only when Daily, 1-Hour, and 5-Minute charts all agree.

Built in **Pine Script v5** (TradingView) and **Python 3** (backtester).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    DAILY TIMEFRAME                      │
│         Close vs 10-day SMA → LONG or SHORT bias        │
└──────────────────────┬──────────────────────────────────┘
                       │ must agree
┌──────────────────────▼──────────────────────────────────┐
│                   1-HOUR TIMEFRAME                      │
│      9/21 EMA momentum → BULLISH, BEARISH, or FLAT     │
└──────────────────────┬──────────────────────────────────┘
                       │ must agree
┌──────────────────────▼──────────────────────────────────┐
│                  5-MINUTE TIMEFRAME                     │
│              Entry triggers (bias direction only)       │
│                                                         │
│   ┌─────────┐  ┌──────────┐  ┌───────┐  ┌──────────┐  │
│   │   ORB   │  │ VWAP     │  │ EMA   │  │ Prev Day │  │
│   │Breakout │  │ Pullback │  │ Touch │  │ H/L Break│  │
│   └─────────┘  └──────────┘  └───────┘  └──────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Core rule:** all three timeframes must agree on direction before any trade is taken. If the Daily says LONG but the 1H momentum is bearish or flat, no trades fire. This single filter eliminates most whipsaw losses.

## Entry Strategies

| Strategy | Signal | Stop | Target | Notes |
|---|---|---|---|---|
| **ORB Breakout** | Price breaks 1-min opening range in bias direction | 80 pts | 152 pts (1.9 RR) | Fires first, highest P&L contributor |
| **VWAP Pullback** | Price near VWAP (±15 pts), resumes in bias direction | 65 pts | 97.5 pts (1.5 RR) | Institutional level bounce |
| **EMA Touch** | Price near 21 EMA (±12 pts), moving in bias direction | 45 pts | 45 pts (1.0 RR) | Quick scalp, 78% win rate |
| **Prev Day H/L** | Price breaks yesterday's high (long) or low (short) + 5pt buffer | 50 pts | 75 pts (1.5 RR) | Breakout continuation |

Strategies are checked in priority order (ORB → VWAP → EMA → PDHL). Each has a per-day fire limit to prevent overtrading.

## Backtest Results

**Python backtester** — 5-minute bars, 58 trading days (Apr–Jun 2026):

| Metric | Value |
|---|---|
| Total trades | 21 |
| Win rate | 66.7% |
| Profit factor | 2.43 |
| Net P&L | +$2,473 |
| Expectancy | $117.80 / trade |
| Max drawdown | -$502 |
| Active days | 10 / 49 (20%) |
| Consistency | 26% ✅ (under 50% cap) |
| Avg daily P&L | +$50 |

**Per-strategy breakdown:**

| Strategy | Trades | Win Rate | Net P&L |
|---|---|---|---|
| ORB Breakout | 8 | 62% | +$1,593 |
| EMA Touch | 9 | 78% | +$684 |
| Prev Day H/L | 4 | 50% | +$196 |

For a standard **$1,250 eval target**, the strategy would have passed on **day 3**.

## Risk Management

- **EOD flatten** at 3:50pm ET — no overnight holds
- **MLL guard** — stops trading when approaching maximum loss limit
- **Consistency enforcement** — caps single-day profit at 49% of total (prop firm 50% rule)
- **Daily goal** — stops trading after +$625/day to spread profits across days
- **Max 3 trades/day** — prevents revenge trading
- **Session filter** — no entries before 9:50am or after 3:40pm ET
- **ORB range filter** — skips days with opening ranges under 8 pts (no volatility) or over 160 pts (too risky)

## Project Structure

```
mtf-trading-strategy/
├── README.md
├── mtf-trading-strategy.pine   # Pine Script strategy (TradingView)
├── backtest.py                 # Python backtester
└── mtf_bot_results.png         # Backtest equity curve
```

## Setup

### TradingView (Pine Script)

1. Open TradingView → **MNQ1!** or **NQ1!** on a **5-minute** chart
2. Pine Editor → paste `LucidFlex_MTF_v6.pine` → Add to Chart
3. Open **Strategy Tester** tab to view backtest results
4. All parameters are pre-configured — no manual tuning needed

TradingView provides years of 5-minute data, making it the primary backtesting environment.

### Python Backtester

```bash
pip3 install yfinance pandas numpy matplotlib
python3 backtest.py.py
```

The Python backtester fetches data from Yahoo Finance (free):
- Daily bars — 1 year (trend context)
- 1-hour bars — 730 days (momentum)
- 5-minute bars — 60 days (entries)

Outputs a trade log, daily summary, and equity curve chart.

## How the Multi-Timeframe Alignment Works

### TF1: Daily Trend

Previous day's close is compared against the 10-day Simple Moving Average on the daily chart:

- Close **above** SMA → **LONG** bias for the entire next day
- Close **below** SMA → **SHORT** bias for the entire next day

### TF2: 1-Hour Momentum

On the hourly chart, a 9/21 EMA pair determines session momentum:

- 9 EMA **above** 21 EMA **and rising** → bullish momentum (+1)
- 9 EMA **below** 21 EMA **and falling** → bearish momentum (-1)
- Everything else → flat / choppy (0) → **no trades**

### TF3: 5-Minute Entries

When Daily and 1H agree, the 5-minute chart scans for entry triggers in the agreed direction only. Counter-trend setups are completely ignored, which eliminates roughly half of all losing trades.

## Parameters

All values are hardcoded as defaults in both Pine Script and Python:

| Parameter | Value | Rationale |
|---|---|---|
| Daily SMA | 10 | Captures medium-term trend without lagging |
| 1H EMA Fast/Slow | 9 / 21 | Standard momentum pair |
| ORB Minutes | 1 | First bar range — fires immediately at open |
| ORB Stop / RR | 80 pts / 1.9 | Wide stop survives NQ noise, near-2:1 payoff |
| VWAP Zone | 15 pts | Defines "near VWAP" for pullback detection |
| VWAP Stop / RR | 65 pts / 1.5 | Moderate risk at institutional level |
| EMA Stop / RR | 45 pts / 1.0 | Tight 1:1 scalp — high win rate |
| PDHL Stop / RR | 50 pts / 1.5 | Standard breakout continuation |

## Target Account

Designed and tested for **LucidFlex 25K evaluation accounts** (Lucid Trading):

- $25,000 starting capital
- $1,250 profit target (eval), $3,000 (funded)
- $1,000–$2,000 maximum loss limit (EOD trailing)
- 50% consistency rule — no single day can exceed 50% of total profit
- Max 2 MNQ contracts
- Microscalping rule — trades held >5 seconds
- Platforms: Tradovate / NinjaTrader

## Tech Stack

- **Pine Script v5** — strategy execution and TradingView backtesting
- **Python 3** — backtester with yfinance data, matplotlib charts
- **yfinance** — free market data (Daily, 1H, 5M)
- **TradingView** — charting, multi-year backtesting, alerts

## Disclaimer

This is a backtested strategy for educational and portfolio purposes. Past performance does not guarantee future results. Futures trading involves substantial risk of loss. Always paper trade before deploying real capital.

## License

MIT 