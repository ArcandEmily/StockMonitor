"""
sector_fetcher.py
─────────────────
板块 / 概念联动分析

功能：
  1. 查询个股所属行业板块
  2. 获取同板块前 5 名个股涨跌情况
  3. 板块整体今日表现

数据来源：东方财富（通过 akshare）
缓存：60 分钟（板块变化慢）
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

_cache: dict = {}          # code → {industry, peers, updated_at}
_lock  = threading.Lock()
_TTL   = 3600              # 1 小时缓存


def get_sector_info(code: str) -> dict:
    """
    返回个股板块联动信息：
    {
      "industry": "食品饮料",
      "industry_change_pct": 1.23,      # 板块今日涨跌%
      "peers": [                        # 同板块 Top5（市值排序）
        {"code":"600519","name":"贵州茅台","change_pct":1.5,"price":1560},
        ...
      ],
      "updated_at": "...",
      "source": "akshare"
    }
    """
    with _lock:
        cached = _cache.get(code)
        if cached and (time.time() - cached.get("_ts", 0)) < _TTL:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

    result = _fetch_sector(code)

    with _lock:
        _cache[code] = {**result, "_ts": time.time()}

    return result


def _fetch_sector(code: str) -> dict:
    empty = {"industry": None, "industry_change_pct": None, "peers": [],
             "updated_at": datetime.datetime.now().isoformat(), "source": "fallback"}

    if not HAS_AK:
        return empty

    # ── Step 1: 获取个股所属行业 ─────────────────────────────
    industry = None
    try:
        info_df = ak.stock_individual_info_em(symbol=code)
        # 返回 DataFrame，item 列包含 "行业" 字段
        row = info_df[info_df["item"] == "行业"]
        if not row.empty:
            industry = str(row.iloc[0]["value"]).strip()
    except Exception as e:
        logger.debug(f"[sector] 获取 {code} 行业信息失败: {e}")
        return empty

    if not industry:
        return empty

    # ── Step 2: 板块今日涨跌 ─────────────────────────────────
    industry_pct = None
    try:
        boards = ak.stock_board_industry_name_em()
        matched = boards[boards["板块名称"].str.contains(industry[:4], na=False)]
        if not matched.empty:
            industry_pct = float(matched.iloc[0].get("涨跌幅", 0) or 0)
    except Exception as e:
        logger.debug(f"[sector] 获取板块涨跌失败: {e}")

    # ── Step 3: 同板块成分股 ─────────────────────────────────
    peers = []
    try:
        cons_df = ak.stock_board_industry_cons_em(symbol=industry)
        # 过滤掉自身，按涨跌幅排序，取前 6
        if "代码" in cons_df.columns:
            cons_df = cons_df[cons_df["代码"] != code]
            if "涨跌幅" in cons_df.columns:
                cons_df = cons_df.sort_values("涨跌幅", ascending=False)
            for _, r in cons_df.head(6).iterrows():
                peers.append({
                    "code":       str(r.get("代码", "")),
                    "name":       str(r.get("名称", "")),
                    "price":      float(r.get("最新价", 0) or 0),
                    "change_pct": float(r.get("涨跌幅", 0) or 0),
                })
    except Exception as e:
        logger.debug(f"[sector] 获取成分股失败: {e}")

    logger.info(f"[sector] {code} → 行业={industry}  同板块 {len(peers)} 只")
    return {
        "industry":             industry,
        "industry_change_pct":  industry_pct,
        "peers":                peers,
        "updated_at":           datetime.datetime.now().isoformat(),
        "source":               "akshare",
    }
