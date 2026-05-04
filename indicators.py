"""
技术指标计算模块
- MACD（DIF / DEA / MACD柱）
- 布林带（上轨 / 中轨 / 下轨 / 带宽）
- 成交量指标（Volume MA / 量比 / OBV）
- 换手率统计
- 均线（MA5 / MA10 / MA20 / MA60）
- RSI（辅助）
"""
import numpy as np
import pandas as pd
from loguru import logger


# ────────────────────────────────────────────────────────────────
#  主入口
# ────────────────────────────────────────────────────────────────

def calc_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df = _calc_macd(df)
    df = _calc_bollinger(df)
    df = _calc_ma(df)
    df = _calc_volume_indicators(df)
    df = _calc_rsi(df)
    return df


# ────────────────────────────────────────────────────────────────
#  MACD
# ────────────────────────────────────────────────────────────────

def _calc_macd(df: pd.DataFrame, fast=12, slow=26, signal=9) -> pd.DataFrame:
    ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow, adjust=False).mean()
    df["dif"] = ema_fast - ema_slow
    df["dea"] = df["dif"].ewm(span=signal, adjust=False).mean()
    df["macd_hist"] = (df["dif"] - df["dea"]) * 2  # MACD 柱（*2 与主流软件一致）
    return df


# ────────────────────────────────────────────────────────────────
#  布林带
# ────────────────────────────────────────────────────────────────

def _calc_bollinger(df: pd.DataFrame, window=20, n_std=2) -> pd.DataFrame:
    mid = df["close"].rolling(window).mean()
    std = df["close"].rolling(window).std(ddof=0)
    df["bb_upper"] = mid + n_std * std
    df["bb_mid"] = mid
    df["bb_lower"] = mid - n_std * std
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"] * 100  # 带宽%
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])  # 价格在带内位置 0~1
    return df


# ────────────────────────────────────────────────────────────────
#  均线
# ────────────────────────────────────────────────────────────────

def _calc_ma(df: pd.DataFrame) -> pd.DataFrame:
    for n in [5, 10, 20, 60]:
        df[f"ma{n}"] = df["close"].rolling(n).mean().round(4)
    return df


# ────────────────────────────────────────────────────────────────
#  成交量指标
# ────────────────────────────────────────────────────────────────

def _calc_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    # 量能均线
    df["vol_ma5"] = df["volume"].rolling(5).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # 量比：当日成交量 / 近 5 日均量
    df["vol_ratio"] = df["volume"] / df["vol_ma5"]

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

    # 换手率 5 日均值（如果列存在）
    if "turnover_rate" in df.columns:
        df["turnover_rate_ma5"] = df["turnover_rate"].rolling(5).mean()

    return df


# ────────────────────────────────────────────────────────────────
#  RSI
# ────────────────────────────────────────────────────────────────

def _calc_rsi(df: pd.DataFrame, period=14) -> pd.DataFrame:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


# ────────────────────────────────────────────────────────────────
#  辅助：获取最近 N 根 K 线快照（用于 AI prompt）
# ────────────────────────────────────────────────────────────────

def get_recent_snapshot(df: pd.DataFrame, n: int = 10) -> list[dict]:
    """返回最近 n 根 K 线的关键字段列表，供 AI 消化"""
    cols = [
        "date", "open", "close", "high", "low",
        "volume", "turnover_rate", "change_pct",
        "dif", "dea", "macd_hist",
        "bb_upper", "bb_mid", "bb_lower", "bb_pct",
        "ma5", "ma10", "ma20", "ma60",
        "vol_ratio", "rsi",
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
