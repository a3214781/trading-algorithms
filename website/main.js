// ─────────────────────────────────────────────
// PINE SCRIPT SOURCE
// ─────────────────────────────────────────────
const PINE = `//@version=5
strategy("Market Open Inversion / IFVG Entry", overlay=true, default_qty_type=strategy.fixed, default_qty_value=20)

// ─────────────────────────────────────────────
// INPUTS — ACCOUNT & RISK
// ─────────────────────────────────────────────
var string GROUP_ACCOUNT = "💰 Account & Risk"
account_size     = input.float(100000.0, "Account Size ($)",          group=GROUP_ACCOUNT, minval=1, step=1000)
risk_mode        = input.string("Fixed Contracts", "Position Sizing Mode", group=GROUP_ACCOUNT, options=["Fixed Contracts", "% Risk Per Trade", "Fixed Dollar Risk"])
contracts        = input.int(20,         "Contracts (Fixed mode)",    group=GROUP_ACCOUNT, minval=1)
risk_pct         = input.float(1.0,      "Risk % Per Trade",          group=GROUP_ACCOUNT, minval=0.01, maxval=100, step=0.1)
risk_dollar      = input.float(500.0,    "Fixed Dollar Risk",         group=GROUP_ACCOUNT, minval=1, step=50)
tick_value       = input.float(0.50,     "Tick Value ($) — MNQ=0.50", group=GROUP_ACCOUNT, minval=0.01, step=0.5)

// ─────────────────────────────────────────────
// INPUTS — SESSION
// ─────────────────────────────────────────────
var string GROUP_SESSION = "🕐 Session"
session_input    = input.session("0930-1700", "Market Session",       group=GROUP_SESSION)
htf              = input.timeframe("30",      "HTF Bias Timeframe",   group=GROUP_SESSION)
open_candle_bars = input.int(1,               "Opening Candle Bars",  group=GROUP_SESSION, minval=1, maxval=5)
max_trades_day   = input.int(1,               "Max Trades Per Day",   group=GROUP_SESSION, minval=1, maxval=10)

// ─────────────────────────────────────────────
// INPUTS — ENTRY
// ─────────────────────────────────────────────
var string GROUP_ENTRY = "📈 Entry Settings"
use_ifvg         = input.bool(true,  "Use IFVG Entry",           group=GROUP_ENTRY)
use_50pct        = input.bool(true,  "Use 50% Candle Entry",     group=GROUP_ENTRY)
pct_trigger      = input.float(50.0, "Reversal % of Open Candle",group=GROUP_ENTRY, minval=1, maxval=100, step=1)
htf_bias_filter  = input.bool(true,  "Use HTF Bias Filter",      group=GROUP_ENTRY)
counter_trend    = input.bool(false, "Counter Trend Mode",       group=GROUP_ENTRY)

// ─────────────────────────────────────────────
// INPUTS — RISK MANAGEMENT
// ─────────────────────────────────────────────
var string GROUP_RISK = "🛡 Risk Management"
stop_buffer      = input.float(2.0,  "Stop Buffer (ticks)",      group=GROUP_RISK, minval=0)
tp_rr            = input.float(0.5,  "Take Profit RR",           group=GROUP_RISK, minval=0.1, step=0.1)
use_be           = input.bool(false, "Move SL to Break Even",    group=GROUP_RISK)
be_trigger_rr    = input.float(0.3,  "Break Even Trigger RR",    group=GROUP_RISK, minval=0.1, step=0.1)
use_trail        = input.bool(false, "Use Trailing Stop",        group=GROUP_RISK)
trail_ticks      = input.int(10,     "Trailing Stop (ticks)",    group=GROUP_RISK, minval=1)

// ─────────────────────────────────────────────
// INPUTS — FILTERS
// ─────────────────────────────────────────────
var string GROUP_FILTER = "🔍 Filters"
min_open_candle_ticks = input.int(5,   "Min Open Candle (ticks)", group=GROUP_FILTER, minval=1)
max_open_candle_ticks = input.int(500, "Max Open Candle (ticks)", group=GROUP_FILTER, minval=1)
time_cutoff      = input.bool(true,    "Stop After Cutoff Time",  group=GROUP_FILTER)
cutoff_hour      = input.int(11,       "Cutoff Hour",             group=GROUP_FILTER, minval=0, maxval=23)
cutoff_min       = input.int(30,       "Cutoff Minute",           group=GROUP_FILTER, minval=0, maxval=59)

// ─────────────────────────────────────────────
// HTF BIAS
// ─────────────────────────────────────────────
htf_open  = request.security(syminfo.tickerid, htf, open,  lookahead=barmerge.lookahead_off)
htf_close = request.security(syminfo.tickerid, htf, close, lookahead=barmerge.lookahead_off)
htf_high  = request.security(syminfo.tickerid, htf, high,  lookahead=barmerge.lookahead_off)
htf_low   = request.security(syminfo.tickerid, htf, low,   lookahead=barmerge.lookahead_off)

var float htf_open_candle_high = na
var float htf_open_candle_low  = na
var bool  htf_bias_bull        = na
var bool  htf_bias_set         = false

htf_session_open = not na(time(timeframe.period, session_input)) and na(time(timeframe.period, session_input)[1])
if htf_session_open
    htf_open_candle_high := htf_high
    htf_open_candle_low  := htf_low
    htf_bias_bull        := htf_close > htf_open
    htf_bias_set         := true

// ─────────────────────────────────────────────
// SESSION & OPENING CANDLE
// ─────────────────────────────────────────────
in_session          = not na(time(timeframe.period, session_input))
session_just_opened = in_session and not in_session[1]
past_cutoff = time_cutoff and (hour > cutoff_hour or (hour == cutoff_hour and minute >= cutoff_min))

var float open_candle_high  = na
var float open_candle_low   = na
var float open_candle_size  = na
var bool  open_candle_bull  = na
var int   bar_count_in_sess = 0
var int   trades_today      = 0
var bool  setup_active      = false

if session_just_opened
    open_candle_high  := na
    open_candle_low   := na
    open_candle_size  := na
    open_candle_bull  := na
    bar_count_in_sess := 0
    trades_today      := 0
    setup_active      := false

if in_session
    bar_count_in_sess += 1

if in_session and bar_count_in_sess == open_candle_bars
    float candle_size_ticks = (high - low) / syminfo.mintick
    if candle_size_ticks >= min_open_candle_ticks and candle_size_ticks <= max_open_candle_ticks
        open_candle_high := high
        open_candle_low  := low
        open_candle_size := high - low
        open_candle_bull := close > open
        setup_active     := true

// ─────────────────────────────────────────────
// POSITION SIZING
// ─────────────────────────────────────────────
f_get_qty(sl_distance) =>
    if risk_mode == "Fixed Contracts"
        contracts
    else if risk_mode == "% Risk Per Trade"
        dollar_risk = account_size * (risk_pct / 100.0)
        sl_ticks    = sl_distance / syminfo.mintick
        qty         = math.floor(dollar_risk / (sl_ticks * tick_value))
        math.max(qty, 1)
    else
        sl_ticks = sl_distance / syminfo.mintick
        qty      = math.floor(risk_dollar / (sl_ticks * tick_value))
        math.max(qty, 1)

// ─────────────────────────────────────────────
// IFVG DETECTION
// ─────────────────────────────────────────────
raw_bull_fvg = high[2] < low[0]
raw_bear_fvg = low[2]  > high[0]

var float stored_bull_fvg_top = na
var float stored_bull_fvg_bot = na
var float stored_bear_fvg_top = na
var float stored_bear_fvg_bot = na
var bool  bull_fvg_active     = false
var bool  bear_fvg_active     = false

if raw_bull_fvg and setup_active
    stored_bull_fvg_top := low[0]
    stored_bull_fvg_bot := high[2]
    bull_fvg_active     := true

if raw_bear_fvg and setup_active
    stored_bear_fvg_top := low[2]
    stored_bear_fvg_bot := high[0]
    bear_fvg_active     := true

bull_ifvg = bear_fvg_active and close >= stored_bear_fvg_bot and close <= stored_bear_fvg_top and close > open
bear_ifvg = bull_fvg_active and close >= stored_bull_fvg_bot and close <= stored_bull_fvg_top and close < open

if bull_ifvg
    bear_fvg_active := false
if bear_ifvg
    bull_fvg_active := false

// ─────────────────────────────────────────────
// 50% CANDLE TRIGGER
// ─────────────────────────────────────────────
current_candle_size  = high - low
pct_threshold        = open_candle_size * (pct_trigger / 100.0)
bull_reversal_candle = (close > open) and (current_candle_size >= pct_threshold)
bear_reversal_candle = (close < open) and (current_candle_size >= pct_threshold)

// ─────────────────────────────────────────────
// ENTRY CONDITIONS
// ─────────────────────────────────────────────
bias_available = not htf_bias_filter or htf_bias_set
take_long  = not htf_bias_filter or (counter_trend ? htf_bias_bull  : not htf_bias_bull)
take_short = not htf_bias_filter or (counter_trend ? not htf_bias_bull : htf_bias_bull)

can_trade = setup_active and in_session and bar_count_in_sess > open_candle_bars and trades_today < max_trades_day and strategy.position_size == 0 and bias_available and not past_cutoff

long_entry  = (can_trade and take_long  and use_ifvg  and bull_ifvg)  or (can_trade and take_long  and use_50pct and bull_reversal_candle)
short_entry = (can_trade and take_short and use_ifvg  and bear_ifvg)  or (can_trade and take_short and use_50pct and bear_reversal_candle)

// ─────────────────────────────────────────────
// EXECUTE
// ─────────────────────────────────────────────
if long_entry
    sl  = low  - (stop_buffer * syminfo.mintick)
    tp  = close + ((close - sl) * tp_rr)
    qty = f_get_qty(close - sl)
    strategy.entry("Long", strategy.long, qty=qty)
    strategy.exit("Long Exit", "Long", stop=sl, limit=tp, trail_points=use_trail ? trail_ticks : na, trail_offset=use_trail ? trail_ticks : na)
    trades_today += 1

if short_entry
    sl  = high + (stop_buffer * syminfo.mintick)
    tp  = close - ((sl - close) * tp_rr)
    qty = f_get_qty(sl - close)
    strategy.entry("Short", strategy.short, qty=qty)
    strategy.exit("Short Exit", "Short", stop=sl, limit=tp, trail_points=use_trail ? trail_ticks : na, trail_offset=use_trail ? trail_ticks : na)
    trades_today += 1

// ─────────────────────────────────────────────
// VISUALS
// ─────────────────────────────────────────────
var box open_box     = na
var box bull_fvg_box = na
var box bear_fvg_box = na

if in_session and bar_count_in_sess == open_candle_bars and setup_active
    box.delete(open_box)
    open_box := box.new(bar_index, open_candle_high, bar_index + 30, open_candle_low,
         border_color=color.new(color.yellow, 0), border_width=2,
         bgcolor=color.new(color.yellow, 88))
    dir_str = open_candle_bull ? "▲ BULL" : "▼ BEAR"
    label.new(bar_index, open_candle_high,
         "Open Candle  " + dir_str + "  " + str.tostring(math.round(open_candle_size / syminfo.mintick, 1)) + " ticks",
         style=label.style_label_down, color=color.new(color.yellow, 20), textcolor=color.black, size=size.small)

if raw_bull_fvg and setup_active
    box.delete(bull_fvg_box)
    bull_fvg_box := box.new(bar_index - 2, stored_bull_fvg_top, bar_index + 10, stored_bull_fvg_bot,
         border_color=color.new(color.lime, 40), border_width=1, bgcolor=color.new(color.lime, 85))

if raw_bear_fvg and setup_active
    box.delete(bear_fvg_box)
    bear_fvg_box := box.new(bar_index - 2, stored_bear_fvg_top, bar_index + 10, stored_bear_fvg_bot,
         border_color=color.new(color.red, 40), border_width=1, bgcolor=color.new(color.red, 85))

if long_entry
    label.new(bar_index, low, "⬆ LONG", style=label.style_label_up, color=color.new(color.lime, 10), textcolor=color.black, size=size.normal)
if short_entry
    label.new(bar_index, high, "⬇ SHORT", style=label.style_label_down, color=color.new(color.red, 10), textcolor=color.white, size=size.normal)

bgcolor(bull_ifvg and setup_active ? color.new(color.lime, 92) : na)
bgcolor(bear_ifvg and setup_active ? color.new(color.red,  92) : na)

plot(setup_active ? open_candle_high : na, "Open High", color=color.new(color.yellow, 40), style=plot.style_linebr, linewidth=1)
plot(setup_active ? open_candle_low  : na, "Open Low",  color=color.new(color.yellow, 40), style=plot.style_linebr, linewidth=1)
plot(htf_bias_set ? htf_open_candle_high : na, "HTF High", color=color.new(color.orange, 50), style=plot.style_linebr, linewidth=1)
plot(htf_bias_set ? htf_open_candle_low  : na, "HTF Low",  color=color.new(color.orange, 50), style=plot.style_linebr, linewidth=1)`;


// ─────────────────────────────────────────────
// SYNTAX HIGHLIGHT + RENDER
// ─────────────────────────────────────────────
function renderCode() {
  const el = document.getElementById('pine-pre');
  if (!el) return;
  let c = PINE
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  c = c.replace(/(\/\/[^\n]*)/g, '<span class="t-cm">$1</span>');
  c = c.replace(/"([^"]*)"/g, '<span class="t-str">"$1"</span>');
  c = c.replace(/\b(var|if|else|and|or|not|true|false|na)\b/g, '<span class="t-kw">$1</span>');
  c = c.replace(/\b(strategy|input|request|ta|math|barmerge|syminfo|color|label|box|plot|bgcolor|high|low|open|close|time|hour|minute|dayofweek|barstate|timeframe|bar_index)\b/g, '<span class="t-fn">$1</span>');
  c = c.replace(/\b(\d+\.?\d*)\b/g, '<span class="t-num">$1</span>');
  el.innerHTML = c;
}


// ─────────────────────────────────────────────
// COPY BUTTON
// ─────────────────────────────────────────────
function initCopyButton() {
  const btn = document.getElementById('copy-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    navigator.clipboard.writeText(PINE).then(() => {
      btn.textContent = '✓ COPIED';
      setTimeout(() => btn.textContent = 'COPY CODE', 2000);
    });
  });
}


// ─────────────────────────────────────────────
// EQUITY CHART
// ─────────────────────────────────────────────
function initChart() {
  const ctx = document.getElementById('eqChart');
  if (!ctx) return;
  const labels = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec','Jan','Feb','Mar','Apr'];
  const data   = [50000,51200,53800,52400,56000,61000,65000,68000,72000,78000,82000,88000,96000,108000,124000,134000];
  new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [{
        data,
        borderColor: '#00e5a0',
        borderWidth: 2,
        pointRadius: 2,
        pointBackgroundColor: '#00e5a0',
        tension: 0.4,
        fill: true,
        backgroundColor: (c) => {
          const g = c.chart.ctx.createLinearGradient(0, 0, 0, 180);
          g.addColorStop(0, 'rgba(0,229,160,0.25)');
          g.addColorStop(1, 'rgba(0,229,160,0)');
          return g;
        }
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          grid: { color: 'rgba(255,255,255,0.03)' },
          ticks: { color: '#30304a', font: { family: 'JetBrains Mono', size: 8 } }
        },
        y: {
          grid: { color: 'rgba(255,255,255,0.03)' },
          ticks: { color: '#30304a', font: { family: 'JetBrains Mono', size: 8 }, callback: v => '$' + (v / 1000).toFixed(0) + 'k' }
        }
      }
    }
  });
}


// ─────────────────────────────────────────────
// INIT — runs only on the detail page
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  renderCode();
  initCopyButton();
  initChart();
});