"""
fetcher.py — 个股 K 线与基础信息抓取
─────────────────────────────────────
设计原则：简单直接，一只一只串行拉。

K 线：    通达信 → 东财 → 新浪 → 腾讯 → 本地磁盘缓存
基础信息：东财单股 → 新浪实时 → 腾讯实时（注：mootdx 不提供基本面字段，
         所以股票基础信息没有通达信通道——这是正常的，不要误以为是 bug）

v3.1 修复：
  1. 启动探测改为并行（4 个源同时探测），从 60-90s 降到 ~5s
  2. K 线源选择改为始终打印（移除"通达信/东财静默"的逻辑），
     方便用户确认实际走的是哪一源
"""
__version__ = "3.1-parallel-probe"

import warnings
warnings.filterwarnings(
    "ignore",
    message=r".*pkg_resources is deprecated.*",
    category=UserWarning,
)

import time
import json
import threading
import requests
import pandas as pd
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger


# ── 屏蔽 akshare 内部的 tqdm 进度条（必须在 import akshare 之前）─
def _disable_tqdm():
    try:
        import tqdm, tqdm.auto
        orig = tqdm.tqdm.__init__
        def silent(self, *args, **kwargs):
            kwargs["disable"] = True
            orig(self, *args, **kwargs)
        tqdm.tqdm.__init__ = silent
        if tqdm.auto.tqdm is not tqdm.tqdm:
            orig2 = tqdm.auto.tqdm.__init__
            def silent2(self, *a, **kw):
                kw["disable"] = True
                orig2(self, *a, **kw)
            tqdm.auto.tqdm.__init__ = silent2
    except ImportError:
        pass

_disable_tqdm()

try:
    import akshare as ak
except ImportError:
    ak = None
    logger.warning("akshare 未安装")

try:
    from mootdx.quotes import Quotes as _MootdxQuotes
    HAS_TDX = True
except ImportError:
    _MootdxQuotes = None
    HAS_TDX = False
    logger.info("mootdx 未安装，通达信数据源不可用（不影响其他源）")


# ════════════════════════════════════════════════════════════════
#  通达信客户端（mootdx）
# ════════════════════════════════════════════════════════════════
_tdx_client = None
_tdx_init_lock = threading.Lock()
_tdx_init_done = False


def _init_tdx_client():
    """bestip=True 会扫描服务器选最快的，耗时 3-5s。整个进程只跑一次。"""
    global _tdx_client, _tdx_init_done
    if not HAS_TDX:
        return False
    with _tdx_init_lock:
        if _tdx_init_done:
            return _tdx_client is not None
        _tdx_init_done = True
        print("[mootdx] 正在选取最快的通达信服务器（约 3-5 秒）...")
        try:
            _tdx_client = _MootdxQuotes.factory(
                market="std",
                multithread=True,
                heartbeat=True,
                bestip=True,
                timeout=15,
                verbose=0,
                quiet=True,
            )
            print("[mootdx] 通达信客户端初始化成功")
            return True
        except Exception as e:
            print(f"[mootdx] 初始化失败（将不使用通达信源）: {e}")
            _tdx_client = None
            return False


# ════════════════════════════════════════════════════════════════
#  全局限流：两次外部调用至少间隔 N 秒
# ════════════════════════════════════════════════════════════════
MIN_INTERVAL = 1.5
_last_call_ts = 0.0
_call_lock = threading.Lock()


def _rate_limit():
    """所有线程共用一把锁；探测阶段会绕过它（见 probe_data_sources）"""
    global _last_call_ts
    with _call_lock:
        elapsed = time.monotonic() - _last_call_ts
        if elapsed < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - elapsed)
        _last_call_ts = time.monotonic()


# ════════════════════════════════════════════════════════════════
#  坏源标记
# ════════════════════════════════════════════════════════════════
DEAD_THRESHOLD   = 2
DEAD_RETRY_AFTER = 600

_source_fail_count: dict = {}
_dead_sources: dict      = {}
_dead_lock               = threading.Lock()


def _is_source_dead(name: str) -> bool:
    with _dead_lock:
        marked_at = _dead_sources.get(name)
        if not marked_at:
            return False
        if time.time() - marked_at > DEAD_RETRY_AFTER:
            del _dead_sources[name]
            _source_fail_count[name] = 0
            logger.info(f"[源标记] {name} 已暂停 {DEAD_RETRY_AFTER // 60} 分钟，准备重新探测")
            return False
        return True


def _mark_source_failed(name: str, is_network: bool):
    if not is_network:
        return
    with _dead_lock:
        _source_fail_count[name] = _source_fail_count.get(name, 0) + 1
        if _source_fail_count[name] >= DEAD_THRESHOLD and name not in _dead_sources:
            _dead_sources[name] = time.time()
            logger.warning(
                f"[源标记] ✗ {name} 已连续网络失败 {_source_fail_count[name]} 次，"
                f"标记为不可用，后续股票将跳过它（{DEAD_RETRY_AFTER // 60} 分钟后再探测）"
            )


def _mark_source_ok(name: str):
    with _dead_lock:
        if _source_fail_count.get(name):
            _source_fail_count[name] = 0
        if name in _dead_sources:
            del _dead_sources[name]
            logger.info(f"[源标记] ✓ {name} 已恢复")


def _is_network_error(e: Exception) -> bool:
    s = str(e)
    return (isinstance(e, (ConnectionError, requests.exceptions.Timeout,
                            requests.exceptions.ConnectionError,
                            requests.exceptions.SSLError))
            or "RemoteDisconnected" in s
            or "Connection aborted" in s
            or "Read timed out" in s)


# ════════════════════════════════════════════════════════════════
#  磁盘缓存
# ════════════════════════════════════════════════════════════════
_CACHE_FILE = Path("kline_cache.json")
_cache_lock = threading.Lock()


def _save_cache(symbol: str, df: pd.DataFrame):
    if df is None or df.empty:
        return
    try:
        with _cache_lock:
            try:
                with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}
            data[symbol] = {
                "ts": time.time(),
                "rows": [
                    {"date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
                     **{k: (None if pd.isna(v) else float(v))
                        for k, v in r.items() if k != "date"}}
                    for r in df.to_dict("records")
                ],
            }
            with open(_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.debug(f"缓存写失败: {e}")


def _load_cache(symbol: str):
    try:
        with _cache_lock:
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        entry = data.get(symbol)
        if not entry or not entry.get("rows"):
            return None
        df = pd.DataFrame(entry["rows"])
        df["date"] = pd.to_datetime(df["date"])
        age_h = (time.time() - entry.get("ts", 0)) / 3600
        logger.info(f"[{symbol}] 使用磁盘缓存（{age_h:.1f}h 前的数据，{len(df)} 行）")
        return df
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
#  3 个 HTTP K 线源 + 通达信
# ════════════════════════════════════════════════════════════════
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _market_prefix(symbol: str) -> str:
    return "sh" if symbol.startswith(("6", "5", "9")) else "sz"


def _fetch_kline_tdx(symbol: str) -> pd.DataFrame:
    """通达信日 K（mootdx，TCP socket 协议，反爬绝缘体）"""
    if not HAS_TDX:
        raise RuntimeError("mootdx 未安装")
    if _tdx_client is None:
        if not _init_tdx_client():
            raise RuntimeError("通达信客户端未就绪")

    df = _tdx_client.bars(symbol=symbol, frequency=9, offset=250)
    if df is None or df.empty:
        raise RuntimeError(f"通达信无数据 for {symbol}")

    if "date" in df.columns and "datetime" in df.columns:
        df = df.drop(columns=["datetime"])
    keep = [c for c in df.columns
            if c in ("date", "datetime", "open", "close", "high", "low",
                     "vol", "volume", "amount", "turnover")]
    df = df[keep].copy()
    df = df.rename(columns={"datetime": "date", "vol": "volume", "amount": "turnover"})
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()]
    return df


def _fetch_kline_em(symbol: str) -> pd.DataFrame:
    """东方财富日 K（akshare）。
    探测时改成只拉最近 ~250 天，避免拉 1540 根 K 线浪费 30+ 秒。"""
    # 默认 start 是 20200101，意味着每次都拉 5+ 年（~1500 根）。
    # 实际只需 250 根，所以把 start 设到「半年前」就够覆盖了。
    import datetime
    start = (datetime.date.today() - datetime.timedelta(days=400)).strftime("%Y%m%d")
    return ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start, end_date="21000101", adjust="qfq",
    )


def _fetch_kline_tencent(symbol: str) -> pd.DataFrame:
    """腾讯日 K（直连）"""
    code = f"{_market_prefix(symbol)}{symbol}"
    r = requests.get(
        "http://web.ifzq.gtimg.cn/appstock/app/kline/kline",
        params={"param": f"{code},day,,,250,qfq"},
        headers={**_BROWSER_HEADERS, "Referer": "http://gu.qq.com/"},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"腾讯错误码: {data.get('code')}")
    rows = (data.get("data", {}).get(code, {}).get("qfqday")
            or data.get("data", {}).get(code, {}).get("day"))
    if not rows:
        raise RuntimeError("腾讯无数据")
    return pd.DataFrame([r[:6] for r in rows],
                        columns=["date", "open", "close", "high", "low", "volume"])


def _fetch_kline_sina(symbol: str) -> pd.DataFrame:
    """新浪日 K（直连）"""
    code = f"{_market_prefix(symbol)}{symbol}"
    r = requests.get(
        "http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
        params={"symbol": code, "scale": "240", "ma": "no", "datalen": "250"},
        headers=_BROWSER_HEADERS, timeout=10,
    )
    r.raise_for_status()
    text = r.text.strip()
    if not text.startswith("["):
        s, e = text.find("["), text.rfind("]")
        if s < 0 or e < 0:
            raise RuntimeError(f"新浪格式异常: {text[:100]}")
        text = text[s:e + 1]
    rows = json.loads(text)
    if not rows:
        raise RuntimeError("新浪无数据")
    return pd.DataFrame(rows).rename(columns={"day": "date"})


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名 + 类型转换 + 自动算 change_pct"""
    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low",
        "成交量": "volume", "成交额": "turnover",
        "振幅": "amplitude", "涨跌幅": "change_pct",
        "涨跌额": "change_amount", "换手率": "turnover_rate",
        "day": "date",
        "datetime": "date",
        "vol": "volume",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for col in ["open", "close", "high", "low", "volume", "turnover",
                "amplitude", "change_pct", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "change_pct" not in df.columns and "close" in df.columns:
        df["change_pct"] = (df["close"].pct_change() * 100).round(3)
    return df


# ════════════════════════════════════════════════════════════════
#  对外接口
# ════════════════════════════════════════════════════════════════

# K 线源优先级表（修改这里就能调顺序）
_KLINE_SOURCES = [
    ("通达信", _fetch_kline_tdx),     # ← 主力：TCP socket，反爬绝缘
    ("东财",   _fetch_kline_em),
    ("新浪",   _fetch_kline_sina),
    ("腾讯",   _fetch_kline_tencent),
]


def probe_data_sources(test_symbol: str = "600519"):
    """
    启动探测：并行测试 4 个数据源，失败的源直接标记 dead。
    并行后总用时 ≈ 单源最慢的那个 + 通达信 bestip（5-10s 量级，原版 60-90s）。
    """
    if ak is None:
        return

    # 1) 通达信 bestip 选服务器（这一步本身就要 3-5s，必须先做）
    if HAS_TDX:
        _init_tdx_client()

    print(f"\n[探测] 并行测试 {len(_KLINE_SOURCES)} 个数据源 (用 {test_symbol})...")

    def _probe_one(name_fn):
        name, fn = name_fn
        if name == "通达信" and not HAS_TDX:
            return name, False, "mootdx 未安装", None
        t0 = time.monotonic()
        try:
            # 注意：探测阶段**绕过 _rate_limit**，因为 4 个源是 4 个不同的服务器，
            # 没有任何一个服务器会被同时打两次。原版串行 + 1.5s × 4 = 6s 是白等的。
            df = fn(test_symbol)
            elapsed = time.monotonic() - t0
            if df is not None and not df.empty:
                return name, True, f"{len(df)} 条 / {elapsed:.1f}s", None
            return name, False, f"返回空 / {elapsed:.1f}s", None
        except Exception as e:
            elapsed = time.monotonic() - t0
            return name, False, f"{type(e).__name__} / {elapsed:.1f}s", e

    with ThreadPoolExecutor(max_workers=len(_KLINE_SOURCES)) as ex:
        futures = [ex.submit(_probe_one, s) for s in _KLINE_SOURCES]
        results = []
        for f in as_completed(futures):
            results.append(f.result())

    # 按 _KLINE_SOURCES 的顺序输出（不按完成顺序），方便用户看到优先级
    order = {name: i for i, (name, _) in enumerate(_KLINE_SOURCES)}
    results.sort(key=lambda x: order[x[0]])

    for name, ok, detail, err in results:
        if ok:
            _mark_source_ok(name)
            print(f"  ✓ {name:4s} 可用 ({detail})")
        else:
            with _dead_lock:
                _dead_sources[name] = time.time()
                _source_fail_count[name] = DEAD_THRESHOLD
            print(f"  ✗ {name:4s} 失败 ({detail})，标记不可用")

    with _dead_lock:
        available = [s for s, _ in _KLINE_SOURCES if s not in _dead_sources]
    print(f"[探测] 可用源: {' / '.join(available) if available else '无（将走磁盘缓存）'}\n")


def fetch_kline(symbol: str, days: int = 250, retries: int = 3) -> pd.DataFrame:
    """
    A 股日 K 线。按 _KLINE_SOURCES 顺序依次试，全失败则用磁盘缓存。
    一只一只串行调用（全局 1.5s 限流）。
    某源连续网络失败 2 次后会被标记不可用，10 分钟内后续股票跳过它。

    v3.1 变化：始终打印使用的源（之前通达信/东财成功时静默，导致看不出实际优先级）。
    """
    if ak is None:
        raise RuntimeError("akshare 未安装")

    last_err = None
    for name, fn in _KLINE_SOURCES:
        if _is_source_dead(name):
            continue
        try:
            _rate_limit()
            df = fn(symbol)
            if df is None or df.empty:
                continue  # 业务层"没数据"，不算源不可用，继续 fallback
            df = _normalize(df).tail(days).reset_index(drop=True)
            _mark_source_ok(name)
            # 始终打印实际使用的源 —— 修复"看不出走的是通达信还是东财"
            logger.info(f"[{symbol}] K 线来源 → {name}（{len(df)} 行）")
            _save_cache(symbol, df)
            return df
        except Exception as e:
            last_err = e
            is_net = _is_network_error(e)
            _mark_source_failed(name, is_net)
            tag = "网络失败" if is_net else "业务失败"
            logger.warning(f"[{symbol}] {name} {tag}: {type(e).__name__}: {e}")

    # 全部源失败 → 磁盘缓存
    cached = _load_cache(symbol)
    if cached is not None and len(cached) >= 20:
        logger.warning(f"[{symbol}] 所有在线源失败，使用磁盘缓存")
        return cached.tail(days).reset_index(drop=True)

    raise last_err or RuntimeError(f"{symbol} 数据获取失败")


def fetch_stock_info(symbol: str) -> dict:
    """
    股票基本信息（名称、市盈率、市净率等）。
    注意：mootdx 协议**不提供**基本面字段，所以这里没有通达信通道。
    路径：东财单股 (akshare) → 新浪实时行情 → 腾讯实时行情 → fallback
    """
    fallback = {"name": symbol, "industry": "N/A", "market_cap": "N/A",
                "pe_ratio": "N/A", "pb_ratio": "N/A",
                "total_shares": "N/A", "float_shares": "N/A"}

    # ─ 路径 1: 东财单股详情（akshare，字段最全：name + industry + PE + PB）
    if ak is not None and not _is_source_dead("东财"):
        try:
            _rate_limit()
            info = ak.stock_individual_info_em(symbol=symbol)
            d = dict(zip(info.iloc[:, 0], info.iloc[:, 1]))
            _mark_source_ok("东财")
            return {
                "name":         str(d.get("股票简称", symbol)),
                "industry":     str(d.get("行业", "N/A")),
                "market_cap":   str(d.get("总市值", "N/A")),
                "pe_ratio":     str(d.get("市盈率(动)", "N/A")),
                "pb_ratio":     str(d.get("市净率", "N/A")),
                "total_shares": str(d.get("总股本", "N/A")),
                "float_shares": str(d.get("流通股本", "N/A")),
            }
        except Exception as e:
            is_net = _is_network_error(e)
            _mark_source_failed("东财", is_net)
            logger.debug(f"[{symbol}] 东财单股失败: {e}")

    # ─ 路径 2: 新浪实时行情（hq.sinajs.cn，能拿到 name + 价格，无 PE/PB）
    if not _is_source_dead("新浪"):
        try:
            _rate_limit()
            code = f"{_market_prefix(symbol)}{symbol}"
            r = requests.get(
                f"http://hq.sinajs.cn/list={code}",
                headers={**_BROWSER_HEADERS, "Referer": "https://finance.sina.com.cn"},
                timeout=8,
            )
            r.raise_for_status()
            quoted = r.text.split('"')
            if len(quoted) >= 2 and quoted[1]:
                fields = quoted[1].split(",")
                if fields[0]:
                    _mark_source_ok("新浪")
                    return {
                        "name":         fields[0],
                        "industry":     "N/A",
                        "market_cap":   "N/A",
                        "pe_ratio":     "N/A",
                        "pb_ratio":     "N/A",
                        "total_shares": "N/A",
                        "float_shares": "N/A",
                    }
        except Exception as e:
            _mark_source_failed("新浪", _is_network_error(e))
            logger.debug(f"[{symbol}] 新浪实时行情失败: {e}")

    # ─ 路径 3: 腾讯实时行情
    if not _is_source_dead("腾讯"):
        try:
            _rate_limit()
            code = f"{_market_prefix(symbol)}{symbol}"
            r = requests.get(
                f"http://qt.gtimg.cn/q={code}",
                headers={**_BROWSER_HEADERS, "Referer": "http://gu.qq.com/"},
                timeout=8,
            )
            r.raise_for_status()
            fields = r.text.split('"', 2)[1].split("~")
            if len(fields) >= 5 and fields[1]:
                _mark_source_ok("腾讯")
                return {
                    "name":         fields[1],
                    "industry":     "N/A",
                    "market_cap":   (fields[45] + "亿") if len(fields) > 45 and fields[45] else "N/A",
                    "pe_ratio":     fields[39] if len(fields) > 39 and fields[39] not in ("", "-") else "N/A",
                    "pb_ratio":     fields[46] if len(fields) > 46 and fields[46] not in ("", "-") else "N/A",
                    "total_shares": "N/A",
                    "float_shares": "N/A",
                }
        except Exception as e:
            _mark_source_failed("腾讯", _is_network_error(e))
            logger.debug(f"[{symbol}] 腾讯实时行情失败: {e}")

    return fallback


print(f"[fetcher] 加载 v{__version__}  限流 {MIN_INTERVAL}s · 并行探测 · 多源 fallback · 磁盘缓存")
