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
        # akshare 当前列名：'当日成交净买额'（亿元，已经是亿元单位，不要再除 1e8）
        # 兼容旧列名 '当日净买额'
        net_col = next((c for c in ["当日成交净买额", "当日净买额", "net_buy"] if c in df.columns), None)
        cum_col = next((c for c in ["历史累计净买额", "累计净买额"] if c in df.columns), None)
        if not net_col:
            logger.warning(f"[北向] 找不到净买额列，实际列名: {list(df.columns)}")
            return empty

        # 安全转 float：NaN/None/非数值都视为 None（NaN 是 truthy，不能用 `x or 0`！）
        def _safe_num(x):
            try:
                v = float(x)
                if v != v:  # NaN 检测（NaN != NaN 是 Python 唯一标识 NaN 的方式）
                    return None
                return v
            except (TypeError, ValueError):
                return None

        for _, row in df.iterrows():
            raw_net = _safe_num(row.get(net_col))
            if raw_net is None:
                # 跳过这一天的数据（akshare 经常在最新交易日盘中返回 NaN，等收盘才有值）
                continue
            history.append({
                "date":        str(row.get("日期", row.get("date", ""))),
                "net":         round(raw_net, 2),
                "cumulative":  round(_safe_num(row.get(cum_col)) or 0, 2) if cum_col else 0,
            })

        today_net = history[-1]["net"]   if history else None
        net5      = round(sum(h["net"] for h in history[-5:]), 2) if len(history) >= 5 else None

        if today_net is None:
            logger.info("[北向] 暂无有效数据（可能盘中数据未发布）")
            return empty
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

    is_sh = code.startswith("6")
    fetcher = ak.stock_margin_detail_sse if is_sh else ak.stock_margin_detail_szse
    code_col_candidates = ["股票代码", "证券代码", "标的证券代码"]

    # 尝试今天 → 昨天 → ... 最多回溯 7 天，找到有数据的最近交易日
    today = datetime.date.today()
    df, used_date = None, None
    for back in range(0, 8):
        d = today - datetime.timedelta(days=back)
        # 跳过周末
        if d.weekday() >= 5:
            continue
        date_str = d.strftime("%Y%m%d")
        try:
            df_try = fetcher(date=date_str)
            if df_try is not None and not df_try.empty:
                df, used_date = df_try, date_str
                break
        except Exception as e:
            logger.debug(f"[融资融券] {code} 拉取 {date_str} 失败: {e}")
            continue

    if df is None or df.empty:
        logger.warning(f"[融资融券] {code} 近 7 日均无数据")
        return empty

    try:
        # 找代码列
        code_col = next((c for c in code_col_candidates if c in df.columns), None)
        if not code_col:
            logger.warning(f"[融资融券] {code} 找不到代码列，实际列: {list(df.columns)}")
            return empty

        row = df[df[code_col].astype(str).str.zfill(6) == code.zfill(6)]
        if row.empty:
            logger.info(f"[融资融券] {code} 在 {used_date} 数据中未找到")
            return empty

        r = row.iloc[0]
        # 兼容沪/深不同列名
        margin_bal = float(r.get("融资余额", r.get("融资余额(元)", 0)) or 0)
        short_bal  = float(r.get("融券余量金额", r.get("融券余额", r.get("融券余额(元)", 0))) or 0)
        margin_buy = float(r.get("融资买入额", r.get("融资买入额(元)", 0)) or 0)

        logger.info(f"[融资融券] {code} ({used_date}) 融资余额={margin_bal/1e8:.2f}亿  融券={short_bal/1e8:.2f}亿")
        return {
            "margin_balance":    margin_bal,
            "short_balance":     short_bal,
            "margin_buy":        margin_buy,
            "margin_change_pct": None,
            "history":           [],
            "data_date":         used_date,
            "updated_at":        datetime.datetime.now().isoformat(),
            "source":            "akshare",
        }

    except Exception as e:
        logger.warning(f"[融资融券] {code} 解析失败: {e}")
        return empty
