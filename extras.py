"""
extras.py — 辅助数据：大宗商品 / 板块 / 资金 / 财报日历
─────────────────────────────────────────────────────
合并自旧版四个模块：
  - commodity_fetcher.py → 全球大宗商品（华尔街见闻 + akshare）
  - sector_fetcher.py    → 板块联动（个股所属行业 + 同板块涨跌）
  - capital_fetcher.py   → 北向资金 + 融资融券
  - calendar_fetcher.py  → 财报日历 + 分红除权

对外接口保持兼容：
  commodity_fetcher                ← 旧 commodity_fetcher（实例）
  get_sector_info(code)            ← 旧 sector_fetcher
  get_northbound(), get_margin(c)  ← 旧 capital_fetcher
  get_upcoming_events(codes)       ← 旧 calendar_fetcher
"""

import time
import datetime
import inspect
import threading
import requests
from loguru import logger

try:
    import akshare as ak
    HAS_AK = True
except ImportError:
    HAS_AK = False


# ════════════════════════════════════════════════════════════════
# Part 1：全球大宗商品（华尔街见闻 + akshare）
# ════════════════════════════════════════════════════════════════

# 华尔街见闻品种映射
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

AK_MAP = {
    "RB": ("RB0", "螺纹钢",  "元/吨", "黑色系"),
    "I":  ("I0",  "铁矿石",  "元/吨", "黑色系"),
    "SC": ("SC0", "上海原油","元/桶", "能源"),
}

_FALLBACK_COMMODITY = {
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
WSN_FIELDS = ("symbol,prod_code,prod_name,prod_en_name,preclose_px,price_precision,"
              "open_px,high_px,low_px,week_52_high,week_52_low,update_time,"
              "last_px,px_change,px_change_rate,market_type,trade_status,securities_type")

_WSN_CACHE: dict = {}
_WSN_CACHE_TS: float = 0
_WSN_TTL = 120

_AK_COMM_CACHE: dict = {}
_AK_COMM_TS: float = 0
_AK_COMM_TTL = 180


def _fetch_wsn_batch() -> dict:
    global _WSN_CACHE, _WSN_CACHE_TS
    now = time.time()
    if _WSN_CACHE and (now - _WSN_CACHE_TS) < _WSN_TTL:
        return _WSN_CACHE

    wsn_codes = ",".join(v[0] for v in WSN_MAP.values())
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

        fields = data["data"]["fields"]
        snapshot = data["data"]["snapshot"]

        idx = {f: i for i, f in enumerate(fields)}
        i_last, i_change, i_pct = idx["last_px"], idx["px_change"], idx["px_change_rate"]

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


def _fetch_akshare_commodity_batch() -> dict:
    global _AK_COMM_CACHE, _AK_COMM_TS
    now = time.time()
    if _AK_COMM_CACHE and (now - _AK_COMM_TS) < _AK_COMM_TTL:
        return _AK_COMM_CACHE
    if not HAS_AK:
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
                            v = str(row[c]).replace('%', '').replace(',', '')
                            return float(v) if v not in ('', '-', 'nan') else 0.0
                        except Exception:
                            pass
                return 0.0

            price = get_val(['最新', '现价', 'last', 'close'])
            prev  = get_val(['昨结', '昨收', 'prev', 'settle'])
            chg   = get_val(['涨跌额', 'chg']) if '幅' not in str(cols) else 0.0
            pct   = get_val(['涨跌幅', 'pct', 'percent'])

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
        _AK_COMM_CACHE = result
        _AK_COMM_TS = now
        logger.info(f"[akshare] 获取 {len(result)} 个品种")
    return result


ALL_COMMODITIES_CONFIG = {
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
        ak_data  = _fetch_akshare_commodity_batch()

        results = []
        for code, meta in ALL_COMMODITIES_CONFIG.items():
            quote = wsn_data.get(code) or ak_data.get(code)

            if quote is None:
                fb    = _FALLBACK_COMMODITY.get(code, {"price": 0, "change": 0, "change_pct": 0})
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


# 全局单例（与原 commodity_fetcher.py 保持接口一致）
commodity_fetcher = CommodityFetcher()


# ════════════════════════════════════════════════════════════════
# Part 2：板块联动（原 sector_fetcher.py）
# ════════════════════════════════════════════════════════════════

_sector_cache: dict = {}
_sector_lock        = threading.Lock()
_SECTOR_TTL         = 3600


def get_sector_info(code: str) -> dict:
    """
    返回个股板块联动信息：
      {industry, industry_change_pct, peers: [...], updated_at, source}
    """
    with _sector_lock:
        cached = _sector_cache.get(code)
        if cached and (time.time() - cached.get("_ts", 0)) < _SECTOR_TTL:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

    result = _fetch_sector(code)

    with _sector_lock:
        _sector_cache[code] = {**result, "_ts": time.time()}

    return result


def _fetch_sector(code: str) -> dict:
    empty = {"industry": None, "industry_change_pct": None, "peers": [],
             "updated_at": datetime.datetime.now().isoformat(), "source": "fallback"}

    if not HAS_AK:
        return empty

    industry = None
    try:
        info_df = ak.stock_individual_info_em(symbol=code)
        row = info_df[info_df["item"] == "行业"]
        if not row.empty:
            industry = str(row.iloc[0]["value"]).strip()
    except Exception as e:
        logger.debug(f"[sector] 获取 {code} 行业信息失败: {e}")
        return empty

    if not industry:
        return empty

    industry_pct = None
    try:
        boards = ak.stock_board_industry_name_em()
        matched = boards[boards["板块名称"].str.contains(industry[:4], na=False)]
        if not matched.empty:
            industry_pct = float(matched.iloc[0].get("涨跌幅", 0) or 0)
    except Exception as e:
        logger.debug(f"[sector] 获取板块涨跌失败: {e}")

    peers = []
    try:
        cons_df = ak.stock_board_industry_cons_em(symbol=industry)
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


# ════════════════════════════════════════════════════════════════
# Part 3：北向资金 + 融资融券（原 capital_fetcher.py）
# ════════════════════════════════════════════════════════════════

_north_cache: dict = {}
_north_ts: float   = 0
_north_lock        = threading.Lock()
_NORTH_TTL         = 1800

_margin_cache: dict = {}
_margin_lock        = threading.Lock()
_MARGIN_TTL         = 3600


def get_northbound() -> dict:
    """北向资金近 10 日数据"""
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
        df = ak.stock_hsgt_hist_em(symbol="北向资金")
        if df is None or df.empty:
            return empty

        df = df.tail(10)
        history = []
        net_col = next((c for c in ["当日成交净买额", "当日净买额", "net_buy"] if c in df.columns), None)
        cum_col = next((c for c in ["历史累计净买额", "累计净买额"] if c in df.columns), None)
        if not net_col:
            logger.warning(f"[北向] 找不到净买额列，实际列名: {list(df.columns)}")
            return empty

        def _safe_num(x):
            try:
                v = float(x)
                if v != v:  # NaN
                    return None
                return v
            except (TypeError, ValueError):
                return None

        for _, row in df.iterrows():
            raw_net = _safe_num(row.get(net_col))
            if raw_net is None:
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


def get_margin(code: str) -> dict:
    """个股融资融券数据"""
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

    today = datetime.date.today()
    df, used_date = None, None
    for back in range(0, 8):
        d = today - datetime.timedelta(days=back)
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
        code_col = next((c for c in code_col_candidates if c in df.columns), None)
        if not code_col:
            logger.warning(f"[融资融券] {code} 找不到代码列，实际列: {list(df.columns)}")
            return empty

        row = df[df[code_col].astype(str).str.zfill(6) == code.zfill(6)]
        if row.empty:
            logger.info(f"[融资融券] {code} 在 {used_date} 数据中未找到")
            return empty

        r = row.iloc[0]
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


# ════════════════════════════════════════════════════════════════
# Part 4：财报日历（原 calendar_fetcher.py）
# ════════════════════════════════════════════════════════════════

_calendar_cache: dict = {}
_calendar_ts: float   = 0
_calendar_lock        = threading.Lock()
_CALENDAR_TTL         = 21600

_failed_endpoints: set = set()
_failed_lock           = threading.Lock()


def _safe_call_ak(fn, **kwargs):
    """安全调用 akshare 函数：自动过滤参数 + 失败缓存"""
    fn_name = getattr(fn, "__name__", str(fn))
    with _failed_lock:
        if fn_name in _failed_endpoints:
            return None

    try:
        sig = inspect.signature(fn)
        accepted = {name for name, p in sig.parameters.items()
                    if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY, p.VAR_KEYWORD)}
        if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            filtered = kwargs
        else:
            filtered = {k: v for k, v in kwargs.items() if k in accepted}
        dropped = set(kwargs) - set(filtered)
        if dropped:
            logger.debug(f"[日历] {fn_name} 不接受参数 {dropped}，已丢弃")
    except (ValueError, TypeError):
        filtered = kwargs

    try:
        return fn(**filtered)
    except TypeError as e:
        logger.info(f"[日历] {fn_name} 签名不匹配，已禁用：{e}")
        with _failed_lock:
            _failed_endpoints.add(fn_name)
        return None
    except Exception as e:
        logger.debug(f"[日历] {fn_name} 调用失败: {e}")
        return None


def get_upcoming_events(codes: list) -> list:
    """返回监控股票的 90 天内重要事件列表（按 days_left 升序）"""
    global _calendar_ts
    key = ",".join(sorted(codes))

    with _calendar_lock:
        if _calendar_cache.get(key) is not None and (time.time() - _calendar_ts) < _CALENDAR_TTL:
            return list(_calendar_cache[key])

    result = _fetch_events(codes)

    with _calendar_lock:
        _calendar_cache[key] = result
        _calendar_ts = time.time()

    return result


def _parse_date(raw):
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.datetime.strptime(s[:10] if "-" in s or "/" in s else s[:8], fmt).date()
        except ValueError:
            continue
    return None


def _make_event(code, name, event_type, event_date, today) -> dict:
    days_left = (event_date - today).days
    return {
        "code":      code,
        "name":      name or code,
        "event":     event_type,
        "date":      event_date.isoformat(),
        "days_left": days_left,
        "status":    "today" if days_left == 0
                     else "overdue" if days_left < 0
                     else "upcoming",
    }


def _fetch_events(codes: list) -> list:
    if not HAS_AK:
        return []

    today   = datetime.date.today()
    events  = []
    codes_s = set(codes)

    # ── 1. 财报披露日历 ─────────────────────────────────
    df = _safe_call_ak(ak.stock_report_disclosure, market="沪深A股")
    if df is not None and not df.empty:
        col_code = next((c for c in ["股票代码", "代码", "证券代码"] if c in df.columns), None)
        col_name = next((c for c in ["股票简称", "名称", "证券简称"] if c in df.columns), None)
        col_date = next((c for c in ["最新预约/披露日期", "预约披露日期", "披露日期", "实际披露日期", "日期"]
                         if c in df.columns), None)
        col_type = next((c for c in ["报告类型", "报告期", "类型"] if c in df.columns), None)

        if col_code and col_date:
            for _, row in df.iterrows():
                code = str(row.get(col_code, "")).zfill(6)
                if code not in codes_s:
                    continue
                event_date = _parse_date(row.get(col_date))
                if not event_date:
                    continue
                days_left = (event_date - today).days
                if not (-7 <= days_left <= 90):
                    continue
                rtype = str(row.get(col_type, "财报披露")).strip() if col_type else "财报披露"
                events.append(_make_event(
                    code, str(row.get(col_name, "")) if col_name else "", rtype, event_date, today
                ))
        else:
            logger.info(f"[日历] stock_report_disclosure 返回列不识别: {list(df.columns)[:8]}")

    # ── 2. 分红除权信息 ─────────────────────────────────
    for code in codes:
        endpoint_key = f"stock_fhps_detail_em:{code}"
        with _failed_lock:
            if endpoint_key in _failed_endpoints:
                continue

        df = _safe_call_ak(getattr(ak, "stock_fhps_detail_em", None), symbol=code) \
             if hasattr(ak, "stock_fhps_detail_em") else None

        if df is None or df.empty:
            df = _safe_call_ak(ak.stock_dividend_cninfo, symbol=code)

        if df is None or df.empty:
            with _failed_lock:
                _failed_endpoints.add(endpoint_key)
            continue

        date_col = next((c for c in ["除权除息日", "股权登记日", "派息日",
                                      "实施公告日", "分红日期", "实施日期"]
                         if c in df.columns), None)
        if not date_col:
            with _failed_lock:
                _failed_endpoints.add(endpoint_key)
            continue

        for _, row in df.tail(5).iterrows():
            event_date = _parse_date(row.get(date_col))
            if not event_date:
                continue
            days_left = (event_date - today).days
            if -7 <= days_left <= 90:
                events.append(_make_event(code, code, "分红除权", event_date, today))

    events.sort(key=lambda x: x["days_left"])
    if events:
        logger.info(f"[日历] 共获取 {len(events)} 个事件")
    else:
        logger.info("[日历] 未获取到 90 天内事件（可能非交易日或接口暂不可用）")
    return events
