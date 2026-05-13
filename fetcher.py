"""
数据抓取模块（多源 fallback 版）

数据源链：东方财富(akshare) → 腾讯(直连) → 新浪(直连) → 本地磁盘缓存
反爬防护：全局限流锁 + 熔断器 + 多源 fallback + 磁盘缓存
"""
__version__ = "2.0.0-multi-source"

import time
import random
import threading
from pathlib import Path
import requests
import pandas as pd
from loguru import logger

# 启动时打印明显的版本横幅，方便用户辨认是否真的加载到了新版
print(f"[fetcher] ★ 加载多源 fallback 版本 v{__version__}  "
      f"（启动时若没看到这一行 = 跑的是旧版！）")

try:
    import akshare as ak
except ImportError:
    ak = None
    logger.warning("akshare 未安装，数据抓取功能不可用")


# ════════════════════════════════════════════════════════════════
#  反爬节流参数（如果还是被封，把这些值调更大；要更激进可以调小）
# ════════════════════════════════════════════════════════════════
# 两次请求之间的最小间隔（秒）。
# 1.2s 太激进容易被封；3.0s 是保守安全值；如果还是被封可改到 5.0 甚至 10.0
# 代价：N 只股票启动总耗时 ≈ N × MIN_INTERVAL_SEC
MIN_INTERVAL_SEC = 3.0

# 重试退避：失败后等待 (RETRY_BACKOFF_BASE × 2^attempt + 0~1s 抖动) 秒后重试
# 例如 BASE=5 时：第 1 次失败等 10s±1，第 2 次等 20s±1，第 3 次等 40s±1
RETRY_BACKOFF_BASE = 5

# 单源单次重试次数（越少越保守）
# 注意：fetch_kline 内部还会做"东财→腾讯→新浪"的 3 源 fallback，
# 所以这里设为 1 也基本等于实际尝试 3 次（一只股票最多 3 个源各试 1 次）
RETRIES_PER_SOURCE = 1

# 熔断器：连续失败 N 次后暂停 M 秒，让对端冷却
CIRCUIT_THRESHOLD = 5            # 之前是 10，改更敏感
CIRCUIT_PAUSE_SEC = 900          # 之前 5 分钟，改成 15 分钟

# 源级健康检查：某个源连续失败 N 次 → 标记为"暂时不可用"，跳过
# 跳过 M 秒后再悄悄探测一次，如果恢复了就重新启用
SOURCE_FAIL_THRESHOLD = 3        # 同一个源连续失败 3 次 → 标记不可用
SOURCE_RETRY_INTERVAL = 600      # 标记后 10 分钟再试探


# ────────────────────────────────────────────────────────────────
#  源级健康状态：避免知道东财坏了仍然每只股票都问一遍
# ────────────────────────────────────────────────────────────────
class _SourceHealth:
    """记录每个数据源（东财/腾讯/新浪）的健康状态，避免重复尝试已知坏源。"""

    def __init__(self):
        # {source_name: {"healthy": bool, "fail_count": int, "marked_at": ts}}
        self._status: dict = {}
        self._lock = threading.Lock()

    def is_healthy(self, name: str) -> bool:
        """该源当前是否值得一试。"""
        with self._lock:
            s = self._status.get(name)
            if s is None:
                return True            # 从没用过 → 试试看
            if s["healthy"]:
                return True
            # 已被标记不可用，但若已超过 SOURCE_RETRY_INTERVAL，允许探测
            if time.time() - s["marked_at"] >= SOURCE_RETRY_INTERVAL:
                logger.info(f"[源健康] {name} 已暂停 {SOURCE_RETRY_INTERVAL // 60} 分钟，准备探测是否恢复")
                return True
            return False

    def mark_success(self, name: str):
        """标记成功：清空失败计数 + 标记健康。"""
        with self._lock:
            prev = self._status.get(name, {})
            if not prev.get("healthy", True):
                logger.info(f"[源健康] ✓ {name} 已恢复正常")
            self._status[name] = {"healthy": True, "fail_count": 0, "marked_at": time.time()}

    def mark_failure(self, name: str):
        """标记失败：失败计数 +1，到达阈值则标记不可用。"""
        with self._lock:
            s = self._status.setdefault(name, {"healthy": True, "fail_count": 0, "marked_at": 0})
            s["fail_count"] += 1
            s["marked_at"] = time.time()
            if s["healthy"] and s["fail_count"] >= SOURCE_FAIL_THRESHOLD:
                s["healthy"] = False
                logger.warning(
                    f"[源健康] ✗ {name} 连续失败 {s['fail_count']} 次，"
                    f"标记暂时不可用，{SOURCE_RETRY_INTERVAL // 60} 分钟后再探测"
                )

    def snapshot(self) -> dict:
        """供调试用：当前各源的状态"""
        with self._lock:
            return {n: dict(s) for n, s in self._status.items()}


_source_health = _SourceHealth()


# ────────────────────────────────────────────────────────────────
#  全局限流：所有数据源调用强制排队
# ────────────────────────────────────────────────────────────────
class _AKLimiter:
    """两次外部调用之间至少间隔 min_interval 秒。所有线程共用一把锁。"""
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self):
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self._last = time.monotonic()

# 模块级单例
_ak_limiter = _AKLimiter(min_interval=MIN_INTERVAL_SEC)


# ────────────────────────────────────────────────────────────────
#  熔断器：连续失败后暂停，避免持续骚扰加重 IP 封禁
# ────────────────────────────────────────────────────────────────
_circuit_failures = 0
_circuit_open_until: float = 0.0
_circuit_lock = threading.Lock()


def _circuit_check():
    """如果熔断器开启且未到恢复时间，抛错。"""
    with _circuit_lock:
        if _circuit_open_until and time.time() < _circuit_open_until:
            remaining = _circuit_open_until - time.time()
            raise RuntimeError(f"熔断器开启中（剩余 {remaining:.0f}s），跳过本次调用")


def _circuit_record_failure(fn_name: str):
    """记录一次失败。达到阈值则熔断。"""
    global _circuit_failures, _circuit_open_until
    with _circuit_lock:
        _circuit_failures += 1
        if _circuit_failures >= CIRCUIT_THRESHOLD and _circuit_open_until < time.time():
            _circuit_open_until = time.time() + CIRCUIT_PAUSE_SEC
            _circuit_failures = 0
            logger.warning(
                f"[熔断] 连续失败已达 {CIRCUIT_THRESHOLD} 次（最近: {fn_name}），"
                f"暂停所有外部调用 {CIRCUIT_PAUSE_SEC // 60} 分钟，让对端冷却"
            )


def _circuit_record_success():
    """成功调用清零失败计数。"""
    global _circuit_failures
    with _circuit_lock:
        _circuit_failures = 0


def _ak_call_with_retry(fn_name: str, fn, *args, retries: int = None, **kwargs):
    """
    带限流、熔断、指数退避的包装器。
    retries 默认使用全局 RETRIES_PER_SOURCE，可被显式覆盖。
    """
    if retries is None:
        retries = RETRIES_PER_SOURCE
    _circuit_check()      # 熔断检查（开启状态直接 raise，让上层兜底缓存）

    last_err = None
    for attempt in range(1, retries + 1):
        _ak_limiter.wait()                  # 全局限流
        try:
            result = fn(*args, **kwargs)
            _circuit_record_success()       # 成功 → 重置失败计数
            return result
        except Exception as e:
            last_err = e
            _circuit_record_failure(fn_name)
            logger.warning(f"[{fn_name}] 第 {attempt}/{retries} 次失败: {e}")
            if attempt < retries:
                # 指数退避 + 抖动：base × 2^attempt 秒
                backoff = RETRY_BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 1.0)
                time.sleep(backoff)
    raise last_err


# ────────────────────────────────────────────────────────────────
#  A 股 K 线数据
# ────────────────────────────────────────────────────────────────

_KLINE_CACHE_FILE = Path("kline_cache.json")
_kline_cache_lock = threading.Lock()


def _normalize_kline(df: pd.DataFrame) -> pd.DataFrame:
    """
    统一三个数据源的列名 + 类型转换。
    腾讯/新浪只返回 OHLCV 基础字段，change_pct 由 close 计算补上。
    """
    col_map = {
        # 东财 stock_zh_a_hist
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "turnover",
        "振幅": "amplitude", "涨跌幅": "change_pct",
        "涨跌额": "change_amount", "换手率": "turnover_rate",
        # 新浪 K 线的列名
        "day": "date",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    if "date" not in df.columns and df.index.name in ("date", "日期"):
        df = df.reset_index().rename(columns={df.index.name: "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    for col in ["open", "close", "high", "low", "volume", "turnover",
                "amplitude", "change_pct", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 腾讯/新浪不返回 change_pct，自己算出来（百分比）
    if "change_pct" not in df.columns and "close" in df.columns:
        df["change_pct"] = (df["close"].pct_change() * 100).round(3)

    return df


def _save_kline_cache(symbol: str, df: pd.DataFrame):
    """保存 K 线到磁盘。仅在拉取成功时调用。最多保留监控股票数 × 2 倍的条目。"""
    if df is None or df.empty:
        return
    try:
        with _kline_cache_lock:
            cache = _load_kline_cache_all()
            cache[symbol] = {
                "ts":   time.time(),
                "data": [
                    {"date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
                     **{k: (None if pd.isna(v) else float(v)) for k, v in r.items() if k != "date"}}
                    for r in df.to_dict("records")
                ],
            }
            with open(_KLINE_CACHE_FILE, "w", encoding="utf-8") as f:
                import json
                json.dump(cache, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"[{symbol}] K 线缓存保存失败（非致命）: {e}")


def _load_kline_cache_all() -> dict:
    """读取整个缓存字典。"""
    if not _KLINE_CACHE_FILE.exists():
        return {}
    try:
        import json
        with open(_KLINE_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.debug(f"K 线缓存读取失败（非致命）: {e}")
        return {}


def _load_kline_cache(symbol: str) -> pd.DataFrame | None:
    """读取某只股票的缓存 K 线。返回 None 表示无缓存。"""
    with _kline_cache_lock:
        cache = _load_kline_cache_all()
    entry = cache.get(symbol)
    if not entry or not entry.get("data"):
        return None
    df = pd.DataFrame(entry["data"])
    df["date"] = pd.to_datetime(df["date"])
    age_hours = (time.time() - entry.get("ts", 0)) / 3600
    logger.info(f"[{symbol}] 使用磁盘缓存（{age_hours:.1f}h 前的数据，{len(df)} 行）")
    return df


def _fetch_kline_em(symbol: str) -> pd.DataFrame:
    """东方财富 K 线（akshare 包装，反爬最严但数据最全）"""
    return _ak_call_with_retry(
        f"K线[em] {symbol}", ak.stock_zh_a_hist,
        retries=RETRIES_PER_SOURCE,
        symbol=symbol, period="daily",
        start_date="20200101", end_date="21000101", adjust="qfq",
    )


# ──── 通用 HTTP headers（伪装成浏览器）────
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def _market_prefix(symbol: str) -> str:
    """A 股市场前缀：sh/sz"""
    return "sh" if symbol.startswith(("6", "5", "9")) else "sz"


def _fetch_kline_tencent(symbol: str) -> pd.DataFrame:
    """
    腾讯日K（直连 requests，不走 akshare）
    URL: http://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sh600519,day,,,250,qfq
    返回 JSON: {"code":0, "data":{"sh600519":{"qfqday":[[date,open,close,high,low,volume],...]}}}
    """
    _ak_limiter.wait()       # 复用同一把限流锁（任何外部数据源都得排队）
    _circuit_check()
    code = f"{_market_prefix(symbol)}{symbol}"
    try:
        r = requests.get(
            "http://web.ifzq.gtimg.cn/appstock/app/kline/kline",
            params={"param": f"{code},day,,,250,qfq"},
            headers={**_BROWSER_HEADERS, "Referer": "http://gu.qq.com/"},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _circuit_record_failure(f"K线[tencent] {symbol}")
        raise

    if data.get("code") != 0:
        _circuit_record_failure(f"K线[tencent] {symbol}")
        raise RuntimeError(f"腾讯返回错误码: {data.get('code')}  msg: {data.get('msg', '')}")

    rows = (data.get("data", {}).get(code, {}).get("qfqday")
            or data.get("data", {}).get(code, {}).get("day"))
    if not rows:
        _circuit_record_failure(f"K线[tencent] {symbol}")
        raise RuntimeError(f"腾讯无K线数据 for {code}")

    # 腾讯返回 [日期, 开, 收, 高, 低, 量, ...]（每行 6-9 列）
    df = pd.DataFrame([r[:6] for r in rows],
                      columns=["date", "open", "close", "high", "low", "volume"])
    _circuit_record_success()
    return df


def _fetch_kline_sina(symbol: str) -> pd.DataFrame:
    """
    新浪日K（直连 requests，不走 akshare）
    URL: http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData
    返回 JSON 数组: [{"day":"2024-01-02","open":"...","high":"...","low":"...","close":"...","volume":"..."},...]
    """
    _ak_limiter.wait()
    _circuit_check()
    code = f"{_market_prefix(symbol)}{symbol}"
    try:
        r = requests.get(
            "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
            params={"symbol": code, "scale": "240", "ma": "no", "datalen": "250"},
            headers=_BROWSER_HEADERS,
            timeout=10,
        )
        r.raise_for_status()
        # 新浪有时返回 JSON 有时返回 JSONP，做兼容
        text = r.text.strip()
        if not text.startswith("["):
            # JSONP 包装：取第一个 [ 到最后一个 ]
            start, end = text.find("["), text.rfind("]")
            if start < 0 or end < 0:
                raise RuntimeError(f"新浪返回格式异常: {text[:100]}")
            text = text[start:end + 1]
        import json
        rows = json.loads(text)
    except Exception:
        _circuit_record_failure(f"K线[sina] {symbol}")
        raise

    if not rows:
        _circuit_record_failure(f"K线[sina] {symbol}")
        raise RuntimeError(f"新浪无K线数据 for {code}")

    df = pd.DataFrame(rows).rename(columns={"day": "date"})
    _circuit_record_success()
    return df


def _fetch_stock_info_tencent(symbol: str) -> dict | None:
    """
    腾讯实时行情拿股票名/价格/PE/PB（直连 requests）
    URL: http://qt.gtimg.cn/q=sh600519
    返回: v_sh600519="1~贵州茅台~600519~1372.99~1371.05~..."
    字段（参考腾讯文档）：[1]名称 [3]当前价 [4]昨收 [5]今开 [44]PE [46]市值(亿)
    """
    _ak_limiter.wait()
    _circuit_check()
    code = f"{_market_prefix(symbol)}{symbol}"
    try:
        r = requests.get(
            f"http://qt.gtimg.cn/q={code}",
            headers={**_BROWSER_HEADERS, "Referer": "http://gu.qq.com/"},
            timeout=8,
        )
        r.raise_for_status()
        text = r.text
    except Exception as e:
        _circuit_record_failure(f"股票信息[tencent] {symbol}")
        _source_health.mark_failure("腾讯")
        logger.debug(f"[{symbol}] 腾讯实时行情请求失败: {e}")
        return None

    # 解析返回字符串：v_sh600519="字段1~字段2~..."
    try:
        payload = text.split('"', 2)[1]
        fields = payload.split("~")
        if len(fields) < 5 or not fields[1]:
            _source_health.mark_failure("腾讯")
            return None
        result = {
            "name":         fields[1],
            "industry":     "N/A",
            "market_cap":   (fields[45] + "亿") if len(fields) > 45 and fields[45] else "N/A",
            "pe_ratio":     fields[39] if len(fields) > 39 and fields[39] not in ("", "-") else "N/A",
            "pb_ratio":     fields[46] if len(fields) > 46 and fields[46] not in ("", "-") else "N/A",
            "total_shares": "N/A",
            "float_shares": "N/A",
            "_source":      "tencent",
        }
        _circuit_record_success()
        _source_health.mark_success("腾讯")
        return result
    except Exception as e:
        _source_health.mark_failure("腾讯")
        logger.debug(f"[{symbol}] 解析腾讯返回失败: {e}  原文前100: {text[:100]!r}")
        return None


def probe_data_sources(test_symbol: str = "600519") -> dict:
    """
    启动探测：用一只测试股票（默认贵州茅台 600519）一次性测试 3 个 K 线数据源，
    预热源健康状态。后续 fetch_kline 直接走可用源，不浪费请求骚扰已知坏源。

    返回各源状态字典，例如 {"东财": False, "腾讯": True, "新浪": True}
    """
    if ak is None:
        return {}

    probes = [
        ("东财", _fetch_kline_em),
        ("腾讯", _fetch_kline_tencent),
        ("新浪", _fetch_kline_sina),
    ]
    print(f"\n[源探测] 用 {test_symbol} 测试三个数据源（限流间隔 {MIN_INTERVAL_SEC}s，约 {len(probes) * MIN_INTERVAL_SEC:.0f} 秒）...")
    result = {}
    for name, fn in probes:
        try:
            df = fn(test_symbol)
            if df is not None and not df.empty:
                _source_health.mark_success(name)
                result[name] = True
                print(f"  ✓ {name:4s} 可用 ({len(df)} 条)")
            else:
                # 直接标记失败到阈值，让后续直接跳过
                for _ in range(SOURCE_FAIL_THRESHOLD):
                    _source_health.mark_failure(name)
                result[name] = False
                print(f"  ✗ {name:4s} 返回空数据")
        except Exception as e:
            for _ in range(SOURCE_FAIL_THRESHOLD):
                _source_health.mark_failure(name)
            result[name] = False
            print(f"  ✗ {name:4s} 失败: {type(e).__name__}")

    available = [n for n, ok in result.items() if ok]
    if available:
        print(f"[源探测] 可用源: {' / '.join(available)}（后续股票将直接走可用源，跳过坏源）\n")
    else:
        print(f"[源探测] ⚠ 三个在线源全部不可用，将使用磁盘缓存兜底\n")
    return result


def fetch_kline(symbol: str, days: int = 250, retries: int = 3) -> pd.DataFrame:
    """
    K 线获取主入口。多源 fallback + 源级健康检查：
      1) 东方财富（akshare，数据最全但反爬严）
      2) 腾讯证券（直连 requests）
      3) 新浪财经（直连 requests）
      4) 本地磁盘缓存（最后兜底）

    源健康检查：某个源连续失败 SOURCE_FAIL_THRESHOLD 次后，后续股票会直接
    跳过这个源，10 分钟后再探测一次。避免"知道东财坏了仍然每只股票都问一遍"。
    """
    if ak is None:
        raise RuntimeError("akshare 未安装")

    sources = [
        ("东财", _fetch_kline_em),
        ("腾讯", _fetch_kline_tencent),
        ("新浪", _fetch_kline_sina),
    ]

    last_err: Exception | None = None
    for src_name, fn in sources:
        # 健康检查：已知坏的源直接跳过
        if not _source_health.is_healthy(src_name):
            continue
        try:
            df = fn(symbol)
            if df is not None and not df.empty:
                df = _normalize_kline(df).tail(days).reset_index(drop=True)
                _source_health.mark_success(src_name)
                if src_name != "东财":
                    logger.info(f"[{symbol}] K 线来源 → {src_name}")
                _save_kline_cache(symbol, df)
                logger.debug(f"[{symbol}] {src_name} 返回 {len(df)} 条，最新："
                             f"{df.iloc[-1]['date'].date()}  收盘：{df.iloc[-1]['close']}")
                return df
        except Exception as e:
            last_err = e
            _source_health.mark_failure(src_name)
            logger.debug(f"[{symbol}] {src_name} K 线源失败: {type(e).__name__}: {e}")

    # 所有可用源都失败/被跳过 → 用磁盘缓存
    cached = _load_kline_cache(symbol)
    if cached is not None and len(cached) >= 20:
        logger.warning(f"[{symbol}] 所有在线 K 线源都失败，使用本地磁盘缓存")
        return cached.tail(days).reset_index(drop=True)

    raise last_err or RuntimeError(f"{symbol} 所有 K 线源均失败且无缓存")


# ────────────────────────────────────────────────────────────────
#  全市场快照缓存（替代单只 stock_individual_info_em，避免反爬）
# ────────────────────────────────────────────────────────────────
# 反爬现状：东方财富对 stock_individual_info_em（爬 HTML 详情页）的限流非常严，
# 即使加了 1.2s 间隔，监控 16 只股票也基本会全军覆没。
#
# 解决思路：用 ak.stock_zh_a_spot_em() 一次性拉全市场快照（5000+ 只股票），
# 含代码/名称/最新价/涨跌幅/市盈率/市净率/总市值，缓存 30 分钟。所有股票从这一份
# 缓存里查，启动时 N 次单股请求 → 1 次全市场请求，反爬压力骤降。
_market_snapshot = None
_market_snapshot_ts: float = 0.0
_market_snapshot_lock = threading.Lock()
_MARKET_SNAPSHOT_TTL = 1800   # 30 分钟


def _get_market_snapshot():
    """获取全市场实时快照（DataFrame 索引为股票代码），缓存 30 分钟。失败返回 None。"""
    global _market_snapshot, _market_snapshot_ts
    with _market_snapshot_lock:
        if _market_snapshot is not None and (time.time() - _market_snapshot_ts) < _MARKET_SNAPSHOT_TTL:
            return _market_snapshot
        if ak is None:
            return None
        # 源健康检查：东财坏了就不试，让上层走腾讯
        if not _source_health.is_healthy("东财"):
            return None
        try:
            df = _ak_call_with_retry(
                "全市场快照",
                ak.stock_zh_a_spot_em,
                retries=RETRIES_PER_SOURCE,
            )
            if df is None or df.empty:
                return None
            if "代码" in df.columns:
                df = df.set_index("代码")
            _market_snapshot = df
            _market_snapshot_ts = time.time()
            _source_health.mark_success("东财")
            logger.info(f"[全市场] 已缓存 {len(df)} 只股票快照（30 分钟有效）")
            return df
        except Exception as e:
            _source_health.mark_failure("东财")
            logger.warning(f"[全市场] 快照拉取失败，将回落到单股查询: {e}")
            return None


def _safe_str(v):
    """把 pandas 单元格转成 str，NaN 返回 'N/A'"""
    if v is None:
        return "N/A"
    try:
        # NaN 检测
        if isinstance(v, float) and v != v:
            return "N/A"
    except Exception:
        pass
    return str(v)


def fetch_stock_info(symbol: str) -> dict:
    """
    获取股票基本信息（名称、市盈率、市净率、总市值等）

    数据来源优先级：
      1) 全市场快照（akshare 东财，一次调用覆盖 5000+ 只）★ 性能最优
      2) 腾讯证券直连（绕过 akshare，IP 被东财封时也能用）
      3) akshare stock_individual_info_em（最后降级，反爬严）

    任何分支失败时返回 fallback {name: symbol, ...}，不抛异常。
    """
    fallback = {"name": symbol, "industry": "N/A", "market_cap": "N/A"}
    if ak is None:
        return fallback

    # ── 路径 1：全市场快照（东财）─ 仅当"东财"健康时尝试
    if _source_health.is_healthy("东财"):
        snap = _get_market_snapshot()
        if snap is not None and symbol in snap.index:
            row = snap.loc[symbol]
            return {
                "name":         _safe_str(row.get("名称", symbol)),
                "industry":     "N/A",
                "market_cap":   _safe_str(row.get("总市值", "N/A")),
                "pe_ratio":     _safe_str(row.get("市盈率-动态", "N/A")),
                "pb_ratio":     _safe_str(row.get("市净率", "N/A")),
                "total_shares": "N/A",
                "float_shares": "N/A",
                "_source":      "spot_em",
            }

    # ── 路径 2：腾讯直连 ─ 仅当"腾讯"健康时尝试
    if _source_health.is_healthy("腾讯"):
        tencent_info = _fetch_stock_info_tencent(symbol)
        if tencent_info is not None:
            return tencent_info

    # ── 路径 3：东财单股详情 ─ 仅当"东财"健康时尝试
    if _source_health.is_healthy("东财"):
        try:
            info = _ak_call_with_retry(
                f"股票信息 {symbol}",
                ak.stock_individual_info_em,
                retries=RETRIES_PER_SOURCE,
                symbol=symbol,
            )
            d = dict(zip(info.iloc[:, 0], info.iloc[:, 1]))
            return {
                "name":         _safe_str(d.get("股票简称", symbol)),
                "industry":     _safe_str(d.get("行业", "N/A")),
                "market_cap":   _safe_str(d.get("总市值", "N/A")),
                "pe_ratio":     _safe_str(d.get("市盈率(动)", "N/A")),
                "pb_ratio":     _safe_str(d.get("市净率", "N/A")),
                "total_shares": _safe_str(d.get("总股本", "N/A")),
                "float_shares": _safe_str(d.get("流通股本", "N/A")),
                "_source":      "individual_em",
            }
        except Exception as e:
            _source_health.mark_failure("东财")
            logger.debug(f"[{symbol}] 东财单股信息失败: {e}")

    return fallback


# ────────────────────────────────────────────────────────────────
#  WallStreet.cn 大宗商品（预留接口）
# ────────────────────────────────────────────────────────────────

class CommodityFetcher:
    """
    WallStreet.cn 大宗商品价格接口（预留，待接入）

    未来接入方式：
    1. 注册 WallStreet.cn 开发者账号，获取 API Key
    2. 在 .env 中设置 WALLSTREET_API_KEY 和 COMMODITY_CODES
    3. 实现 fetch() 方法，调用其 REST API
    4. 返回标准化 DataFrame，列：commodity, price, change_pct, date

    参考 API 文档：https://wallstreetcn.com/developer （需登录查看）
    """

    BASE_URL = "https://api.wallstreetcn.com/apiv1"  # 示例，实际以文档为准

    def __init__(self, api_key: str = "", commodity_codes: list = None):
        self.api_key = api_key
        self.commodity_codes = commodity_codes or []
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "StockMonitor/1.0",
        })

    def is_configured(self) -> bool:
        return bool(self.api_key and self.commodity_codes)

    def fetch(self) -> dict:
        """
        获取大宗商品最新价格
        返回：{commodity_code: {price, change_pct, name, unit}}

        ⚠️  此方法为预留接口，尚未实现，接入时请在此实现
        """
        if not self.is_configured():
            logger.debug("大宗商品接口未配置，跳过")
            return {}

        results = {}
        for code in self.commodity_codes:
            try:
                # TODO: 替换为真实的 WallStreet.cn API 端点
                # resp = self.session.get(f"{self.BASE_URL}/market/realtime?code={code}", timeout=10)
                # data = resp.json()
                # results[code] = {
                #     "name": data["name"],
                #     "price": data["last"],
                #     "change_pct": data["chg"],
                #     "unit": data["unit"],
                # }
                logger.debug(f"大宗商品 [{code}] 接口预留，暂未实现")
            except Exception as e:
                logger.warning(f"大宗商品 [{code}] 获取失败: {e}")

        return results

    def format_for_prompt(self, commodity_data: dict) -> str:
        """
        将大宗商品数据格式化为 AI prompt 段落
        """
        if not commodity_data:
            return ""

        lines = ["【全球大宗商品参考（WallStreet.cn）】"]
        for code, info in commodity_data.items():
            sign = "+" if info.get("change_pct", 0) >= 0 else ""
            lines.append(
                f"  {info.get('name', code)}：{info.get('price', 'N/A')} "
                f"{info.get('unit', '')}  ({sign}{info.get('change_pct', 'N/A')}%)"
            )
        return "\n".join(lines)
