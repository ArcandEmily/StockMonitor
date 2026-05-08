"""
calendar_fetcher.py
───────────────────
财报日历 / 重要事件提醒

功能：
  1. 财报披露日历（一季报/半年报/三季报/年报）
  2. 分红除权信息
  3. 重大公告扫描

数据来源：akshare（东方财富/巨潮资讯）
缓存：6 小时（日历变化较慢）
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

_cache: dict  = {}        # "all_codes_joined" → events list
_cache_ts: float = 0
_lock = threading.Lock()
_TTL  = 21600             # 6 小时


def get_upcoming_events(codes: list[str]) -> list[dict]:
    """
    返回监控股票的近期重要事件列表（90天内）：
    [
      {
        "code":      "600519",
        "name":      "贵州茅台",
        "event":     "年报",           # 类型
        "date":      "2026-04-30",    # 预计日期
        "days_left": 5,               # 距今天数
        "status":    "upcoming"       # upcoming / overdue / today
      },
      ...
    ]
    按 days_left 升序排列。
    """
    key = ",".join(sorted(codes))

    with _lock:
        if _cache.get(key) is not None and (time.time() - _cache_ts) < _TTL:
            return list(_cache[key])

    result = _fetch_events(codes)

    with _lock:
        _cache[key] = result
        # 更新全局时间戳（用类变量避免 global）
        _CalendarState.ts = time.time()

    return result


class _CalendarState:
    ts: float = 0


def _fetch_events(codes: list[str]) -> list[dict]:
    if not HAS_AK:
        return []

    today    = datetime.date.today()
    events   = []
    codes_s  = set(codes)

    # ── 1. 财报披露日历 ──────────────────────────────────────
    report_types = {
        "一季报": ("01-01", "04-30"),
        "半年报": ("04-01", "08-31"),
        "三季报": ("07-01", "10-31"),
        "年报":   ("10-01", "05-31"),   # 跨年
    }
    for report_name, _ in report_types.items():
        try:
            df = ak.stock_report_disclosure(market="沪深A股", category=report_name)
            if df is None or df.empty:
                continue
            # 字段：股票代码 / 股票简称 / 预约披露日期
            for col_code in ["股票代码", "代码"]:
                if col_code in df.columns:
                    break
            for col_name in ["股票简称", "名称"]:
                if col_name in df.columns:
                    break
            for col_date in ["预约披露日期", "披露日期", "日期"]:
                if col_date in df.columns:
                    break

            for _, row in df.iterrows():
                code = str(row.get(col_code, "")).zfill(6)
                if code not in codes_s:
                    continue
                date_raw = str(row.get(col_date, "")).strip()
                if not date_raw or date_raw == "nan":
                    continue
                try:
                    event_date = datetime.date.fromisoformat(date_raw[:10])
                    days_left  = (event_date - today).days
                    if -7 <= days_left <= 90:    # 已过 7 天内或未来 90 天内
                        events.append({
                            "code":      code,
                            "name":      str(row.get(col_name, code)),
                            "event":     report_name,
                            "date":      event_date.isoformat(),
                            "days_left": days_left,
                            "status":    "today"    if days_left == 0
                                         else "overdue"  if days_left < 0
                                         else "upcoming",
                        })
                except ValueError:
                    continue
        except Exception as e:
            logger.debug(f"[日历] {report_name} 获取失败: {e}")

    # ── 2. 分红除权信息 ──────────────────────────────────────
    for code in codes:
        try:
            df = ak.stock_dividend_cninfo(symbol=code, indicator="分红")
            if df is None or df.empty:
                continue
            for col_date in ["除权除息日", "股权登记日", "分红日期"]:
                if col_date in df.columns:
                    date_col = col_date
                    break
            else:
                continue

            for _, row in df.tail(3).iterrows():
                date_raw = str(row.get(date_col, "")).strip()
                if not date_raw or date_raw == "nan":
                    continue
                try:
                    event_date = datetime.date.fromisoformat(date_raw[:10])
                    days_left  = (event_date - today).days
                    if -7 <= days_left <= 90:
                        # 尝试获取股票名称
                        name = code
                        events.append({
                            "code":      code,
                            "name":      name,
                            "event":     "分红除权",
                            "date":      event_date.isoformat(),
                            "days_left": days_left,
                            "status":    "today"   if days_left == 0
                                         else "overdue" if days_left < 0
                                         else "upcoming",
                        })
                except ValueError:
                    continue
        except Exception as e:
            logger.debug(f"[日历] {code} 分红信息获取失败: {e}")

    events.sort(key=lambda x: x["days_left"])
    logger.info(f"[日历] 共获取 {len(events)} 个事件")
    return events
