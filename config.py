"""
config.py
─────────
从 config.yaml 读取所有配置。
配置文件路径：程序同目录下的 config.yaml
"""

from pathlib import Path
from loguru import logger

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    logger.warning("pyyaml 未安装（pip install pyyaml），将使用内置默认值")

CONFIG_FILE = Path("config.yaml")

# ── 内置默认值（config.yaml 缺失或字段空缺时使用）──────────
_DEFAULT: dict = {
    "ai": {
        "api_key":     "",
        "base_url":    "https://api.deepseek.com",
        "model":       "deepseek-chat",
        "enabled":     True,
        "max_tokens":  2000,
        "temperature": 0.2,
        "timeout":     60,
        "thinking":    {"enabled": False, "effort": "high"},
    },
    "stocks": {
        "codes":                    ["000001", "600519"],
        "kline_days":               250,
        "interval_minutes":         60,
        "trading_hours":            "",
        "sr_window":                10,
        "sr_count":                 3,
        "support_tolerance_pct":    2.0,
        "resistance_tolerance_pct": 2.0,
    },
    "alerts": {
        "enable_sound": False,
    },
}


def _deep_get(d: dict, *keys, default=None):
    """安全多级取值：_deep_get(d, 'ai', 'api_key', default='')"""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
        if cur is None:
            return default
    return cur


class Config:
    def __init__(self):
        raw = self._load()

        ai      = raw.get("ai", {})
        stocks  = raw.get("stocks", {})
        alerts  = raw.get("alerts", {})
        thinking = ai.get("thinking", {})

        # ── AI ─────────────────────────────────────────────────
        self.ai_api_key     = str(ai.get("api_key",     "") or "").strip()
        self.ai_base_url    = str(ai.get("base_url",    "https://api.deepseek.com")).strip()
        self.ai_model       = str(ai.get("model",       "deepseek-chat")).strip()
        self.enable_ai      = bool(ai.get("enabled",    True))
        self.ai_max_tokens  = int(ai.get("max_tokens",  2000))
        self.ai_temperature = float(ai.get("temperature", 0.2))
        self.ai_timeout     = int(ai.get("timeout",     60))

        self.enable_thinking = bool(thinking.get("enabled", False))
        self.thinking_effort = str(thinking.get("effort", "high")).strip().lower()

        # ── 股票 ───────────────────────────────────────────────
        raw_codes = stocks.get("codes", ["000001", "600519"])
        if isinstance(raw_codes, list):
            self.stock_codes = [str(c).strip() for c in raw_codes if str(c).strip()]
        else:
            # 兼容逗号分隔字符串写法
            self.stock_codes = [c.strip() for c in str(raw_codes).split(",") if c.strip()]

        self.kline_days               = int(stocks.get("kline_days",               250))
        self.sr_window                = int(stocks.get("sr_window",                10))
        self.sr_count                 = int(stocks.get("sr_count",                 3))
        self.interval_minutes         = int(stocks.get("interval_minutes",         60))
        self.trading_hours            = str(stocks.get("trading_hours",            "") or "")
        self.support_tolerance_pct    = float(stocks.get("support_tolerance_pct",    2.0))
        self.resistance_tolerance_pct = float(stocks.get("resistance_tolerance_pct", 2.0))

        # ── 提醒 ───────────────────────────────────────────────
        self.enable_sound = bool(alerts.get("enable_sound", False))

    # ────────────────────────────────────────────────────────
    def _load(self) -> dict:
        if not HAS_YAML:
            return dict(_DEFAULT)
        if not CONFIG_FILE.exists():
            logger.warning(f"未找到 {CONFIG_FILE}，使用内置默认值（建议复制一份 config.yaml）")
            return dict(_DEFAULT)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            logger.info(f"已加载配置：{CONFIG_FILE.resolve()}")
            return data
        except Exception as e:
            logger.error(f"读取 {CONFIG_FILE} 失败：{e}，使用内置默认值")
            return dict(_DEFAULT)

    def print_summary(self):
        logger.info(f"监控股票：{self.stock_codes}")
        logger.info(f"轮询间隔：{self.interval_minutes} 分钟")
        logger.info(
            f"AI：{'开启' if self.enable_ai else '关闭'} | 模型：{self.ai_model}"
            + (f" | 思考模式 [{self.thinking_effort}]" if self.enable_thinking else "")
        )
