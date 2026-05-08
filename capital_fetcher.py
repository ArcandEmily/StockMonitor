"""
capital_fetcher.py
──────────────────
北向资金 + 融资融券数据

功能：
  1. 北向资金近 10 日净流入趋势
  2. 个股融资融券余额及变化

数据来源：akshare（东方财富/沪深交易所）
缓存：北向 30 分钟，融资融券 60 分钟
"""

import datetime
import threading
import time
from loguru import logger

try:
    import akshare as ak
    HAS_AK = True
except ImportError:
    HAS_AK = False

_north_cache: dict = {}
_north_ts: float   = 0
_north_lock        = threading.Lock()
_NORTH_TTL         = 1800   # 30 分钟

_margin_cache: dict = {}
_margin_lock        = threading.Lock()
_MARGIN_TTL         = 3600   # 60 分钟


# ══════════════════════════════════════════════════════════════
#  北向资金
# ══════════════════════════════════════════════════════════════

def get_northbound() -> dict:
    """
    返回北向资金近 10 日数据：
    {
      "today_net": -12.3,             # 今日净流入（亿元）
      "5day_net":  -45.6,             # 近5日累计
      "history": [                    # 近10日列表
        {"date":"2026-05-06","net":12.3,"cumulative":...},
        ...
      ],
      "updated_at": "...",
      "source": "akshare"
    }
    """
    global _north_ts
    with _north_lock:
        if _north_cache and (time.time() - _north_ts) < _NORTH_TTL:
            return dict(_north_cache)

    result = _fetch_northbound()

    with _north_lock:
        _north_cache.clear()
        _north_cache.update(result)
        _north_ts = time.time()

    return result


def _fetch_northbound() -> dict:
    empty = {"today_net": None, "5day_net": None, "history": [],
             "updated_at": datetime.datetime.now().isoformat(), "source": "fallback"}

    if not HAS_AK:
        return empty

    try:
        # 沪深港通资金流向历史
        today     = datetime.date.today()
        start     = (today - datetime.timedelta(days=20)).strftime("%Y%m%d")
        end_str   = today.strftime("%Y%m%d")

        # 北向资金净流入（东方财富）
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return empty

        df = df.tail(10)
        history = []
        for _, row in df.iterrows():
            history.append({
                "date":        str(row.get("日期", row.get("date", ""))),
                "net":         round(float(row.get("当日净买额", row.get("net_buy", 0)) or 0) / 1e8, 2),
                "cumulative":  round(float(row.get("历史累计净买额", 0) or 0) / 1e8, 2),
            })

        today_net = history[-1]["net"]   if history else None
        net5      = sum(h["net"] for h in history[-5:]) if len(history) >= 5 else None

        logger.info(f"[北向] 今日净流入={today_net}亿  近5日={net5}亿")
        return {
            "today_net":  today_net,
            "5day_net":   round(net5, 2) if net5 is not None else None,
            "history":    history,
            "updated_at": datetime.datetime.now().isoformat(),
            "source":     "akshare",
        }

    except Exception as e:
        logger.warning(f"[北向] 获取失败: {e}")
        return empty


# ══════════════════════════════════════════════════════════════
#  融资融券
# ══════════════════════════════════════════════════════════════

def get_margin(code: str) -> dict:
    """
    返回个股最近 10 日融资融券数据：
    {
      "margin_balance":   12345678,   # 融资余额（元）
      "short_balance":    2345678,    # 融券余额（元）
      "margin_buy":       345678,     # 今日融资买入
      "margin_change_pct": 2.3,       # 融资余额较前5日均值变化%
      "history": [...],
      "updated_at": "...",
    }
    """
    with _margin_lock:
        cached = _margin_cache.get(code)
        if cached and (time.time() - cached.get("_ts", 0)) < _MARGIN_TTL:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

    result = _fetch_margin(code)

    with _margin_lock:
        _margin_cache[code] = {**result, "_ts": time.time()}

    return result


def _fetch_margin(code: str) -> dict:
    empty = {"margin_balance": None, "short_balance": None,
             "margin_buy": None, "margin_change_pct": None,
             "history": [], "updated_at": datetime.datetime.now().isoformat(),
             "source": "fallback"}

    if not HAS_AK:
        return empty

    try:
        today    = datetime.date.today()
        date_str = today.strftime("%Y%m%d")

        # 根据市场选接口
        if code.startswith("6"):
            df = ak.stock_margin_detail_sse(date=date_str)
            code_col = "股票代码"
        else:
            df = ak.stock_margin_detail_szse(date=date_str)
            code_col = "证券代码"

        if df is None or df.empty:
            return empty

        # 找到目标股票行
        row = df[df[code_col].astype(str).str.contains(code)]
        if row.empty:
            return empty

        r = row.iloc[0]
        margin_bal = float(r.get("融资余额", 0) or 0)
        short_bal  = float(r.get("融券余额", 0) or r.get("融券余量金额", 0) or 0)
        margin_buy = float(r.get("融资买入额", 0) or 0)

        logger.info(f"[融资融券] {code} 融资余额={margin_bal/1e8:.2f}亿")
        return {
            "margin_balance":    margin_bal,
            "short_balance":     short_bal,
            "margin_buy":        margin_buy,
            "margin_change_pct": None,   # 需要历史数据计算，此处省略
            "history":           [],
            "updated_at":        datetime.datetime.now().isoformat(),
            "source":            "akshare",
        }

    except Exception as e:
        logger.debug(f"[融资融券] {code} 获取失败: {e}")
        return empty
