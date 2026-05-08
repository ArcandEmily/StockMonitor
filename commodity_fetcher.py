"""
commodity_fetcher.py  (华尔街见闻正式版)
─────────────────────────────────────────
真实 API 来源（已抓包确认）：
  https://api-ddc-wscn.awtmt.com/market/real
  无需登录，无需 token，公开可访问

数据来源优先级：
  1. 华尔街见闻 (api-ddc-wscn.awtmt.com) —— 国际大宗商品
  2. akshare                              —— 国内期货（螺纹钢/铁矿石等）
  3. 静态兜底                             —— 所有来源失败时保证页面不空白
"""

import time
import datetime
import threading
import requests
from loguru import logger

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

# ══════════════════════════════════════════════════════════════
#  华尔街见闻品种映射
#  格式: 我们的code → (wsn_prod_code, 中文名, 单位, 分类)
# ══════════════════════════════════════════════════════════════
WSN_MAP = {
    "CL":    ("USCL.OTC",   "WTI原油",    "USD/桶",     "能源"),
    "UKOIL": ("UKOIL.OTC",  "布伦特原油", "USD/桶",     "能源"),
    "NG":    ("USNG.OTC",   "天然气",     "USD/MMBtu",  "能源"),
    "GC":    ("XAUUSD.OTC", "现货黄金",   "USD/盎司",   "贵金属"),
    "SI":    ("XAGUSD.OTC", "现货白银",   "USD/盎司",   "贵金属"),
    "PL":    ("USPL.OTC",   "纽约铂金",   "USD/盎司",   "贵金属"),
    "HG":    ("UKCA.OTC",   "伦敦期铜",   "USD/吨",     "工业金属"),
    "ALI":   ("UKAH.OTC",   "伦敦期铝",   "USD/吨",     "工业金属"),
    "NI":    ("UKNI.OTC",   "伦敦期镍",   "USD/吨",     "工业金属"),
    "ZN":    ("UKZS.OTC",   "伦敦期锌",   "USD/吨",     "工业金属"),
    "ZC":    ("USZC.OTC",   "美玉米",     "美分/蒲式耳","农产品"),
    "ZS":    ("USZS.OTC",   "美大豆",     "美分/蒲式耳","农产品"),
    "ZW":    ("USZW.OTC",   "美小麦",     "美分/蒲式耳","农产品"),
    "SB":    ("USYO.OTC",   "美糖",       "美分/磅",    "农产品"),
}

# 国内期货（WSN 无此数据，用 akshare 补充）
AK_MAP = {
    "RB": ("RB0", "螺纹钢", "元/吨",  "黑色系"),
    "I":  ("I0",  "铁矿石", "元/吨",  "黑色系"),
    "SC": ("SC0", "上海原油","元/桶", "能源"),
}

# 静态兜底（所有来源失败时使用）
_FALLBACK = {
    "CL":    {"price": 101.24,  "change": -1.03,  "change_pct": -1.01},
    "UKOIL": {"price": 108.85,  "change": -1.02,  "change_pct": -0.93},
    "NG":    {"price": 3.061,   "change": -0.011, "change_pct": -0.36},
    "GC":    {"price": 4610.26, "change": 52.71,  "change_pct": 1.16},
    "SI":    {"price": 74.28,   "change": 1.45,   "change_pct": 1.99},
    "PL":    {"price": 1992.2,  "change": 16.9,   "change_pct": 0.86},
    "HG":    {"price": 13187.0, "change": 86.5,   "change_pct": 0.66},
    "ALI":   {"price": 3564.0,  "change": -10.0,  "change_pct": -0.28},
    "NI":    {"price": 19630.0, "change": -5.0,   "change_pct": -0.03},
    "ZN":    {"price": 3382.0,  "change": 23.5,   "change_pct": 0.70},
    "ZC":    {"price": 506.25,  "change": -1.0,   "change_pct": -0.20},
    "ZS":    {"price": 1213.75, "change": 2.25,   "change_pct": 0.19},
    "ZW":    {"price": 625.5,   "change": -2.25,  "change_pct": -0.36},
    "SB":    {"price": 15.37,   "change": 0.08,   "change_pct": 0.52},
    "RB":    {"price": 3285.0,  "change": -15.0,  "change_pct": -0.45},
    "I":     {"price": 812.0,   "change": 6.0,    "change_pct": 0.74},
    "SC":    {"price": 607.0,   "change": -3.5,   "change_pct": -0.57},
}

WSN_URL = "https://api-ddc-wscn.awtmt.com/market/real"
WSN_FIELDS = "symbol,prod_code,prod_name,prod_en_name,preclose_px,price_precision,open_px,high_px,low_px,week_52_high,week_52_low,update_time,last_px,px_change,px_change_rate,market_type,trade_status,securities_type"

_WSN_CACHE: dict = {}
_WSN_CACHE_TS: float = 0
_WSN_TTL = 120   # 2 分钟缓存

_AK_CACHE: dict = {}
_AK_CACHE_TS: float = 0
_AK_TTL = 180


# ══════════════════════════════════════════════════════════════
#  来源 1：华尔街见闻（国际大宗）
# ══════════════════════════════════════════════════════════════

def _fetch_wsn_batch() -> dict:
    """
    一次性拉取所有 WSN 品种，返回
    {我们的code: {price, change, change_pct, source, name}}
    """
    global _WSN_CACHE, _WSN_CACHE_TS
    now = time.time()
    if _WSN_CACHE and (now - _WSN_CACHE_TS) < _WSN_TTL:
        return _WSN_CACHE

    # 构造 prod_code 列表
    wsn_codes = ",".join(v[0] for v in WSN_MAP.values())
    # 建立反查表: wsn_prod_code → 我们的code
    reverse = {v[0]: k for k, v in WSN_MAP.items()}

    try:
        r = requests.get(
            WSN_URL,
            params={"prod_code": wsn_codes, "fields": WSN_FIELDS},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://wallstreetcn.com/",
                "Accept": "application/json",
            },
            timeout=10,
        )
        data = r.json()
        if data.get("code") != 20000:
            logger.warning(f"WSN 返回异常: {data.get('message')}")
            return {}

        fields = data["data"]["fields"]   # 字段名列表
        snapshot = data["data"]["snapshot"]  # {prod_code: [values...]}

        # 建立字段索引
        idx = {f: i for i, f in enumerate(fields)}
        i_last   = idx["last_px"]
        i_change = idx["px_change"]
        i_pct    = idx["px_change_rate"]

        result = {}
        for wsn_code, values in snapshot.items():
            our_code = reverse.get(wsn_code)
            if not our_code:
                continue
            try:
                price = float(values[i_last]  or 0)
                chg   = float(values[i_change] or 0)
                pct   = float(values[i_pct]   or 0)
                if price <= 0:
                    continue
                result[our_code] = {
                    "price":      round(price, 4),
                    "change":     round(chg,   4),
                    "change_pct": round(pct,   4),
                    "source":     "wallstreetcn",
                }
            except (TypeError, ValueError, IndexError) as e:
                logger.debug(f"WSN 解析 {wsn_code} 失败: {e}")

        if result:
            _WSN_CACHE = result
            _WSN_CACHE_TS = now
            logger.info(f"[WSN] 获取 {len(result)} 个品种")
        return result

    except Exception as e:
        logger.warning(f"WSN 请求失败: {e}")
        return {}


# ══════════════════════════════════════════════════════════════
#  来源 2：akshare（国内期货）
# ══════════════════════════════════════════════════════════════

def _fetch_akshare_batch() -> dict:
    global _AK_CACHE, _AK_CACHE_TS
    now = time.time()
    if _AK_CACHE and (now - _AK_CACHE_TS) < _AK_TTL:
        return _AK_CACHE
    if not HAS_AKSHARE:
        return {}

    result = {}
    for our_code, (ak_sym, _, _, _) in AK_MAP.items():
        try:
            df = ak.futures_zh_realtime(symbol=ak_sym)
            if df is None or df.empty:
                continue
            row  = df.iloc[0]
            cols = list(row.index)

            def get_val(keywords):
                for c in cols:
                    if any(k in c for k in keywords):
                        try:
                            v = str(row[c]).replace('%','').replace(',','')
                            return float(v) if v not in ('', '-', 'nan') else 0.0
                        except:
                            pass
                return 0.0

            price = get_val(['最新','现价','last','close'])
            prev  = get_val(['昨结','昨收','prev','settle'])
            chg   = get_val(['涨跌额','chg']) if '幅' not in str(cols) else 0.0
            pct   = get_val(['涨跌幅','pct','percent'])

            if price <= 0:
                continue
            if chg == 0 and prev > 0:
                chg = round(price - prev, 4)
            if pct == 0 and prev > 0:
                pct = round(chg / prev * 100, 2)

            result[our_code] = {
                "price":      round(price, 4),
                "change":     round(chg,   4),
                "change_pct": round(pct,   2),
                "source":     "akshare",
            }
        except Exception as e:
            logger.debug(f"akshare {ak_sym} 失败: {e}")

    if result:
        _AK_CACHE = result
        _AK_CACHE_TS = now
        logger.info(f"[akshare] 获取 {len(result)} 个品种")
    return result


# ══════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════

# 完整品种列表（WSN 国际 + akshare 国内）
ALL_CODES_CONFIG = {
    **{k: {"name": v[1], "unit": v[2], "category": v[3]}
       for k, v in WSN_MAP.items()},
    **{k: {"name": v[1], "unit": v[2], "category": v[3]}
       for k, v in AK_MAP.items()},
}


class CommodityFetcher:
    def __init__(self):
        self._cache: dict       = {}
        self._last_fetch: float = 0
        self._lock              = threading.Lock()
        self._ttl               = 300   # 5 分钟缓存

    def fetch_all(self) -> list[dict]:
        now = time.time()
        with self._lock:
            if self._cache and (now - self._last_fetch) < self._ttl:
                return list(self._cache.values())

        # 并发拉取两个来源
        wsn_data = _fetch_wsn_batch()
        ak_data  = _fetch_akshare_batch()

        results = []
        for code, meta in ALL_CODES_CONFIG.items():
            quote = wsn_data.get(code) or ak_data.get(code)

            if quote is None:
                fb    = _FALLBACK.get(code, {"price": 0, "change": 0, "change_pct": 0})
                quote = {**fb, "source": "fallback"}

            record = {
                "code":       code,
                "name":       meta["name"],
                "price":      round(float(quote["price"]),      4),
                "change":     round(float(quote["change"]),     4),
                "change_pct": round(float(quote["change_pct"]), 4),
                "unit":       meta["unit"],
                "category":   meta["category"],
                "source":     quote.get("source", "unknown"),
                "updated_at": datetime.datetime.now().isoformat(),
            }
            results.append(record)
            logger.info(
                f"[{code:6s}] {meta['name']:8s} = {record['price']:>10.4f} {meta['unit']}"
                f"  {record['change_pct']:+.2f}%  [{record['source']}]"
            )

        with self._lock:
            self._cache      = {r["code"]: r for r in results}
            self._last_fetch = now

        return results

    def get_cached(self) -> list[dict]:
        with self._lock:
            if self._cache:
                return list(self._cache.values())
        return self.fetch_all()

    def format_for_prompt(self) -> str:
        data = self.get_cached()
        if not data:
            return ""
        lines = ["【全球大宗商品最新行情（华尔街见闻）】"]
        for r in data:
            sign = "+" if r["change_pct"] >= 0 else ""
            lines.append(
                f"  {r['name']}（{r['code']}）：{r['price']} {r['unit']}"
                f"  {sign}{r['change_pct']:.2f}%"
            )
        return "\n".join(lines)


commodity_fetcher = CommodityFetcher()
