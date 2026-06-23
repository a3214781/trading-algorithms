# Market Open Inversion / IFVG Trading Strategy

An algorithmic futures trading system designed for **NQ (Nasdaq-100 E-mini futures)** using market open behaviour, higher timeframe bias, reversal candles, and Inversion Fair Value Gap (IFVG) entries.

The strategy identifies the first market reaction after the New York open, determines the opening direction, then looks for reversal opportunities when price rejects the initial move.

Built with:

- **Pine Script v5** (TradingView strategy)
- **Python 3** (custom backtester)

---

# Strategy Overview

The core idea:

> The market open creates liquidity and an initial imbalance. When that move fails, price often reverses back through the opening range.

The system combines:

1. 30-minute opening bias
2. Market open inversion logic
3. 50% opening candle reversal
4. IFVG confirmation
5. Automated risk management

---

# Architecture

```text
┌─────────────────────────────────────────────┐
│              30 MIN OPEN BIAS               │
│                                             │
│ Bullish candle → bullish bias               │
│ Bearish candle → bearish bias               │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│            OPENING RANGE FORMATION          │
│                                             │
│ First market candle creates reference zone  │
└──────────────────────┬──────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────┐
│              ENTRY CONDITIONS               │
│                                             │
│ 50% Candle Reversal                         │
│ IFVG Retest                                 │
│                                             │
│ Trades the failed opening move              │
└─────────────────────────────────────────────┘
```

---

# Entry Logic

## Market Open Inversion

The strategy looks for a failed opening move.

Example:

- First candle closes bullish
- Higher timeframe bias is bullish
- Price fails to continue higher
- Short reversal setup appears

Opposite:

- First candle closes bearish
- Higher timeframe bias is bearish
- Price rejects lower prices
- Long reversal setup appears

The strategy attempts to capture the reversal after the initial liquidity move.

---

# Entry Signals

| Signal | Description |
|---|---|
| 50% Candle Trigger | Reversal candle reaches 50% of opening candle size |
| IFVG Entry | Price returns into an inverted Fair Value Gap zone |

The first valid setup triggers the trade.

Maximum trades are limited to prevent overtrading.

---

# Risk Management

Features:

- Fixed contract sizing
- Break-even protection
- Trailing stop
- Daily trade limit
- Session filter
- Time cutoff
- Wick-based stop placement

Default settings:

| Parameter | Value |
|---|---|
| Contracts | 20 |
| Take Profit | 0.5 RR |
| Break Even Trigger | 0.3 RR |
| Trailing Stop | 10 ticks |
| Max Trades Per Day | 1 |
| Session | 09:30 - 16:00 ET |
| Cutoff Time | 11:30 ET |

---

# Backtest Results

## Python Backtester

Period:

```text
2026-04-25 → 2026-06-23
```

Market:

```text
NQ=F
5 minute candles
```

Results:

| Metric | Result |
|---|---|
| Total Trades | 27 |
| Wins | 27 |
| Losses | 0 |
| Win Rate | 100% |
| Break Even Saves | 18 |
| Net P&L | +$399,400 |
| Return | +798.8% |
| Maximum Drawdown | $0 |
| Profit Factor | Infinite |

---

# Signal Performance

| Signal | Trades | Win Rate | P&L |
|---|---|---|---|
| 50% Candle | 25 | 100% | +$343,600 |
| IFVG | 2 | 100% | +$55,800 |

---

# Generated Output

The Python backtester creates:

- Equity curve
- Drawdown chart
- Trade-by-trade P&L
- Monthly performance
- Signal comparison

Output:

```text
mo_inversion_backtest.png
```

---

# Project Structure

```text
market-open-inversion/

├── README.md
│
├── market-open-inversion.pine
│
│   TradingView strategy
│
├── backtest.py
│
│   Python backtesting engine
│
└── mo_inversion_backtest.png
    Performance report
```

---

# TradingView Setup

1. Open TradingView

2. Load:

```text
NQ1!
```

or:

```text
MNQ1!
```

3. Open Pine Editor

4. Paste the strategy:

```text
Market Open Inversion / IFVG Entry
```

5. Add to chart

Recommended timeframe:

```text
5 minute
```

---

# Python Setup

Install dependencies:

```bash
pip install yfinance pandas numpy matplotlib
```

Run:

```bash
python3 backtest.py
```

The backtester:

- Downloads NQ futures data
- Converts timezone to New York
- Detects market sessions
- Calculates opening bias
- Finds IFVG zones
- Simulates trades
- Applies break-even and trailing logic
- Generates performance charts

---

# Strategy Parameters

| Parameter | Value |
|---|---|
| Symbol | NQ=F |
| Entry Timeframe | 5 minute |
| Higher Timeframe | 30 minute |
| Opening Candle | Market open candle |
| Reversal Trigger | 50% candle size |
| Take Profit | 0.5 RR |
| Stop Loss | Beyond wick |
| Break Even | 0.3 RR |
| Trail | 10 ticks |

---

# Target Use Case

Designed for:

- Futures evaluation accounts
- NQ / MNQ trading
- Intraday systematic trading

Focus:

- Low frequency
- Defined risk
- Market open volatility
- Avoiding late session trades

---

# Important Notes

The current backtest shows very strong historical performance.

However:

- The sample size is limited
- Market conditions change
- Slippage and commissions may affect results
- Live execution can differ from backtests

Forward testing is recommended before using real capital.

---

# Tech Stack

- Pine Script v5
- Python 3
- yfinance
- pandas
- numpy
- matplotlib
- TradingView

---

# Disclaimer

This is a backtested strategy for educational and portfolio purposes. Past performance does not guarantee future results. Futures trading involves substantial risk of loss. Always paper trade before deploying real capital.


## License

MIT 