"""
支撑位 / 压力位识别模块
方法：
  1. 局部极值法（scipy argrelextrema）
  2. 价格密集区（成交量加权聚类）
  3. 整数关口（心理价位）
最终合并三种方法，排重后按价格排序
"""
import numpy as np
import pandas as pd
from loguru import logger

try:
    from scipy.signal import argrelextrema
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("scipy 未安装，局部极值法不可用，将使用滑动窗口替代")


# ────────────────────────────────────────────────────────────────
#  主入口
# ────────────────────────────────────────────────────────────────

def find_support_resistance(
    df: pd.DataFrame,
    window: int = 10,
    keep: int = 5,
    price_tolerance_pct: float = 1.5,
) -> tuple[list, list]:
    """
    返回 (supports, resistances)，各为价格列表（升序）
    """
    current_price = df["close"].iloc[-1]
    all_supports = []
    all_resistances = []

    # 方法 1：局部极值
    sup1, res1 = _method_local_extrema(df, window)
    all_supports.extend(sup1)
    all_resistances.extend(res1)

    # 方法 2：价格密集区（成交量聚类）
    sup2, res2 = _method_volume_cluster(df, current_price)
    all_supports.extend(sup2)
    all_resistances.extend(res2)

    # 方法 3：整数关口
    sup3, res3 = _method_round_numbers(current_price)
    all_supports.extend(sup3)
    all_resistances.extend(res3)

    # 去重合并
    supports = _merge_levels(
        [s for s in all_supports if s < current_price * (1 + price_tolerance_pct / 100)],
        price_tolerance_pct,
    )
    resistances = _merge_levels(
        [r for r in all_resistances if r > current_price * (1 - price_tolerance_pct / 100)],
        price_tolerance_pct,
    )

    # 取最靠近当前价的 keep 个
    supports = sorted(supports)[-keep:]
    resistances = sorted(resistances)[:keep]

    logger.debug(f"支撑位: {supports}  |  压力位: {resistances}")
    return supports, resistances


# ────────────────────────────────────────────────────────────────
#  方法 1：局部极值
# ────────────────────────────────────────────────────────────────

def _method_local_extrema(df: pd.DataFrame, window: int):
    supports, resistances = [], []
    lows = df["low"].values
    highs = df["high"].values

    if HAS_SCIPY:
        min_idx = argrelextrema(lows, np.less_equal, order=window)[0]
        max_idx = argrelextrema(highs, np.greater_equal, order=window)[0]
        supports = lows[min_idx].tolist()
        resistances = highs[max_idx].tolist()
    else:
        # 滑动窗口替代
        for i in range(window, len(df) - window):
            if lows[i] == min(lows[i - window: i + window + 1]):
                supports.append(lows[i])
            if highs[i] == max(highs[i - window: i + window + 1]):
                resistances.append(highs[i])

    return supports, resistances


# ────────────────────────────────────────────────────────────────
#  方法 2：成交量聚类（价格密集区）
# ────────────────────────────────────────────────────────────────

def _method_volume_cluster(df: pd.DataFrame, current_price: float, n_bins: int = 50):
    """
    以成交量加权，在价格区间内找出成交密集区
    密集区低于当前价 → 支撑；高于 → 压力
    """
    if "volume" not in df.columns or df["volume"].sum() == 0:
        return [], []

    price_min = df["low"].min()
    price_max = df["high"].max()
    bins = np.linspace(price_min, price_max, n_bins + 1)

    # 每根K线的成交量按价格分布均匀分配到其高低价区间
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

    # 找局部峰值（密集区）
    threshold = np.percentile(vol_profile, 70)
    cluster_centers = []
    for i in range(1, n_bins - 1):
        if vol_profile[i] >= threshold and vol_profile[i] >= vol_profile[i - 1] and vol_profile[i] >= vol_profile[i + 1]:
            center = (bins[i] + bins[i + 1]) / 2
            cluster_centers.append(center)

    supports = [c for c in cluster_centers if c < current_price]
    resistances = [c for c in cluster_centers if c > current_price]
    return supports, resistances


# ────────────────────────────────────────────────────────────────
#  方法 3：整数关口
# ────────────────────────────────────────────────────────────────

def _method_round_numbers(current_price: float):
    """生成当前价附近的整数 / 半整数关口"""
    if current_price <= 0:
        return [], []

    # 根据价格量级确定步长
    if current_price < 10:
        step = 0.5
    elif current_price < 100:
        step = 1.0
    elif current_price < 1000:
        step = 10.0
    else:
        step = 50.0

    levels = []
    base = round(current_price / step) * step
    for mult in range(-5, 6):
        levels.append(round(base + mult * step, 4))

    supports = sorted([l for l in levels if l < current_price], reverse=True)[:3]
    resistances = sorted([l for l in levels if l > current_price])[:3]
    return supports, resistances


# ────────────────────────────────────────────────────────────────
#  工具：合并接近的价位
# ────────────────────────────────────────────────────────────────

def _merge_levels(levels: list, tolerance_pct: float = 1.5) -> list:
    if not levels:
        return []
    levels = sorted(set(round(l, 4) for l in levels if l > 0))
    merged = [levels[0]]
    for price in levels[1:]:
        if abs(price - merged[-1]) / merged[-1] * 100 > tolerance_pct:
            merged.append(price)
        else:
            # 取均值
            merged[-1] = round((merged[-1] + price) / 2, 4)
    return merged


# ────────────────────────────────────────────────────────────────
#  描述支撑/压力与当前价关系
# ────────────────────────────────────────────────────────────────

def describe_sr_relation(
    current_price: float,
    supports: list,
    resistances: list,
    tolerance_pct: float = 2.0,
) -> dict:
    """
    返回一个结构化描述，判断价格是否接近关键位
    """
    nearest_sup = max(supports) if supports else None
    nearest_res = min(resistances) if resistances else None

    near_support = False
    near_resistance = False
    broke_support = False

    if nearest_sup:
        diff_pct_sup = (current_price - nearest_sup) / nearest_sup * 100
        if -tolerance_pct <= diff_pct_sup <= tolerance_pct:
            near_support = True
        if diff_pct_sup < -tolerance_pct:
            broke_support = True
    else:
        diff_pct_sup = None

    if nearest_res:
        diff_pct_res = (nearest_res - current_price) / current_price * 100
        if 0 <= diff_pct_res <= tolerance_pct:
            near_resistance = True
    else:
        diff_pct_res = None

    return {
        "nearest_support": nearest_sup,
        "nearest_resistance": nearest_res,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "broke_support": broke_support,
        "pct_above_support": round(diff_pct_sup, 2) if diff_pct_sup is not None else None,
        "pct_below_resistance": round(diff_pct_res, 2) if diff_pct_res is not None else None,
    }
