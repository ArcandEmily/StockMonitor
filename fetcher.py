"""
数据抓取模块
- A股日K线数据（akshare → 东方财富）
- 股票基本信息（名称、市值、换手率等）
- WallStreet.cn 大宗商品价格（预留接口，未来接入）
"""
import time
import requests
import pandas as pd
from loguru import logger

try:
    import akshare as ak
except ImportError:
    ak = None
    logger.warning("akshare 未安装，数据抓取功能不可用")


# ────────────────────────────────────────────────────────────────
#  A 股 K 线数据
# ────────────────────────────────────────────────────────────────

def fetch_kline(symbol: str, days: int = 250, retries: int = 3) -> pd.DataFrame:
    """
    从东方财富抓取日K线（前复权）
    返回列：date, open, close, high, low, volume, turnover,
             turnover_rate, amplitude, change_pct
    """
    if ak is None:
        raise RuntimeError("akshare 未安装")

    for attempt in range(1, retries + 1):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date="20200101",
                end_date="21000101",
                adjust="qfq",        # 前复权
            )
            break
        except Exception as e:
            logger.warning(f"[{symbol}] 抓取K线第 {attempt}/{retries} 次失败: {e}")
            if attempt == retries:
                raise
            time.sleep(3 * attempt)

    # 标准化列名
    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",          # 单位：手
        "成交额": "turnover",        # 单位：元
        "振幅": "amplitude",         # %
        "涨跌幅": "change_pct",      # %
        "涨跌额": "change_amount",
        "换手率": "turnover_rate",   # %
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.tail(days).reset_index(drop=True)

    # 类型转换
    for col in ["open", "close", "high", "low", "volume", "turnover",
                "amplitude", "change_pct", "turnover_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.debug(f"[{symbol}] 获取 {len(df)} 条K线，"
                 f"最新：{df.iloc[-1]['date'].date()}  收盘：{df.iloc[-1]['close']}")
    return df


def fetch_stock_info(symbol: str) -> dict:
    """
    获取股票基本信息（名称、所属行业、总市值等）
    """
    if ak is None:
        return {"name": symbol, "industry": "N/A", "market_cap": "N/A"}

    try:
        info = ak.stock_individual_info_em(symbol=symbol)
        # info 是两列 DataFrame：item / value
        d = dict(zip(info.iloc[:, 0], info.iloc[:, 1]))
        return {
            "name": d.get("股票简称", symbol),
            "industry": d.get("行业", "N/A"),
            "market_cap": d.get("总市值", "N/A"),
            "pe_ratio": d.get("市盈率(动)", "N/A"),
            "pb_ratio": d.get("市净率", "N/A"),
            "total_shares": d.get("总股本", "N/A"),
            "float_shares": d.get("流通股本", "N/A"),
        }
    except Exception as e:
        logger.warning(f"[{symbol}] 获取股票信息失败: {e}")
        return {"name": symbol, "industry": "N/A", "market_cap": "N/A"}


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
