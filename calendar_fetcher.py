"""
calendar_fetcher.py
───────────────────
财报日历 / 重要事件提醒

功能：
  1. 财报披露日历（一季报/半年报/三季报/年报）
  2. 分红除权信息

数据来源：akshare（东方财富/巨潮资讯）
缓存：6 小时（日历变化较慢）

防御性设计：
  - 用 inspect.signature 动态过滤 akshare 函数的关键字参数，
    避免 akshare 改动签名后整个功能挂掉刷日志。
  - 一旦某个接口调用失败，记入 _failed_endpoints，本进程内不再重试，
    避免 N 只股票 × 多种报表类型导致日志刷屏。
"""

import datetime
import inspect
import threading
import time
from loguru import logger

try:
    import akshare as ak
    HAS_AK = True
except ImportError:
    HAS_AK = False

_cache: dict     = {}
_cache_ts: float = 0
_lock            = threading.Lock()
_TTL             = 21600                 # 6 小时

# 本进程内已确认失败的接口端点，跳过避免刷日志
# 例如："stock_report_disclosure" / "stock_dividend_cninfo:600519"
_failed_endpoints: set = set()
_failed_lock           = threading.Lock()


def _safe_call(fn, **kwargs):
    """
    安全调用 akshare 函数：
      - 用 inspect 过滤掉函数不接受的关键字参数
      - 函数级失败缓存：一旦失败就记下来不再重试
    """
    fn_name = getattr(fn, "__name__", str(fn))
    with _failed_lock:
        if fn_name in _failed_endpoints:
            return None

    # 过滤参数
    try:
        sig = inspect.signature(fn)
        accepted = {
            name for name, p in sig.parameters.items()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY, p.VAR_KEYWORD)
        }
        # 如果有 VAR_KEYWORD（**kwargs），全部传；否则只传接受的
        if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            filtered = kwargs
        else:
            filtered = {k: v for k, v in kwargs.items() if k in accepted}
        # 警告丢弃了哪些参数
        dropped = set(kwargs) - set(filtered)
        if dropped:
            logger.debug(f"[日历] {fn_name} 不接受参数 {dropped}，已丢弃")
    except (ValueError, TypeError):
        # 某些 C 实现的函数 inspect 不了，直接传
        filtered = kwargs

    try:
        return fn(**filtered)
    except TypeError as e:
        # 还是签名问题（比如 inspect 拿不到准确签名）
        logger.info(f"[日历] {fn_name} 签名不匹配，已禁用：{e}")
        with _failed_lock:
            _failed_endpoints.add(fn_name)
        return None
    except Exception as e:
        # 网络错误等运行时错误
        logger.debug(f"[日历] {fn_name} 调用失败: {e}")
        return None


def get_upcoming_events(codes: list) -> list:
    """
    返回监控股票的近期重要事件列表（90 天内）。
    按 days_left 升序排列。
    """
    global _cache_ts
    key = ",".join(sorted(codes))

    with _lock:
        if _cache.get(key) is not None and (time.time() - _cache_ts) < _TTL:
            return list(_cache[key])

    result = _fetch_events(codes)

    with _lock:
        _cache[key] = result
        _cache_ts = time.time()

    return result


def _parse_date(raw) -> datetime.date | None:
    """宽松日期解析"""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    # 试 ISO / 紧凑两种格式
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

    # ── 1. 财报披露日历 ──────────────────────────────────────
    # 不再按报表类型分别请求（4 次 → 1 次），只调用一次然后过滤
    df = _safe_call(ak.stock_report_disclosure, market="沪深A股")
    if df is not None and not df.empty:
        # 兼容多种可能的列名
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
                # 报告类型：用接口返回值或回退到通用文案
                rtype = str(row.get(col_type, "财报披露")).strip() if col_type else "财报披露"
                events.append(_make_event(
                    code, str(row.get(col_name, "")) if col_name else "", rtype, event_date, today
                ))
        else:
            logger.info(f"[日历] stock_report_disclosure 返回列不识别: {list(df.columns)[:8]}")

    # ── 2. 分红除权信息 ──────────────────────────────────────
    # 只为监控股票拉取，按 code 缓存失败标记
    for code in codes:
        endpoint_key = f"stock_fhps_detail_em:{code}"
        with _failed_lock:
            if endpoint_key in _failed_endpoints:
                continue

        # 优先尝试 stock_fhps_detail_em（按个股查询，更准），失败回退 stock_dividend_cninfo
        df = _safe_call(getattr(ak, "stock_fhps_detail_em", None), symbol=code) \
             if hasattr(ak, "stock_fhps_detail_em") else None

        if df is None or df.empty:
            df = _safe_call(ak.stock_dividend_cninfo, symbol=code)

        if df is None or df.empty:
            with _failed_lock:
                _failed_endpoints.add(endpoint_key)
            continue

        # 找日期列
        date_col = next((c for c in ["除权除息日", "股权登记日", "派息日",
                                      "实施公告日", "分红日期", "实施日期"]
                         if c in df.columns), None)
        if not date_col:
            with _failed_lock:
                _failed_endpoints.add(endpoint_key)
            continue

        # 取最近 5 行尝试匹配
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
