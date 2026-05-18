"""
analysis.py — 技术分析与决策
─────────────────────────────
合并自旧版三个模块：
  - indicators.py  → 技术指标计算（MACD/BOLL/MA/RSI/KDJ/VWAP/OBV）
  - analysis.py    → 支撑/压力位识别
  - decision.py    → 规则引擎 + 综合决策

对外接口（与旧版完全一致，保持 import 兼容）：
  calc_indicators, get_recent_snapshot              ← 旧 indicators
  find_support_resistance, describe_sr_relation     ← 旧 analysis
  rule_engine, make_final_decision, DecisionResult  ← 旧 decision
"""
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from loguru import logger

try:
    from scipy.signal import argrelextrema
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("scipy 未安装，局部极值法不可用，将使用滑动窗口替代")


# ════════════════════════════════════════════════════════════════
# Part 1：技术指标（原 indicators.py）
# ════════════════════════════════════════════════════════════════

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """主入口：一次性计算所有指标"""
    df = df.copy()
    df = _calc_macd(df)
    df = _calc_bollinger(df)
    df = _calc_ma(df)
    df = _calc_volume_indicators(df)
    df = _calc_rsi(df)
    df = _calc_kdj(df)
    df = _calc_vwap(df)
    return df


def _calc_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = (df["dif"] - df["dea"]) * 2
    return df


def _calc_bollinger(df: pd.DataFrame, window=20, n_std=2) -> pd.DataFrame:
    mid = df["close"].rolling(window).mean()
    std = df["close"].rolling(window).std(ddof=0)
    df["bb_upper"] = mid + n_std * std
    df["bb_mid"]   = mid
    df["bb_lower"] = mid - n_std * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100
    df["bb_pct"]   = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    return df


def _calc_ma(df: pd.DataFrame) -> pd.DataFrame:
    for n in [5, 10, 20, 60]:
        df[f"ma{n}"] = df["close"].rolling(n).mean().round(4)
    return df


def _calc_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df["vol_ma5"]    = df["volume"].rolling(5).mean()
    df["vol_ma20"]   = df["volume"].rolling(20).mean()
    df["vol_ratio"]  = df["volume"] / df["vol_ma5"]

    # OBV（能量潮）
    obv = [0]
    for i in range(1, len(df)):
        if df["close"].iloc[i] > df["close"].iloc[i - 1]:
            obv.append(obv[-1] + df["volume"].iloc[i])
        elif df["close"].iloc[i] < df["close"].iloc[i - 1]:
            obv.append(obv[-1] - df["volume"].iloc[i])
        else:
            obv.append(obv[-1])
    df["obv"] = obv

    if "turnover_rate" in df.columns:
        df["turnover_rate_ma5"] = df["turnover_rate"].rolling(5).mean()
    return df


def _calc_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def _calc_kdj(df: pd.DataFrame, n: int = 9) -> pd.DataFrame:
    low_min  = df["low"].rolling(window=n, min_periods=1).min()
    high_max = df["high"].rolling(window=n, min_periods=1).max()
    denom    = high_max - low_min
    rsv      = np.where(denom > 0, (df["close"] - low_min) / denom * 100, 50.0)
    rsv_s    = pd.Series(rsv, index=df.index)
    K = rsv_s.ewm(alpha=1/3, adjust=False).mean()
    D = K.ewm(alpha=1/3, adjust=False).mean()
    J = 3 * K - 2 * D
    df["kdj_k"] = K.round(2)
    df["kdj_d"] = D.round(2)
    df["kdj_j"] = J.round(2)
    return df


def _calc_vwap(df: pd.DataFrame) -> pd.DataFrame:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["vwap"] = (typical * df["volume"]).cumsum() / df["volume"].cumsum()
    df["vwap"] = df["vwap"].round(2)
    return df


def get_recent_snapshot(df: pd.DataFrame, n: int = 10) -> list[dict]:
    """返回最近 n 根 K 线的关键字段列表，供 AI 消化"""
    cols = [
        "date", "open", "close", "high", "low",
        "volume", "turnover_rate", "change_pct",
        "dif", "dea", "macd_hist",
        "bb_upper", "bb_mid", "bb_lower", "bb_pct",
        "ma5", "ma10", "ma20", "ma60",
        "vol_ratio", "rsi",
        "kdj_k", "kdj_d", "kdj_j",
        "vwap", "obv",
    ]
    available = [c for c in cols if c in df.columns]
    recent = df[available].tail(n).copy()
    recent["date"] = recent["date"].dt.strftime("%Y-%m-%d")

    records = []
    for _, row in recent.iterrows():
        rec = {}
        for k, v in row.items():
            if pd.isna(v):
                rec[k] = None
            elif isinstance(v, float):
                rec[k] = round(v, 4)
            else:
                rec[k] = v
        records.append(rec)
    return records


# ════════════════════════════════════════════════════════════════
# Part 2：支撑位 / 压力位识别（原 analysis.py）
# ════════════════════════════════════════════════════════════════

def find_support_resistance(
    df: pd.DataFrame,
    window: int = 10,
    keep: int = 5,
    price_tolerance_pct: float = 1.5,
) -> tuple[list, list]:
    """
    综合三种方法（局部极值 + 量价聚类 + 整数关口），返回 (supports, resistances)
    """
    current_price = df["close"].iloc[-1]
    all_supports, all_resistances = [], []

    sup1, res1 = _sr_local_extrema(df, window)
    sup2, res2 = _sr_volume_cluster(df, current_price)
    sup3, res3 = _sr_round_numbers(current_price)
    all_supports.extend(sup1 + sup2 + sup3)
    all_resistances.extend(res1 + res2 + res3)

    supports = _merge_levels(
        [s for s in all_supports if s < current_price * (1 + price_tolerance_pct / 100)],
        price_tolerance_pct,
    )
    resistances = _merge_levels(
        [r for r in all_resistances if r > current_price * (1 - price_tolerance_pct / 100)],
        price_tolerance_pct,
    )

    supports = sorted(supports)[-keep:]
    resistances = sorted(resistances)[:keep]

    logger.debug(f"支撑位: {supports}  |  压力位: {resistances}")
    return supports, resistances


def _sr_local_extrema(df: pd.DataFrame, window: int):
    supports, resistances = [], []
    lows = df["low"].values
    highs = df["high"].values

    if HAS_SCIPY:
        min_idx = argrelextrema(lows, np.less_equal, order=window)[0]
        max_idx = argrelextrema(highs, np.greater_equal, order=window)[0]
        supports = lows[min_idx].tolist()
        resistances = highs[max_idx].tolist()
    else:
        for i in range(window, len(df) - window):
            if lows[i] == min(lows[i - window: i + window + 1]):
                supports.append(lows[i])
            if highs[i] == max(highs[i - window: i + window + 1]):
                resistances.append(highs[i])
    return supports, resistances


def _sr_volume_cluster(df: pd.DataFrame, current_price: float, n_bins: int = 50):
    """成交量加权找密集区"""
    if "volume" not in df.columns or df["volume"].sum() == 0:
        return [], []

    price_min = df["low"].min()
    price_max = df["high"].max()
    bins = np.linspace(price_min, price_max, n_bins + 1)

    vol_profile = np.zeros(n_bins)
    for _, row in df.iterrows():
        lo, hi, vol = row["low"], row["high"], row["volume"]
        if hi == lo:
            idx = np.searchsorted(bins, lo, side="right") - 1
            idx = max(0, min(idx, n_bins - 1))
            vol_profile[idx] += vol
        else:
            for b in range(n_bins):
                overlap = max(0, min(bins[b + 1], hi) - max(bins[b], lo))
                vol_profile[b] += vol * overlap / (hi - lo)

    threshold = np.percentile(vol_profile, 70)
    cluster_centers = []
    for i in range(1, n_bins - 1):
        if vol_profile[i] >= threshold and vol_profile[i] >= vol_profile[i - 1] and vol_profile[i] >= vol_profile[i + 1]:
            cluster_centers.append((bins[i] + bins[i + 1]) / 2)

    return ([c for c in cluster_centers if c < current_price],
            [c for c in cluster_centers if c > current_price])


def _sr_round_numbers(current_price: float):
    """整数关口"""
    if current_price <= 0:
        return [], []

    if current_price < 10:
        step = 0.5
    elif current_price < 100:
        step = 1.0
    elif current_price < 1000:
        step = 10.0
    else:
        step = 50.0

    base = round(current_price / step) * step
    levels = [round(base + m * step, 4) for m in range(-5, 6)]

    return (sorted([l for l in levels if l < current_price], reverse=True)[:3],
            sorted([l for l in levels if l > current_price])[:3])


def _merge_levels(levels: list, tolerance_pct: float = 1.5) -> list:
    if not levels:
        return []
    levels = sorted(set(round(l, 4) for l in levels if l > 0))
    merged = [levels[0]]
    for price in levels[1:]:
        if abs(price - merged[-1]) / merged[-1] * 100 > tolerance_pct:
            merged.append(price)
        else:
            merged[-1] = round((merged[-1] + price) / 2, 4)
    return merged


def describe_sr_relation(
    current_price: float,
    supports: list,
    resistances: list,
    tolerance_pct: float = 2.0,
) -> dict:
    """描述当前价与最近支撑/压力的关系"""
    nearest_sup = max(supports) if supports else None
    nearest_res = min(resistances) if resistances else None

    near_support = near_resistance = broke_support = False
    diff_pct_sup = diff_pct_res = None

    if nearest_sup:
        diff_pct_sup = (current_price - nearest_sup) / nearest_sup * 100
        if -tolerance_pct <= diff_pct_sup <= tolerance_pct:
            near_support = True
        if diff_pct_sup < -tolerance_pct:
            broke_support = True

    if nearest_res:
        diff_pct_res = (nearest_res - current_price) / current_price * 100
        if 0 <= diff_pct_res <= tolerance_pct:
            near_resistance = True

    return {
        "nearest_support":       nearest_sup,
        "nearest_resistance":    nearest_res,
        "near_support":          near_support,
        "near_resistance":       near_resistance,
        "broke_support":         broke_support,
        "pct_above_support":     round(diff_pct_sup, 2) if diff_pct_sup is not None else None,
        "pct_below_resistance":  round(diff_pct_res, 2) if diff_pct_res is not None else None,
    }


# ════════════════════════════════════════════════════════════════
# Part 3：规则引擎 + 综合决策（原 decision.py）
# ════════════════════════════════════════════════════════════════

@dataclass
class DecisionResult:
    symbol: str
    stock_name: str
    price: float
    date: str

    rule_signal: str = "观望"
    rule_reasons: list = field(default_factory=list)

    ai_decision: str = "N/A"
    ai_confidence: str = "N/A"
    ai_reasons: list = field(default_factory=list)
    ai_risks: list = field(default_factory=list)
    ai_entry: float = None
    ai_stop_loss: float = None
    ai_target: float = None
    ai_target_short: float = None
    ai_target_long: float = None
    ai_summary: str = ""

    final_decision: str = "观望"
    alert_level: str = "normal"

    def to_log_string(self) -> str:
        lines = [
            f"{'=' * 55}",
            f"  [{self.symbol}] {self.stock_name}  {self.date}  收盘：{self.price:.3f}",
            f"{'=' * 55}",
            f"  规则信号：{self.rule_signal}",
        ]
        for r in self.rule_reasons:
            lines.append(f"    · {r}")
        if self.ai_decision != "N/A":
            lines.append(f"  AI 建议：{self.ai_decision}（置信度：{self.ai_confidence}）")
            lines.append(f"  AI 摘要：{self.ai_summary}")
            for r in self.ai_reasons:
                lines.append(f"    · {r}")
            if self.ai_entry:
                lines.append(f"  建议入场：{self.ai_entry}  止损：{self.ai_stop_loss}"
                             f"  短期目标：{self.ai_target_short}  长期目标：{self.ai_target_long}")
            if self.ai_risks:
                lines.append("  风险提示：" + "；".join(self.ai_risks))
        lines.append(f"  ★ 最终决策：{self.final_decision}  [{self.alert_level.upper()}]")
        lines.append(f"{'=' * 55}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol":          self.symbol,
            "name":            self.stock_name,
            "price":           self.price,
            "date":            self.date,
            "rule_signal":     self.rule_signal,
            "ai_target_short": self.ai_target_short,
            "ai_target_long":  self.ai_target_long,
            "ai_decision":     self.ai_decision,
            "final_decision":  self.final_decision,
            "alert_level":     self.alert_level,
            "ai_summary":      self.ai_summary,
        }


def rule_engine(df, supports: list, resistances: list, sr_relation: dict) -> tuple[str, list]:
    """规则引擎：基于技术指标打分，返回 (信号, 原因列表)"""
    last = df.iloc[-1]
    prev = df.iloc[-2]
    reasons = []
    buy_score = sell_score = 0
    price = last["close"]

    # ── 支撑/压力位 ──────────────────────────────────────
    if sr_relation.get("broke_support"):
        sell_score += 3
        reasons.append(f"⚠️ 价格跌破最近支撑位 {sr_relation['nearest_support']}")
    elif sr_relation.get("near_support"):
        buy_score += 1
        reasons.append(f"✓ 价格接近支撑位 {sr_relation['nearest_support']}"
                       f"（距支撑 {sr_relation['pct_above_support']:+.2f}%）")
    if sr_relation.get("near_resistance"):
        sell_score += 1
        reasons.append(f"⚠️ 价格接近压力位 {sr_relation['nearest_resistance']}"
                       f"（距压力 {sr_relation['pct_below_resistance']:.2f}%）")

    # ── MACD ─────────────────────────────────────────────
    dif = last.get("dif", 0) or 0
    dea = last.get("dea", 0) or 0
    hist = last.get("macd_hist", 0) or 0
    prev_dif = prev.get("dif", 0) or 0
    prev_dea = prev.get("dea", 0) or 0

    if dif > dea and prev_dif <= prev_dea:
        buy_score += 2
        reasons.append(f"✓ MACD 金叉（DIF={dif:.4f} 上穿 DEA={dea:.4f}）")
    elif dif < dea and prev_dif >= prev_dea:
        sell_score += 2
        reasons.append(f"⚠️ MACD 死叉（DIF={dif:.4f} 下穿 DEA={dea:.4f}）")

    prev_hist = prev.get("macd_hist", 0) or 0
    if hist > 0 and prev_hist <= 0:
        buy_score += 1
        reasons.append("✓ MACD 柱由负转正")
    elif hist < 0 and prev_hist >= 0:
        sell_score += 1
        reasons.append("⚠️ MACD 柱由正转负")

    # ── 布林带 ────────────────────────────────────────────
    bb_lower = last.get("bb_lower", 0) or 0
    bb_upper = last.get("bb_upper", 0) or 0
    if bb_lower > 0 and price <= bb_lower * 1.005:
        buy_score += 2
        reasons.append(f"✓ 价格触及布林下轨（下轨={bb_lower:.3f}）")
    if bb_upper > 0 and price >= bb_upper * 0.995:
        sell_score += 2
        reasons.append(f"⚠️ 价格触及布林上轨（上轨={bb_upper:.3f}）")

    # ── 均线 ──────────────────────────────────────────────
    ma5 = last.get("ma5", 0) or 0
    ma20 = last.get("ma20", 0) or 0
    prev_ma5 = prev.get("ma5", 0) or 0
    prev_ma20 = prev.get("ma20", 0) or 0

    if ma20 > 0 and price > ma20 and prev["close"] <= prev_ma20:
        buy_score += 1
        reasons.append(f"✓ 价格站上 MA20（{ma20:.3f}）")
    if ma20 > 0 and price < ma20 and prev["close"] >= prev_ma20:
        sell_score += 1
        reasons.append(f"⚠️ 价格跌破 MA20（{ma20:.3f}）")

    if ma5 > 0 and ma20 > 0:
        if ma5 > ma20 and prev_ma5 <= prev_ma20:
            buy_score += 1
            reasons.append("✓ MA5 上穿 MA20（短期金叉）")
        elif ma5 < ma20 and prev_ma5 >= prev_ma20:
            sell_score += 1
            reasons.append("⚠️ MA5 下穿 MA20（短期死叉）")

    # ── RSI ─────────────────────────────────────────────
    rsi = last.get("rsi", 50) or 50
    if rsi < 30:
        buy_score += 1
        reasons.append(f"✓ RSI 超卖（RSI={rsi:.1f}）")
    elif rsi > 70:
        sell_score += 1
        reasons.append(f"⚠️ RSI 超买（RSI={rsi:.1f}）")

    # ── 成交量配合 ──────────────────────────────────────
    vol_ratio = last.get("vol_ratio", 1) or 1
    if buy_score > sell_score and vol_ratio >= 1.5:
        buy_score += 1
        reasons.append(f"✓ 放量配合多方信号（量比={vol_ratio:.2f}）")
    elif sell_score > buy_score and vol_ratio >= 1.5:
        sell_score += 1
        reasons.append(f"⚠️ 放量配合空方信号（量比={vol_ratio:.2f}）")

    # ── 综合信号 ────────────────────────────────────────
    if buy_score >= 4 and buy_score > sell_score + 1:
        signal = "买入"
    elif sell_score >= 4 and sell_score > buy_score + 1:
        signal = "卖出"
    elif buy_score >= 2 and buy_score > sell_score:
        signal = "持有"
    elif sell_score >= 2 and sell_score > buy_score:
        signal = "观望"
    else:
        signal = "观望"

    reasons.insert(0, f"规则得分 → 买入信号：{buy_score}分，卖出信号：{sell_score}分")
    return signal, reasons


def make_final_decision(
    symbol: str,
    stock_name: str,
    df,
    supports: list,
    resistances: list,
    sr_relation: dict,
    ai_result: dict = None,
) -> DecisionResult:
    """综合规则引擎 + AI，输出最终决策"""
    last = df.iloc[-1]
    price = float(last["close"])
    date_str = str(last["date"])[:10]

    result = DecisionResult(
        symbol=symbol,
        stock_name=stock_name,
        price=price,
        date=date_str,
    )
    result.ai_target_short = ai_result.get("suggested_target_short") if ai_result else None
    result.ai_target_long  = ai_result.get("suggested_target_long")  if ai_result else None

    # 规则引擎
    rule_signal, rule_reasons = rule_engine(df, supports, resistances, sr_relation)
    result.rule_signal = rule_signal
    result.rule_reasons = rule_reasons

    # AI 结果
    if ai_result and ai_result.get("decision") not in ("ERROR", None):
        result.ai_decision   = ai_result.get("decision", "观望")
        result.ai_confidence = ai_result.get("confidence", "低")
        result.ai_reasons    = ai_result.get("key_reasons", [])
        result.ai_risks      = ai_result.get("risk_warnings", [])
        result.ai_entry      = ai_result.get("suggested_entry")
        result.ai_stop_loss  = ai_result.get("suggested_stop_loss")
        result.ai_target     = ai_result.get("suggested_target")
        result.ai_summary    = ai_result.get("summary", "")

    # ── 综合最终逻辑 ──────────────────────────────────
    ai_d, rule_d = result.ai_decision, result.rule_signal
    BUY, SELL = {"买入"}, {"卖出"}

    both_buy   = rule_d in BUY  and ai_d in BUY
    both_sell  = rule_d in SELL and ai_d in SELL
    conflict   = (rule_d in BUY and ai_d in SELL) or (rule_d in SELL and ai_d in BUY)
    rule_buy_ai_hold = rule_d in BUY and ai_d in {"持有", "观望"}
    ai_buy_rule_hold = ai_d in BUY and rule_d in {"持有", "观望"}

    if both_buy:
        result.final_decision = "强烈买入"
        result.alert_level    = "strong"
    elif both_sell:
        result.final_decision = "强烈卖出"
        result.alert_level    = "strong"
    elif conflict:
        result.final_decision = "信号冲突，观望"
        result.alert_level    = "warning"
    elif rule_buy_ai_hold or ai_buy_rule_hold:
        result.final_decision = "买入（信号一般）"
        result.alert_level    = "warning"
    elif rule_d in SELL or ai_d in SELL:
        result.final_decision = "倾向卖出/减仓"
        result.alert_level    = "warning"
    elif ai_d == "N/A":
        result.final_decision = rule_signal
        result.alert_level    = "normal" if rule_signal == "观望" else "warning"
    else:
        result.final_decision = "观望"
        result.alert_level    = "normal"

    return result
