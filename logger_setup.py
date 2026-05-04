"""
日志配置模块
使用 loguru，自动按天轮转，保留 30 天
"""
import os
import sys
from loguru import logger


def setup_logger(app_path: str):
    log_dir = os.path.join(app_path, "logs")
    os.makedirs(log_dir, exist_ok=True)

    logger.remove()  # 移除默认 handler

    # 控制台输出（带颜色）
    logger.add(
        sys.stdout,
        level="INFO",
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
        colorize=True,
    )

    # 文件输出（每天轮转，保留 30 天）
    logger.add(
        os.path.join(log_dir, "stock_{time:YYYY-MM-DD}.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
        rotation="00:00",       # 每天午夜轮转
        retention="30 days",
        encoding="utf-8",
    )

    # 单独记录错误
    logger.add(
        os.path.join(log_dir, "errors.log"),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}",
        rotation="10 MB",
        retention="60 days",
        encoding="utf-8",
    )
