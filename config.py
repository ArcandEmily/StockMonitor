"""
config.py
─────────
配置加载（config.yaml）+ 日志初始化。

合并自旧版：
  - config.py        → 配置类 Config
  - logger_setup.py  → setup_logger()
"""
import os
import sys
from pathlib import Path
from loguru import logger

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    logger.warning("pyyaml 未安装（pip install pyyaml），将使用内置默认值")

CONFIG_FILE = Path("config.yaml")

# 模块级标记：Config 多次实例化时只 INFO 打印一次
_load_logged: bool = False

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


# ════════════════════════════════════════════════════════════════
#  Config 类
# ════════════════════════════════════════════════════════════════

class Config:
    def __init__(self):
        raw = self._load()

        ai       = raw.get("ai", {})
        stocks   = raw.get("stocks", {})
        alerts   = raw.get("alerts", {})
        thinking = ai.get("thinking", {})

        # ── AI ─────────────────────────────────────────────
        self.ai_api_key     = str(ai.get("api_key",     "") or "").strip()
        self.ai_base_url    = str(ai.get("base_url",    "https://api.deepseek.com")).strip()
        self.ai_model       = str(ai.get("model",       "deepseek-chat")).strip()
        self.enable_ai      = bool(ai.get("enabled",    True))
        self.ai_max_tokens  = int(ai.get("max_tokens",  2000))
        self.ai_temperature = float(ai.get("temperature", 0.2))
        self.ai_timeout     = int(ai.get("timeout",     60))

        self.enable_thinking = bool(thinking.get("enabled", False))
        self.thinking_effort = str(thinking.get("effort", "high")).strip().lower()

        # ── 股票 ───────────────────────────────────────────
        raw_codes = stocks.get("codes", ["000001", "600519"])
        if isinstance(raw_codes, list):
            self.stock_codes = [str(c).strip() for c in raw_codes if str(c).strip()]
        else:
            self.stock_codes = [c.strip() for c in str(raw_codes).split(",") if c.strip()]

        self.kline_days               = int(stocks.get("kline_days",               250))
        self.sr_window                = int(stocks.get("sr_window",                10))
        self.sr_count                 = int(stocks.get("sr_count",                 3))
        self.interval_minutes         = int(stocks.get("interval_minutes",         60))
        self.trading_hours            = str(stocks.get("trading_hours",            "") or "")
        self.support_tolerance_pct    = float(stocks.get("support_tolerance_pct",    2.0))
        self.resistance_tolerance_pct = float(stocks.get("resistance_tolerance_pct", 2.0))

        # ── 提醒 ───────────────────────────────────────────
        self.enable_sound = bool(alerts.get("enable_sound", False))

    def _load(self) -> dict:
        global _load_logged
        if not HAS_YAML:
            return dict(_DEFAULT)
        if not CONFIG_FILE.exists():
            if not _load_logged:
                logger.warning(f"未找到 {CONFIG_FILE}，使用内置默认值（建议复制一份 config.yaml）")
                _load_logged = True
            return dict(_DEFAULT)
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not _load_logged:
                logger.info(f"已加载配置：{CONFIG_FILE.resolve()}")
                _load_logged = True
            else:
                logger.debug(f"重新读取配置：{CONFIG_FILE}")
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


# ════════════════════════════════════════════════════════════════
#  日志初始化（原 logger_setup.py）
# ════════════════════════════════════════════════════════════════

def setup_logger(app_path: str):
    """配置 loguru：控制台 + 按天轮转的日志文件 + 错误单独存档"""
    log_dir = os.path.join(app_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger.remove()

    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )

    logger.add(
        os.path.join(log_dir, "stock_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
        rotation="00:00",
        retention="30 days",
        encoding="utf-8",
    )

    logger.add(
        os.path.join(log_dir, "errors.log"),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
        rotation="10 MB",
        retention="60 days",
        encoding="utf-8",
    )
