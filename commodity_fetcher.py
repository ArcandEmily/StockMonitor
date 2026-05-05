"""
commodity_fetcher.py
────────────────────
大宗商品数据抓取模块

数据来源优先级：
  1. 华尔街见闻 (wallstreetcn.com)  —— 主数据源，国际+国内期货
  2. Yahoo Finance                  —— 备用（国际期货）
  3. 东方财富 (eastmoney)           —— 备用（国内主力合约）
  4. 内置静态兜底数据               —— 三路均失败时返回

返回标准格式：
  {
    "code":       "CL",
    "name":       "原油(WTI)",
    "price":      82.35,
    "change":     -0.45,
    "change_pct": -0.54,
    "unit":       "USD/桶",
    "category":   "能源",
    "source":     "wallstreetcn",
    "updated_at": "2026-05-05T10:00:00"
  }
"""

import time
import datetime
import threading
import requests
from loguru import logger

# ══════════════════════════════════════════════════════════════
#  大宗商品配置表
# ══════════════════════════════════════════════════════════════
COMMODITY_CONFIG = [
    # ── 能源 ────────────────────────────────────────────────
    {"code": "CL",  "name": "原油(WTI)",  "wsn": "NYMEX:CLc1",  "yahoo": "CL=F",  "em_symbol": "SC0",  "unit": "USD/桶",    "category": "能源"},
    {"code": "NG",  "name": "天然气",     "wsn": "NYMEX:NGc1",  "yahoo": "NG=F",  "em_symbol": None,   "unit": "USD/MMBtu", "category": "能源"},
    # ── 贵金属 ──────────────────────────────────────────────
    {"code": "GC",  "name": "黄金",       "wsn": "COMEX:GCc1",  "yahoo": "GC=F",  "em_symbol": "AU0",  "unit": "USD/盎司",  "category": "贵金属"},
    {"code": "SI",  "name": "白银",       "wsn": "COMEX:SIc1",  "yahoo": "SI=F",  "em_symbol": "AG0",  "unit": "USD/盎司",  "category": "贵金属"},
    # ── 工业金属 ────────────────────────────────────────────
    {"code": "HG",  "name": "铜",         "wsn": "COMEX:HGc1",  "yahoo": "HG=F",  "em_symbol": "CU0",  "unit": "USD/磅",    "category": "工业金属"},
    {"code": "ALI", "name": "铝",         "wsn": "LME:ALUMc1",  "yahoo": "ALI=F", "em_symbol": "AL0",  "unit": "USD/吨",    "category": "工业金属"},
    # ── 农产品 ──────────────────────────────────────────────
    {"code": "ZC",  "name": "玉米",       "wsn": "CBOT:ZCc1",   "yahoo": "ZC=F",  "em_symbol": None,   "unit": "USD/蒲式耳","category": "农产品"},
    {"code": "ZS",  "name": "大豆",       "wsn": "CBOT:ZSc1",   "yahoo": "ZS=F",  "em_symbol": None,   "unit": "USD/蒲式耳","category": "农产品"},
    {"code": "ZW",  "name": "小麦",       "wsn": "CBOT:ZWc1",   "yahoo": "ZW=F",  "em_symbol": None,   "unit": "USD/蒲式耳","category": "农产品"},
    # ── 黑色系（国内）───────────────────────────────────────
    {"code": "RB",  "name": "螺纹钢",     "wsn": "SHFE:RBc1",   "yahoo": None,    "em_symbol": "RB0",  "unit": "元/吨",     "category": "黑色系"},
    {"code": "I",   "name": "铁矿石",     "wsn": "DCE:Ic1",     "yahoo": None,    "em_symbol": "I0",   "unit": "元/吨",     "category": "黑色系"},
]

# 静态兜底数据（所有网络源失败时返回）
_FALLBACK = {
    "CL":  {"price": 82.35,    "change": -0.45, "change_pct": -0.54},
    "NG":  {"price": 2.18,     "change": +0.03, "change_pct": +1.40},
    "GC":  {"price": 3285.0,   "change": +12.5, "change_pct": +0.38},
    "SI":  {"price": 33.15,    "change": -0.22, "change_pct": -0.66},
    "HG":  {"price": 4.72,     "change": +0.04, "change_pct": +0.86},
    "ALI": {"price": 2580.0,   "change": -8.0,  "change_pct": -0.31},
    "ZC":  {"price": 448.25,   "change": +2.75, "change_pct": +0.62},
    "ZS":  {"price": 1022.5,   "change": -5.25, "change_pct": -0.51},
    "ZW":  {"price": 535.0,    "change": +1.50, "change_pct": +0.28},
    "RB":  {"price": 3285.0,   "change": -15.0, "change_pct": -0.45},
    "I":   {"price": 812.0,    "change": +6.0,  "change_pct": +0.74},
}

# ══════════════════════════════════════════════════════════════
#  来源 1：华尔街见闻 (wallstreetcn.com)
# ══════════════════════════════════════════════════════════════

_WSN_CACHE: dict = {}
_WSN_CACHE_TS: float = 0
_WSN_TTL: int = 120   # 2 分钟缓存，避免频繁请求


def _fetch_wsn_batch(wsn_symbols: list[str], timeout: int = 10) -> dict:
    """
    批量拉取华尔街见闻行情。
    返回 {wsn_symbol: {"price":..., "change":..., "change_pct":..., "source":"wallstreetcn"}}
    """
    global _WSN_CACHE, _WSN_CACHE_TS
    now = time.time()
    if _WSN_CACHE and (now - _WSN_CACHE_TS) < _WSN_TTL:
        return _WSN_CACHE

    result: dict = {}
    try:
        codes = ",".join(wsn_symbols)
        # 华尔街见闻行情 API（批量）
        url = "https://api-prod.wallstreetcn.com/apiv1/financial-futures-quotations/basic-info"
        params = {"asset_codes": codes}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://wallstreetcn.com/",
            "Origin": "https://wallstreetcn.com",
        }
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        data = r.json()

        # 响应结构：{"code":20000,"data":{"list":[{...}, ...]}}
        items = (data.get("data") or {}).get("list") or []
        for item in items:
            sym  = item.get("asset_code") or item.get("code", "")
            if not sym:
                continue
            # 字段可能叫 last / close / price
            price = float(item.get("last") or item.get("close") or item.get("price") or 0)
            chg   = float(item.get("chg") or item.get("change") or 0)
            pct   = float(item.get("chg_pct") or item.get("change_pct") or 0)
            if price:
                result[sym] = {"price": price, "change": chg, "change_pct": pct, "source": "wallstreetcn"}

        if result:
            _WSN_CACHE = result
            _WSN_CACHE_TS = now
            logger.debug(f"WSN batch: got {len(result)} symbols")

    except Exception as e:
        logger.debug(f"WSN batch fetch failed: {e}")

    return result


def _fetch_wsn_single(wsn_sym: str, timeout: int = 8) -> dict | None:
    """单品种 fallback（batch 失败时）"""
    try:
        url = "https://api-prod.wallstreetcn.com/apiv1/financial-futures-quotations/basic-info"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://wallstreetcn.com/",
        }
        r = requests.get(url, params={"asset_codes": wsn_sym}, headers=headers, timeout=timeout)
        data = r.json()
        items = (data.get("data") or {}).get("list") or []
        if not items:
            return None
        item  = items[0]
        price = float(item.get("last") or item.get("close") or item.get("price") or 0)
        chg   = float(item.get("chg") or item.get("change") or 0)
        pct   = float(item.get("chg_pct") or item.get("change_pct") or 0)
        if not price:
            return None
        return {"price": price, "change": chg, "change_pct": pct, "source": "wallstreetcn"}
    except Exception as e:
        logger.debug(f"WSN single {wsn_sym} failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  来源 2：Yahoo Finance
# ══════════════════════════════════════════════════════════════

def _fetch_yahoo(yahoo_sym: str, timeout: int = 8) -> dict | None:
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}"
        params = {"interval": "1d", "range": "2d"}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "application/json",
        }
        r     = requests.get(url, params=params, headers=headers, timeout=timeout)
        data  = r.json()
        meta  = data["chart"]["result"][0]["meta"]
        price = float(meta.get("regularMarketPrice", 0))
        prev  = float(meta.get("chartPreviousClose", price))
        chg   = round(price - prev, 4)
        pct   = round(chg / prev * 100, 2) if prev else 0
        return {"price": price, "change": chg, "change_pct": pct, "source": "Yahoo"}
    except Exception as e:
        logger.debug(f"Yahoo fetch {yahoo_sym} failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  来源 3：东方财富
# ══════════════════════════════════════════════════════════════

def _fetch_em(em_symbol: str, timeout: int = 10) -> dict | None:
    try:
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            "secid":  f"113.{em_symbol}",
            "fields": "f43,f170,f171,f14",
            "ut":     "fa5fd1943c7b386f172d6893dbfba10b",
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Referer":    "https://quote.eastmoney.com/",
        }
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        d = r.json().get("data", {})
        if not d or d.get("f43") in (None, "-"):
            return None
        price = float(d["f43"]) / 100
        chg   = float(d.get("f170", 0)) / 100
        pct   = float(d.get("f171", 0)) / 100
        return {"price": price, "change": chg, "change_pct": pct, "source": "EastMoney"}
    except Exception as e:
        logger.debug(f"EM fetch {em_symbol} failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════

class CommodityFetcher:
    def __init__(self):
        self._cache: dict      = {}
        self._last_fetch: float = 0
        self._lock             = threading.Lock()
        self._ttl              = 300   # 5 分钟缓存

    def fetch_all(self) -> list[dict]:
        """
        拉取所有大宗商品数据，返回列表。
        优先级：华尔街见闻 → Yahoo Finance → 东方财富 → 静态兜底
        """
        now = time.time()
        with self._lock:
            if self._cache and (now - self._last_fetch) < self._ttl:
                return list(self._cache.values())

        # ── 预热：批量拉取华尔街见闻 ────────────────────────
        wsn_symbols = [c["wsn"] for c in COMMODITY_CONFIG if c.get("wsn")]
        wsn_batch   = _fetch_wsn_batch(wsn_symbols) if wsn_symbols else {}

        results = []
        for cfg in COMMODITY_CONFIG:
            code     = cfg["code"]
            wsn_sym  = cfg.get("wsn")
            yahoo    = cfg.get("yahoo")
            em_sym   = cfg.get("em_symbol")
            unit     = cfg["unit"]
            category = cfg["category"]

            quote = None

            # 1. 华尔街见闻（batch 结果）
            if wsn_sym and wsn_sym in wsn_batch:
                quote = wsn_batch[wsn_sym]

            # 2. 华尔街见闻 single（batch 未命中时补抓）
            if quote is None and wsn_sym:
                quote = _fetch_wsn_single(wsn_sym)

            # 3. Yahoo Finance
            if quote is None and yahoo:
                quote = _fetch_yahoo(yahoo)

            # 4. 东方财富（国内品种）
            if quote is None and em_sym:
                quote = _fetch_em(em_sym)

            # 5. 静态兜底
            if quote is None:
                fb    = _FALLBACK.get(code, {"price": 0, "change": 0, "change_pct": 0})
                quote = {**fb, "source": "fallback"}

            record = {
                "code":       code,
                "name":       cfg["name"],
                "price":      round(float(quote["price"]), 4),
                "change":     round(float(quote["change"]), 4),
                "change_pct": round(float(quote["change_pct"]), 2),
                "unit":       unit,
                "category":   category,
                "source":     quote.get("source", "unknown"),
                "updated_at": datetime.datetime.now().isoformat(),
            }
            results.append(record)
            logger.debug(f"商品 [{code}] {cfg['name']} = {record['price']} ({record['source']})")

        with self._lock:
            self._cache      = {r["code"]: r for r in results}
            self._last_fetch = now

        return results

    def get_cached(self) -> list[dict]:
        """直接返回缓存，无缓存时触发一次实时拉取"""
        with self._lock:
            if self._cache:
                return list(self._cache.values())
        return self.fetch_all()

    def format_for_prompt(self) -> str:
        """格式化为 AI prompt 段落"""
        data = self.get_cached()
        if not data:
            return ""
        lines = ["【全球大宗商品最新行情（华尔街见闻 / Yahoo Finance）】"]
        for r in data:
            sign = "+" if r["change_pct"] >= 0 else ""
            lines.append(
                f"  {r['name']}（{r['code']}）：{r['price']} {r['unit']}  "
                f"{sign}{r['change_pct']}%  来源：{r['source']}"
            )
        return "\n".join(lines)


# 单例
commodity_fetcher = CommodityFetcher()
