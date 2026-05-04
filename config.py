"""
配置管理模块
从 .env 文件读取所有配置
"""
import os
from loguru import logger


class Config:
    def __init__(self):
        # ── DeepSeek / OpenAI 兼容 AI ──────────────────────────────
        self.ai_api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.ai_base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.ai_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
        self.enable_ai = os.getenv("ENABLE_AI", "True").strip().lower() == "true"
        self.ai_temperature = float(os.getenv("AI_TEMPERATURE", "0.2"))
        self.ai_max_tokens = int(os.getenv("AI_MAX_TOKENS", "800"))
        self.ai_timeout = int(os.getenv("AI_TIMEOUT_SECONDS", "60"))

        # ── 股票列表 ────────────────────────────────────────────────
        raw_codes = os.getenv("STOCK_CODES", "000001,600519")
        self.stock_codes = [c.strip() for c in raw_codes.split(",") if c.strip()]

        # ── 数据参数 ────────────────────────────────────────────────
        self.kline_days = int(os.getenv("KLINE_DAYS", "250"))
        self.sr_window = int(os.getenv("SR_WINDOW", "10"))    # 支撑/压力位识别窗口
        self.sr_count = int(os.getenv("SR_COUNT", "3"))       # 保留几个支撑/压力位

        # ── 调度 ────────────────────────────────────────────────────
        self.interval_minutes = int(os.getenv("INTERVAL_MINUTES", "60"))
        # 只在交易时段运行（留空则全天运行，可填 "09:30-11:30,13:00-15:00"）
        self.trading_hours = os.getenv("TRADING_HOURS", "")

        # ── 决策阈值 ────────────────────────────────────────────────
        # 价格在支撑位 N% 以内视为"靠近支撑"
        self.support_tolerance_pct = float(os.getenv("SUPPORT_TOLERANCE_PCT", "2.0"))
        # 价格在压力位 N% 以内视为"靠近压力"
        self.resistance_tolerance_pct = float(os.getenv("RESISTANCE_TOLERANCE_PCT", "2.0"))

        # ── WallStreet.cn 大宗商品接口（预留，暂未启用）───────────────
        self.enable_commodity = os.getenv("ENABLE_COMMODITY", "False").strip().lower() == "true"
        self.wallstreet_api_key = os.getenv("WALLSTREET_API_KEY", "")
        # 关注的大宗商品代码，如 "crude_oil,gold,copper"
        raw_commodities = os.getenv("COMMODITY_CODES", "")
        self.commodity_codes = [c.strip() for c in raw_commodities.split(",") if c.strip()]

        # ── 报警 ────────────────────────────────────────────────────
        # 声音提示（需要 Windows 环境）
        self.enable_sound = os.getenv("ENABLE_SOUND", "False").strip().lower() == "true"

    def print_summary(self):
        logger.info(f"监控股票：{self.stock_codes}")
        logger.info(f"轮询间隔：{self.interval_minutes} 分钟")
        logger.info(f"AI 辅助决策：{'开启' if self.enable_ai else '关闭'} | 模型：{self.ai_model}")
        logger.info(f"大宗商品辅助：{'开启' if self.enable_commodity else '关闭（预留接口）'}")
        logger.info(f"K线天数：{self.kline_days}，支撑/压力窗口：{self.sr_window}")
