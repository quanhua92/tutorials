#!/usr/bin/env python3
"""
demand_forecasting.py - Demand forecasting system design (GROUND TRUTH).

Pure Python stdlib only. Every number printed below feeds DEMAND_FORECASTING.md
and is recomputed identically in demand_forecasting.html (gold-checked).

Core model: TIME-SERIES DECOMPOSITION + smoothing + accuracy metrics.
  Decomposition : y(t) = Trend(t) + Seasonal(t) + Residual(t)   (additive)
  Trend         : centered moving average CMA(period)
  Seasonal      : average detrended by season position, normalized to sum 0
  Smoothing     : simple moving average SMA(n); Holt's linear exp smoothing
  Forecast      : Holt level+trend recursion; seasonal-naive baseline y(t-7)
  Accuracy      : MAE, RMSE, MAPE, WMAPE  (WMAPE wins on near-zero demand)

Sections:
  1. Synthetic demand series (trend + weekly seasonal + residual)
  2. Time-series decomposition (trend + seasonality + residual)
  3. Moving average smoothing
  4. Seasonal index computation (deseasonalization)
  5. Exponential smoothing forecast (Holt's linear)
  6. Forecast accuracy metrics (MAE, RMSE, MAPE, WMAPE)
  7. Scale estimation (zones, predictions/day, storage, latency)
  8. GOLD values pinned for demand_forecasting.html
"""

import math

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

LINE = "=" * 74


def banner(title):
    print()
    print(LINE)
    print("  " + title)
    print(LINE)


def fmt_int(n):
    return "{:,}".format(n)


def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if abs(n) < 1000.0:
            return "%.2f %s" % (n, unit)
        n /= 1000.0
    return "%.2f EB" % n


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def f4(v):
    return "%.4f" % v


# ---------------------------------------------------------------------------
# deterministic synthetic series (identical in JS gold recompute)
# ---------------------------------------------------------------------------
N = 56                 # 8 weeks of daily data
PERIOD = 7             # weekly seasonality
TREND_BASE = 100.0
TREND_SLOPE = 2.0      # +2 units / day  (strong, learnable trend)
# weekly seasonal profile Mon..Sun, additive, sums to 0
SEASONAL_TRUE = [-10.0, 0.0, 5.0, 0.0, 15.0, 30.0, -40.0]
# fixed residual ("noise"), 56 values -- deterministic so py == JS exactly
RESID_TRUE = [
     2, -3,  4,  0, -1,  5, -4,
     1,  3, -2,  4, -5,  6, -1,
    -2,  4,  1, -3,  5, -4,  2,
     3, -1,  4, -2,  1,  5, -3,
     0,  2, -4,  3, -1,  4, -2,
    -3,  5,  1, -4,  2, -1,  3,
     4, -2,  0,  3, -5,  1, -3,
     2, -4,  5, -1,  3, -2,  4,
]
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def gen_series():
    y = []
    for t in range(N):
        trend = TREND_BASE + TREND_SLOPE * t
        seas = SEASONAL_TRUE[t % PERIOD]
        y.append(trend + seas + RESID_TRUE[t])
    return y


# ---------------------------------------------------------------------------
# decomposition primitives
# ---------------------------------------------------------------------------

def centered_ma(y, period):
    """Centered moving average -- odd period only (period//2 on each side)."""
    half = period // 2
    n = len(y)
    out = [None] * n
    for t in range(half, n - half):
        out[t] = mean(y[t - half:t + half + 1])
    return out


def seasonal_indices(y, trend, period):
    """Additive seasonal indices: detrend, average per season position, normalize."""
    n = len(y)
    sums = [0.0] * period
    counts = [0] * period
    for t in range(n):
        if trend[t] is not None:
            p = t % period
            sums[p] += y[t] - trend[t]
            counts[p] += 1
    idx = [sums[p] / counts[p] if counts[p] else 0.0 for p in range(period)]
    adj = mean(idx)               # enforce sum == 0 for an additive model
    return [v - adj for v in idx]


def decompose(y, period):
    trend = centered_ma(y, period)
    seas = seasonal_indices(y, trend, period)
    resid = [None] * len(y)
    for t in range(len(y)):
        if trend[t] is not None:
            resid[t] = y[t] - trend[t] - seas[t % period]
    return trend, seas, resid


def sma(y, n):
    """Simple (trailing) moving average of window n."""
    out = [None] * len(y)
    acc = 0.0
    for t in range(len(y)):
        acc += y[t]
        if t >= n:
            acc -= y[t - n]
        if t >= n - 1:
            out[t] = acc / n
    return out


def holt_linear(y, alpha, beta, h):
    """Holt's linear smoothing: level + trend. Returns (fitted, forecast, L, B)."""
    n = len(y)
    level = y[0]
    trend = y[1] - y[0]
    fitted = [0.0] * n
    fitted[0] = y[0]
    for t in range(1, n):
        fitted[t] = level + trend          # 1-step forecast for y[t]
        last = level
        level = alpha * y[t] + (1.0 - alpha) * (level + trend)
        trend = beta * (level - last) + (1.0 - beta) * trend
    forecast = [level + (i + 1) * trend for i in range(h)]
    return fitted, forecast, level, trend


def metrics(actual, forecast):
    n = len(actual)
    err = [actual[i] - forecast[i] for i in range(n)]
    mae = mean([abs(e) for e in err])
    rmse = math.sqrt(mean([e * e for e in err]))
    mape = mean([abs(err[i]) / abs(actual[i])
                 for i in range(n) if actual[i] != 0]) * 100.0
    wmape = sum(abs(e) for e in err) / sum(abs(a) for a in actual) * 100.0
    return {"MAE": mae, "RMSE": rmse, "MAPE": mape, "WMAPE": wmape}


# ===========================================================================
# SECTION 1 - Synthetic demand series
# ===========================================================================

def section_series():
    banner("SECTION 1: Synthetic demand series (trend + weekly seasonal + residual)")
    print("We build a DETERMINISTIC daily-demand series so every downstream number")
    print("reproduces in JS. The data-generating process is additive:")
    print("  y(t) = Trend(t) + Seasonal(t) + Residual(t)")
    print("  Trend(t)     = %.0f + %.0f * t   (linear, +2/day)" %
          (TREND_BASE, TREND_SLOPE))
    print("  Seasonal(t)  = weekly profile indexed by day-of-week (sums to 0)")
    print("  Residual(t)  = fixed noise array (no RNG -> py == JS bit-for-bit)")
    print()
    print("  true weekly seasonal profile (Mon..Sun):")
    for p in range(PERIOD):
        print("    %-3s  %+5.1f" % (DOW[p], SEASONAL_TRUE[p]))
    print("  sum(seasonal) = %.1f  (additive -> must sum to 0)" %
          sum(SEASONAL_TRUE))
    print()

    y = gen_series()
    print("  first 14 days (2 weeks):")
    print("    %-4s %-4s %8s %8s %7s %8s" % ("t", "dow", "trend", "season", "resid", "y"))
    for t in range(14):
        print("    %-4d %-4s %8.1f %8.1f %7.0f %8.1f" % (
            t, DOW[t % PERIOD],
            TREND_BASE + TREND_SLOPE * t, SEASONAL_TRUE[t % PERIOD],
            RESID_TRUE[t], y[t]))
    print()
    print("  key points: y[0]=%.1f (Mon open), y[5]=%.1f (Sat peak wk0), "
          "y[6]=%.1f (Sun trough), y[55]=%.1f (last Sun)" %
          (y[0], y[5], y[6], y[55]))
    print()

    ok = (abs(y[0] - 92.0) < 1e-9 and abs(y[5] - 145.0) < 1e-9 and
          abs(y[6] - 68.0) < 1e-9 and abs(y[55] - 174.0) < 1e-9 and
          abs(sum(SEASONAL_TRUE)) < 1e-9)
    print("[check] y[0]=92, y[5]=145, y[6]=68, y[55]=174, seasonal sums to 0? " +
          ("OK" if ok else "FAIL"))
    return y


# ===========================================================================
# SECTION 2 - Time-series decomposition
# ===========================================================================

def section_decompose(y):
    banner("SECTION 2: Time-series decomposition (trend + seasonality + residual)")
    print("Classical additive decomposition recovers the three components from y:")
    print("  1. Trend(t)      = centered moving average CMA(%d) -- smooths out the"
          % PERIOD)
    print("                     seasonal cycle (one full week averages to 0).")
    print("  2. Seasonal(p)   = mean(y - trend) for each day-of-week p, then")
    print("                     re-centered so the 7 indices sum to 0.")
    print("  3. Residual(t)   = y(t) - trend(t) - seasonal(t% d)." % PERIOD)
    print()

    trend, seas, resid = decompose(y, PERIOD)
    print("  recovered seasonal indices vs TRUE (should match closely):")
    print("    %-4s %8s %8s" % ("dow", "est", "true"))
    for p in range(PERIOD):
        print("    %-4s %8.2f %8.2f" % (DOW[p], seas[p], SEASONAL_TRUE[p]))
    print("    sum(est) = %.4f" % sum(seas))
    print()

    print("  decomposition at sample points (t in valid CMA range [3, 52]):")
    print("    %-4s %-4s %8s %8s %8s %8s %8s" %
          ("t", "dow", "y", "trend", "seas", "resid", "check"))
    for t in [3, 5, 6, 10, 20, 30, 40, 50, 52]:
        recon = trend[t] + seas[t % PERIOD] + resid[t]
        print("    %-4d %-4s %8.1f %8.2f %8.2f %8.2f %8.2f" % (
            t, DOW[t % PERIOD], y[t], trend[t], seas[t % PERIOD],
            resid[t], recon))
    print("  'check' = trend + seas + resid; equals y exactly (residual absorbs diff).")
    print()

    max_se = max(abs(seas[p] - SEASONAL_TRUE[p]) for p in range(PERIOD))
    print("  max |est - true| seasonal = %.3f  (CMA smoothing + residual averaging)"
          % max_se)
    print()

    ok = (abs(sum(seas)) < 1e-9 and max_se < 2.5 and
          abs((trend[10] + seas[10 % PERIOD] + resid[10]) - y[10]) < 1e-9)
    print("[check] seasonal sums to 0, est within 2.5 of true, residual reconciles? " +
          ("OK" if ok else "FAIL"))
    return trend, seas, resid


# ===========================================================================
# SECTION 3 - Moving average smoothing
# ===========================================================================

def section_ma(y):
    banner("SECTION 3: Moving average smoothing")
    print("A moving average is the simplest smoother / short-horizon forecaster:")
    print("  SMA(n)[t] = mean(y[t-n+1 .. t])   (trailing, asymmetric -> LAGS)")
    print("  CMA(n)[t] = mean(y[t-n/2 .. t+n/2]) (centered -> no lag, but cannot")
    print("              forecast forward; used to extract trend in decomposition).")
    print()
    print("  Larger n => smoother but more lag. SMA(%d) = one full week, so it"
          % PERIOD)
    print("  cancels weekly seasonality and tracks the trend.")
    print()

    s7 = sma(y, 7)
    s14 = sma(y, 14)
    print("    %-4s %8s %10s %10s" % ("t", "y", "SMA(7)", "SMA(14)"))
    for t in [6, 7, 13, 14, 20, 27, 34, 41, 48, 55]:
        print("    %-4d %8.1f %10s %10s" % (
            t, y[t],
            "%.2f" % s7[t] if s7[t] is not None else "-",
            "%.2f" % s14[t] if s14[t] is not None else "-"))
    print()
    print("  SMA(7)[6] = mean(y[0..6]) = %.4f  -- the first full-week average."
          % s7[6])
    print("  Because SMA(7) averages exactly one week, the seasonal swing cancels")
    print("  and the result tracks the trend -- but it LAGS (a trailing window")
    print("  reports the level of ~3.5 days ago, not today).")
    print()

    ok = (abs(s7[6] - mean(y[0:7])) < 1e-9 and s14[13] is not None and
          abs(s7[55] - mean(y[49:56])) < 1e-9)
    print("[check] SMA(7)[6]=mean(y0..6), SMA(7)[55]=mean(y49..55)? " +
          ("OK" if ok else "FAIL"))
    return s7


# ===========================================================================
# SECTION 4 - Seasonal index computation
# ===========================================================================

def section_seasonal(y, trend):
    banner("SECTION 4: Seasonal index computation (deseasonalization)")
    print("The seasonal index quantifies the typical swing of each season slot.")
    print("Two equivalent normalizations:")
    print("  Additive (this system): index_p = mean(detrended at slot p), sum=0")
    print("                           deseasonalized y* = y - index_{dow}")
    print("  Multiplicative (ratio) : ratio_p = y / CMA, index_p = mean(ratio_p),")
    print("                           product=1; y* = y / index_{dow}")
    print()
    print("Deseasonalizing strips the repeating weekly shape so a trend model sees")
    print("a clean signal -- the core of SARIMA / Prophet / Holt-Winters pipelines.")
    print()

    seas = seasonal_indices(y, trend, PERIOD)
    y_ds = [y[t] - seas[t % PERIOD] for t in range(N)]
    print("  %-4s %8s %12s %12s %12s" %
          ("dow", "index", "raw range", "deseason", "index*"))
    for p in range(PERIOD):
        raw = [y[t] for t in range(p, N, PERIOD)]
        ds = [y_ds[t] for t in range(p, N, PERIOD)]
        print("    %-4s %+8.2f  [%6.1f,%6.1f]  [%6.1f,%6.1f]  %+8.2f" % (
            DOW[p], seas[p], min(raw), max(raw), min(ds), max(ds),
            seas[p]))
    print("  sum(index) = %.4f" % sum(seas))
    print()
    print("  Before deseasonalizing, Sun (p=6) raw swings [%.1f, %.1f]; after" %
          (min(y[t] for t in range(6, N, PERIOD)),
           max(y[t] for t in range(6, N, PERIOD))))
    print("  removing the Sun index (%+.2f) the deseasonalized Sun tracks the trend."
          % seas[6])
    print()

    # re-seasonalize a trend-only forecast: forecast = trend_hat + index
    trend_hat = TREND_BASE + TREND_SLOPE * 56      # next-week level estimate
    print("  seasonal-adjusted forecast for next week (trend_hat=%.0f + index):" %
          trend_hat)
    for p in range(PERIOD):
        print("    next %-3s : %.1f" % (DOW[p], trend_hat + seas[p]))
    print()

    ok = (abs(sum(seas)) < 1e-9 and
          abs(seas[5] - 30.0) < 2.5 and abs(seas[6] + 40.0) < 2.5)
    print("[check] indices sum to 0, Sat~+30, Sun~-40 recovered? " +
          ("OK" if ok else "FAIL"))
    return seas


# ===========================================================================
# SECTION 5 - Exponential smoothing forecast (Holt's linear)
# ===========================================================================

HOLT_ALPHA = 0.5
HOLT_BETA = 0.3
TRAIN_END = 49          # train on first 7 weeks, hold out last week


def section_holt(y):
    banner("SECTION 5: Exponential smoothing forecast (Holt's linear)")
    print("Holt's linear method extends simple exp smoothing with an explicit")
    print("trend term -- a lightweight, online-update forecaster (~microseconds):")
    print("  level(t)  = a*y(t) + (1-a)*(level(t-1) + trend(t-1))")
    print("  trend(t)  = b*(level(t)-level(t-1)) + (1-b)*trend(t-1)")
    print("  forecast h steps ahead = level(T) + h*trend(T)")
    print("  alpha=%.2f (level weight), beta=%.2f (trend weight)" %
          (HOLT_ALPHA, HOLT_BETA))
    print("  train on t=[0,%d) (7 weeks), forecast the held-out last week (h=7)."
          % TRAIN_END)
    print()

    train = y[:TRAIN_END]
    fitted, fc, level_end, trend_end = holt_linear(
        train, HOLT_ALPHA, HOLT_BETA, 7)
    print("  end-of-train state: level=%.4f, trend=%.4f" %
          (level_end, trend_end))
    print()
    print("  held-out week: actual vs Holt forecast")
    print("    %-4s %-4s %8s %10s %8s" % ("t", "dow", "actual", "holt_fc", "err"))
    for i in range(7):
        t = TRAIN_END + i
        print("    %-4d %-4s %8.1f %10.2f %8.2f" % (
            t, DOW[t % PERIOD], y[t], fc[i], y[t] - fc[i]))
    print()
    print("  NOTE: the train window ENDS on a Sunday trough (t=%d), so Holt's"
          % (TRAIN_END - 1))
    print("  trend estimate went NEGATIVE (%+.2f) -- it mistakes the weekly dip"
          % trend_end)
    print("  for a downtrend and forecasts a DECLINING line, under-shooting the")
    print("  whole rising week. Holt knows NOTHING about seasonality. Beating it")
    print("  needs a seasonal method (Holt-Winters / SARIMA / Prophet) -- Section 6.")
    print()

    ok = (abs(fitted[1] - y[1]) < 1e-9 and
          abs(level_end - 187.0035) < 0.05 and abs(trend_end + 2.6398) < 0.05 and
          abs(fc[0] - (level_end + trend_end)) < 1e-9)
    print("[check] fitted[1]=y[1], end level~187.0, trend~-2.64, fc[0]=L+B? " +
          ("OK" if ok else "FAIL"))
    return fc, level_end, trend_end


# ===========================================================================
# SECTION 6 - Forecast accuracy metrics
# ===========================================================================

def section_metrics(y, holt_fc):
    banner("SECTION 6: Forecast accuracy metrics (MAE, RMSE, MAPE, WMAPE)")
    print("How good is a forecast? Four complementary metrics on the held-out week:")
    print("  MAE   = mean(|y - yhat|)                 (interpretable, same units)")
    print("  RMSE  = sqrt(mean((y-yhat)^2))           (penalizes large errors)")
    print("  MAPE  = mean(|y-yhat|/|y|) * 100         (%%, but EXPLODES at y~0)")
    print("  WMAPE = sum(|y-yhat|) / sum(|y|) * 100   (volume-weighted, robust to 0)")
    print()
    print("  WMAPE is the production metric for demand: a 3 AM zone with demand 0.1")
    print("  vs forecast 0.2 is 50%% MAPE -- meaningless -- but contributes almost")
    print("  nothing to WMAPE. WMAPE mirrors business impact (total missed units).")
    print()

    actual = y[TRAIN_END:TRAIN_END + 7]
    train = y[:TRAIN_END]

    # method A: Holt linear (from Section 5)
    m_holt = metrics(actual, holt_fc)

    # method B: seasonal naive -- forecast(t) = y(t - 7)
    seas_naive = [train[TRAIN_END - 7 + i] for i in range(7)]
    m_seas = metrics(actual, seas_naive)

    # method C: random-walk naive -- forecast = last observed value
    rw_naive = [train[-1]] * 7
    m_rw = metrics(actual, rw_naive)

    print("    %-20s %8s %8s %8s %8s" %
          ("method", "MAE", "RMSE", "MAPE%", "WMAPE%"))
    rows = [("Holt linear", m_holt), ("seasonal naive (t-7)", m_seas),
            ("random walk (last)", m_rw)]
    for name, m in rows:
        print("    %-20s %8.2f %8.2f %8.2f %8.2f" %
              (name, m["MAE"], m["RMSE"], m["MAPE"], m["WMAPE"]))
    print()
    print("  The seasonal NAIVE baseline (\"tomorrow ~= last week's same day\")")
    print("  often BEATS an unseasonal model like Holt -- a strong sanity floor.")
    print("  Any real model (Prophet/SARIMA/GNN) must clear it before shipping.")
    print()

    ok = (m_holt["WMAPE"] > 0 and m_holt["WMAPE"] < 40 and
          m_holt["RMSE"] >= m_holt["MAE"] and
          m_seas["WMAPE"] < m_rw["WMAPE"])
    print("[check] Holt WMAPE in (0,40), RMSE>=MAE, seasonal-naive beats RW? " +
          ("OK" if ok else "FAIL"))
    return {"holt": m_holt, "seasonal_naive": m_seas, "random_walk": m_rw}


# ===========================================================================
# SECTION 7 - Scale estimation
# ===========================================================================

def section_scale():
    banner("SECTION 7: Scale estimation")
    zones_per_city = 5000
    cities = 50
    buckets_per_day = 288              # 5-min buckets
    requests_per_city_day = 1_000_000
    bytes_per_zone_day = 10_000        # ~10 KB time-series row set per zone/day

    zones_global = zones_per_city * cities
    preds_day = zones_global * buckets_per_day
    requests_day = requests_per_city_day * cities
    storage_day = zones_global * bytes_per_zone_day
    storage_year = storage_day * 365

    print("Assumptions:")
    print("  zones / major city        = %s   (H3 res-8 ~0.74 km^2)" %
          fmt_int(zones_per_city))
    print("  cities                    = %s" % fmt_int(cities))
    print("  forecast buckets / day     = %d   (5-min interval)" % buckets_per_day)
    print("  ride requests / city / day = %s" % fmt_int(requests_per_city_day))
    print("  bytes / zone / day         = %s   (demand time-series)" %
          fmt_int(bytes_per_zone_day))
    print()

    print("Throughput:")
    print("  zones globally             = %s" % fmt_int(zones_global))
    print("  predictions / day          = %s   (~72M)" % fmt_int(preds_day))
    print("  ride requests / day        = %s" % fmt_int(requests_day))
    print()

    print("Storage:")
    print("  demand time-series / day   = %s" % fmt_bytes(storage_day))
    print("  demand time-series / year  = %s   (~900 GB, archive S3/Parquet)" %
          fmt_bytes(storage_year))
    print()

    print("Latency budget (full-city forecast refresh every 5 min):")
    print("  feature fetch (Feast)      < 500 ms")
    print("  GNN batched inference      < 3000 ms   (5K zones / GPU batch)")
    print("  ensemble + quantile heads   < 500 ms")
    print("  write forecasts to Redis    < 500 ms")
    print("  total refresh               < 5000 ms   (5-min cycle)")
    print()

    ok = (zones_global == 250_000 and preds_day == 72_000_000 and
          abs(storage_year / 1e9 - 912.5) < 0.1)
    print("[check] 250K zones, 72M preds/day, ~912.5 GB/year storage? " +
          ("OK" if ok else "FAIL"))


# ===========================================================================
# SECTION 8 - GOLD values pinned for demand_forecasting.html
# ===========================================================================

def section_gold(y, seas, resid, holt_fc, level_end, trend_end, mtab):
    banner("SECTION 8: GOLD values (pinned for demand_forecasting.html)")

    trend, seas2, _ = decompose(y, PERIOD)
    s7 = sma(y, 7)

    gold = [
        ("series_len", N),
        ("period", PERIOD),
        ("y0", y[0]),
        ("y5", y[5]),
        ("y6", y[6]),
        ("y55", y[55]),
        ("seasonal_true_sum", round(sum(SEASONAL_TRUE), 4)),
        ("cma_at_10", round(trend[10], 4)),
        ("cma_at_30", round(trend[30], 4)),
        ("cma_at_52", round(trend[52], 4)),
        ("seas_est_mon", round(seas[0], 4)),
        ("seas_est_tue", round(seas[1], 4)),
        ("seas_est_wed", round(seas[2], 4)),
        ("seas_est_thu", round(seas[3], 4)),
        ("seas_est_fri", round(seas[4], 4)),
        ("seas_est_sat", round(seas[5], 4)),
        ("seas_est_sun", round(seas[6], 4)),
        ("seas_est_sum", round(sum(seas), 4)),
        ("resid_at_10", round(resid[10], 4)),
        ("sma7_at_6", round(s7[6], 4)),
        ("sma7_at_55", round(s7[55], 4)),
        ("holt_alpha", HOLT_ALPHA),
        ("holt_beta", HOLT_BETA),
        ("holt_level_end", round(level_end, 4)),
        ("holt_trend_end", round(trend_end, 4)),
        ("holt_fc_h1", round(holt_fc[0], 4)),
        ("holt_fc_h2", round(holt_fc[1], 4)),
        ("holt_fc_h7", round(holt_fc[6], 4)),
        ("holt_mae", round(mtab["holt"]["MAE"], 4)),
        ("holt_rmse", round(mtab["holt"]["RMSE"], 4)),
        ("holt_mape", round(mtab["holt"]["MAPE"], 4)),
        ("holt_wmape", round(mtab["holt"]["WMAPE"], 4)),
        ("seasnaive_wmape", round(mtab["seasonal_naive"]["WMAPE"], 4)),
        ("rw_wmape", round(mtab["random_walk"]["WMAPE"], 4)),
        ("scale_zones", 5000 * 50),
        ("scale_preds_day", 250000 * 288),
        ("scale_storage_year_gb", round(250000 * 10000 * 365 / 1e9, 2)),
    ]
    for k, v in gold:
        print("  %-24s = %s" % (k, v))
    print()

    ok = (y[0] == 92.0 and y[5] == 145.0 and abs(sum(seas)) < 1e-9 and
          abs(seas[5] - 30.0) < 2.5 and
          abs(holt_fc[0] - (level_end + trend_end)) < 1e-9 and
          abs(level_end - 187.0035) < 0.05 and
          250000 * 288 == 72_000_000)
    print("[check] GOLD reproduces from series + decomposition + Holt + metrics? " +
          ("OK" if ok else "FAIL"))


# ---------------------------------------------------------------------------

def main():
    print("# demand_forecasting.py - Demand forecasting system simulation")
    print("# Pure Python stdlib only. Numbers below feed DEMAND_FORECASTING.md")
    print("# and demand_forecasting.html (gold-checked).")

    y = section_series()
    trend, seas, resid = section_decompose(y)
    section_ma(y)
    section_seasonal(y, trend)
    holt_fc, level_end, trend_end = section_holt(y)
    mtab = section_metrics(y, holt_fc)
    section_scale()
    section_gold(y, seas, resid, holt_fc, level_end, trend_end, mtab)
    print()
    print(LINE)
    print("  ALL SECTIONS COMPLETE")
    print(LINE)


if __name__ == "__main__":
    main()
