"""
commodity_fetcher.py  (华尔街见闻完整版)
真实 API：https://api-ddc-wscn.awtmt.com/market/real
无需 token，直接 GET，已抓包确认
"""

import time, datetime, threading, requests
from loguru import logger

try:
    import akshare as ak
    HAS_AKSHARE = True
except ImportError:
    HAS_AKSHARE = False

# ══════════════════════════════════════════════════════════════
#  华尔街见闻完整品种表
#  格式: 内部code → (wsn_prod_code, 中文名, 单位, 分类)
# ══════════════════════════════════════════════════════════════
WSN_MAP = {
    # ── 能源 ─────────────────────────────────────────────────
    "CL":    ("USCL.OTC",   "WTI原油",      "USD/桶",      "能源"),
    "UKOIL": ("UKOIL.OTC",  "布伦特原油",   "USD/桶",      "能源"),
    "NG":    ("USNG.OTC",   "天然气",       "USD/MMBtu",   "能源"),

    # ── 贵金属 ───────────────────────────────────────────────
    "GC":    ("XAUUSD.OTC", "现货黄金",     "USD/盎司",    "贵金属"),
    "USGC":  ("USGC.OTC",   "纽约金CFD",   "USD/盎司",    "贵金属"),
    "SI":    ("XAGUSD.OTC", "现货白银",     "USD/盎司",    "贵金属"),
    "USSI":  ("USSI.OTC",   "纽约银",       "USD/盎司",    "贵金属"),
    "PL":    ("USPL.OTC",   "纽约铂金",     "USD/盎司",    "贵金属"),
    "PA":    ("USPA.OTC",   "纽约钯金",     "USD/盎司",    "贵金属"),
    "PT":    ("PT9995.SGE", "上海铂金9995", "元/克",       "贵金属"),

    # ── 工业金属 ─────────────────────────────────────────────
    "HG":    ("USHG.OTC",   "纽约铜",       "USD/磅",      "工业金属"),
    "UKCA":  ("UKCA.OTC",   "伦敦期铜",     "USD/吨",      "工业金属"),
    "ALI":   ("UKAH.OTC",   "伦敦期铝",     "USD/吨",      "工业金属"),
    "NI":    ("UKNI.OTC",   "伦敦期镍",     "USD/吨",      "工业金属"),
    "ZN":    ("UKZS.OTC",   "伦敦期锌",     "USD/吨",      "工业金属"),
    "PB":    ("UKPB.OTC",   "伦敦期铅",     "USD/吨",      "工业金属"),
    "SN":    ("UKSN.OTC",   "伦敦期锡",     "USD/吨",      "工业金属"),

    # ── 农产品 ───────────────────────────────────────────────
    "ZC":    ("USZC.OTC",   "美玉米",       "美分/蒲式耳", "农产品"),
    "ZS":    ("USZS.OTC",   "美大豆",       "美分/蒲式耳", "农产品"),
    "ZW":    ("USZW.OTC",   "美小麦",       "美分/蒲式耳", "农产品"),
    "ZL":    ("USZL.OTC",   "美豆油",       "美分/磅",     "农产品"),
    "SB":    ("USYO.OTC",   "美糖",         "美分/磅",     "农产品"),
    "CT":    ("USCT.OTC",   "美棉花",       "美分/磅",     "农产品"),
    "CC":    ("USCC.OTC",   "美可可",       "USD/吨",      "农产品"),
    "LH":    ("LHC.OTC",    "美瘦猪肉",     "USD/磅",      "农产品"),

    # ── 外汇 ─────────────────────────────────────────────────
    "DXY":    ("DXY.OTC",    "美元指数",    "点",          "外汇"),
    "EURUSD": ("EURUSD.OTC", "欧元/美元",   "汇率",        "外汇"),
    "GBPUSD": ("GBPUSD.OTC", "英镑/美元",   "汇率",        "外汇"),
    "USDJPY": ("USDJPY.OTC", "美元/日元",   "汇率",        "外汇"),
    "USDCNH": ("USDCNH.OTC", "离岸人民币",  "汇率",        "外汇"),
    "AUDUSD": ("AUDUSD.OTC", "澳元/美元",   "汇率",        "外汇"),
    "USDCAD": ("USDCAD.OTC", "美元/加元",   "汇率",        "外汇"),
    "USDCHF": ("USDCHF.OTC", "美元/瑞郎",   "汇率",        "外汇"),
    "NZDUSD": ("NZDUSD.OTC", "纽元/美元",   "汇率",        "外汇"),
}

# 国内期货（WSN 无此数据，akshare 补充）
AK_MAP = {
    "RB": ("RB0", "螺纹钢",   "元/吨",  "黑色系"),
    "I":  ("I0",  "铁矿石",   "元/吨",  "黑色系"),
    "SC": ("SC0", "上海原油", "元/桶",  "能源"),
    "CU": ("CU0", "沪铜",     "元/吨",  "工业金属"),
    "AL": ("AL0", "沪铝",     "元/吨",  "工业金属"),
    "AU": ("AU0", "沪金",     "元/克",  "贵金属"),
    "AG": ("AG0", "沪银",     "元/千克","贵金属"),
}

# 静态兜底（保证页面永不空白，价格为最近参考值）
_FALLBACK = {
    "CL":    {"price":101.24,  "change":-1.03,  "change_pct":-1.01},
    "UKOIL": {"price":108.85,  "change":-1.02,  "change_pct":-0.93},
    "NG":    {"price":3.061,   "change":-0.011, "change_pct":-0.36},
    "GC":    {"price":4610.26, "change":52.71,  "change_pct":1.16},
    "USGC":  {"price":4621.2,  "change":52.7,   "change_pct":1.15},
    "SI":    {"price":74.28,   "change":1.45,   "change_pct":1.99},
    "USSI":  {"price":33.15,   "change":-0.22,  "change_pct":-0.66},
    "PL":    {"price":1992.2,  "change":16.9,   "change_pct":0.86},
    "PA":    {"price":980.0,   "change":5.0,    "change_pct":0.51},
    "PT":    {"price":489.7,   "change":-0.3,   "change_pct":-0.06},
    "HG":    {"price":4.72,    "change":0.04,   "change_pct":0.86},
    "UKCA":  {"price":13187.0, "change":86.5,   "change_pct":0.66},
    "ALI":   {"price":3564.0,  "change":-10.0,  "change_pct":-0.28},
    "NI":    {"price":19630.0, "change":-5.0,   "change_pct":-0.03},
    "ZN":    {"price":3382.0,  "change":23.5,   "change_pct":0.70},
    "PB":    {"price":1973.0,  "change":0.5,    "change_pct":0.03},
    "SN":    {"price":50285.0, "change":445.0,  "change_pct":0.89},
    "ZC":    {"price":506.25,  "change":-1.0,   "change_pct":-0.20},
    "ZS":    {"price":1213.75, "change":2.25,   "change_pct":0.19},
    "ZW":    {"price":625.5,   "change":-2.25,  "change_pct":-0.36},
    "ZL":    {"price":45.2,    "change":0.3,    "change_pct":0.67},
    "SB":    {"price":15.37,   "change":0.08,   "change_pct":0.52},
    "CT":    {"price":68.5,    "change":-0.4,   "change_pct":-0.58},
    "CC":    {"price":9200.0,  "change":85.0,   "change_pct":0.93},
    "LH":    {"price":84.95,   "change":-0.73,  "change_pct":-0.85},
    "DXY":   {"price":100.85,  "change":-0.35,  "change_pct":-0.35},
    "EURUSD":{"price":1.1285,  "change":0.0032, "change_pct":0.28},
    "GBPUSD":{"price":1.3574,  "change":0.0036, "change_pct":0.27},
    "USDJPY":{"price":143.52,  "change":-0.85,  "change_pct":-0.59},
    "USDCNH":{"price":7.2180,  "change":0.0085, "change_pct":0.12},
    "AUDUSD":{"price":0.6415,  "change":0.0025, "change_pct":0.39},
    "USDCAD":{"price":1.3825,  "change":-0.005, "change_pct":-0.36},
    "USDCHF":{"price":0.8935,  "change":0.002,  "change_pct":0.22},
    "NZDUSD":{"price":0.5915,  "change":0.0018, "change_pct":0.30},
    "RB":    {"price":3285.0,  "change":-15.0,  "change_pct":-0.45},
    "I":     {"price":812.0,   "change":6.0,    "change_pct":0.74},
    "SC":    {"price":607.0,   "change":-3.5,   "change_pct":-0.57},
    "CU":    {"price":78500.0, "change":350.0,  "change_pct":0.45},
    "AL":    {"price":20200.0, "change":-80.0,  "change_pct":-0.39},
    "AU":    {"price":658.0,   "change":2.5,    "change_pct":0.38},
    "AG":    {"price":8350.0,  "change":-55.0,  "change_pct":-0.65},
}

WSN_URL    = "https://api-ddc-wscn.awtmt.com/market/real"
WSN_FIELDS = ("symbol,prod_code,prod_name,prod_en_name,preclose_px,price_precision,"
               "open_px,high_px,low_px,week_52_high,week_52_low,update_time,"
               "last_px,px_change,px_change_rate,market_type,trade_status,securities_type")

_WSN_CACHE: dict = {}
_WSN_CACHE_TS: float = 0
_WSN_TTL = 120

_AK_CACHE: dict = {}
_AK_CACHE_TS: float = 0
_AK_TTL = 180


# ──────────────────────────────────────────────────────────────
#  来源 1：华尔街见闻
# ──────────────────────────────────────────────────────────────
def _fetch_wsn_batch() -> dict:
    global _WSN_CACHE, _WSN_CACHE_TS
    now = time.time()
    if _WSN_CACHE and (now - _WSN_CACHE_TS) < _WSN_TTL:
        return _WSN_CACHE

    wsn_codes = ",".join(v[0] for v in WSN_MAP.values())
    reverse   = {v[0]: k for k, v in WSN_MAP.items()}   # wsn_code → 内部code

    try:
        r = requests.get(
            WSN_URL,
            params={"prod_code": wsn_codes, "fields": WSN_FIELDS},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer":    "https://wallstreetcn.com/",
                "Accept":     "application/json",
            },
            timeout=12,
        )
        body = r.json()
        if body.get("code") != 20000:
            logger.warning(f"WSN 返回异常: {body.get('message')}")
            return {}

        fields   = body["data"]["fields"]
        snapshot = body["data"]["snapshot"]

        idx_last   = fields.index("last_px")
        idx_change = fields.index("px_change")
        idx_pct    = fields.index("px_change_rate")

        result = {}
        for wsn_code, values in snapshot.items():
            our_code = reverse.get(wsn_code)
            if not our_code:
                continue
            try:
                price = float(values[idx_last]   or 0)
                chg   = float(values[idx_change] or 0)
                pct   = float(values[idx_pct]    or 0)
                if price <= 0:
                    continue
                result[our_code] = {
                    "price":      round(price, 6),
                    "change":     round(chg,   6),
                    "change_pct": round(pct,   4),
                    "source":     "wallstreetcn",
                }
            except (TypeError, ValueError, IndexError) as e:
                logger.debug(f"WSN 解析 {wsn_code}: {e}")

        if result:
            _WSN_CACHE    = result
            _WSN_CACHE_TS = now
            logger.info(f"[WSN] ✓ 获取 {len(result)}/{len(WSN_MAP)} 个品种")
        return result

    except Exception as e:
        logger.warning(f"[WSN] 请求失败: {e}")
        return {}


# ──────────────────────────────────────────────────────────────
#  来源 2：akshare（国内期货补充）
# ──────────────────────────────────────────────────────────────
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

            def get_val(keywords, exclude=""):
                for c in cols:
                    if any(k in c for k in keywords) and exclude not in c:
                        try:
                            v = str(row[c]).replace('%','').replace(',','')
                            return float(v) if v not in ('','-','nan') else 0.0
                        except: pass
                return 0.0

            price = get_val(['最新','现价','last','close'])
            prev  = get_val(['昨结','昨收','prev','settle'])
            chg   = get_val(['涨跌额','chg'], exclude='幅')
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
            logger.debug(f"akshare {ak_sym}: {e}")

    if result:
        _AK_CACHE    = result
        _AK_CACHE_TS = now
        logger.info(f"[akshare] ✓ 获取 {len(result)} 个品种")
    return result


# ──────────────────────────────────────────────────────────────
#  品种完整配置（WSN + akshare 合并）
# ──────────────────────────────────────────────────────────────
ALL_CODES = {
    **{k: {"name": v[1], "unit": v[2], "category": v[3]} for k, v in WSN_MAP.items()},
    **{k: {"name": v[1], "unit": v[2], "category": v[3]} for k, v in AK_MAP.items()},
}


class CommodityFetcher:
    def __init__(self):
        self._cache: dict       = {}
        self._last_fetch: float = 0
        self._lock              = threading.Lock()
        self._ttl               = 300

    def fetch_all(self) -> list[dict]:
        now = time.time()
        with self._lock:
            if self._cache and (now - self._last_fetch) < self._ttl:
                return list(self._cache.values())

        wsn_data = _fetch_wsn_batch()
        ak_data  = _fetch_akshare_batch()

        results = []
        for code, meta in ALL_CODES.items():
            quote = wsn_data.get(code) or ak_data.get(code)
            if quote is None:
                fb    = _FALLBACK.get(code, {"price":0,"change":0,"change_pct":0})
                quote = {**fb, "source": "fallback"}

            record = {
                "code":       code,
                "name":       meta["name"],
                "price":      round(float(quote["price"]),      6),
                "change":     round(float(quote["change"]),     6),
                "change_pct": round(float(quote["change_pct"]), 4),
                "unit":       meta["unit"],
                "category":   meta["category"],
                "source":     quote.get("source", "unknown"),
                "updated_at": datetime.datetime.now().isoformat(),
            }
            results.append(record)
            logger.debug(
                f"[{code:8s}] {meta['name']:10s} = {record['price']:>12.4f}"
                f"  {record['change_pct']:+.2f}%  [{record['source']}]"
            )

        with self._lock:
            self._cache      = {r["code"]: r for r in results}
            self._last_fetch = now

        src_count = {}
        for r in results:
            src_count[r["source"]] = src_count.get(r["source"], 0) + 1
        logger.info(f"[大宗商品] 共 {len(results)} 个品种 | 来源: {src_count}")

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
        # 按分类分组输出
        from collections import defaultdict
        by_cat = defaultdict(list)
        for r in data:
            by_cat[r["category"]].append(r)
        lines = ["【全球大宗商品 & 外汇最新行情（华尔街见闻）】"]
        for cat, items in by_cat.items():
            lines.append(f"\n  ▸ {cat}")
            for r in items:
                sign = "+" if r["change_pct"] >= 0 else ""
                lines.append(
                    f"    {r['name']}（{r['code']}）：{r['price']} {r['unit']}"
                    f"  {sign}{r['change_pct']:.2f}%"
                )
        return "\n".join(lines)


commodity_fetcher = CommodityFetcher()
