"""
调度模块
- 定时轮询所有股票
- 异常自动恢复
- 支持交易时段过滤
"""
import time
import datetime
import json
import os
from loguru import logger

from config import Config
from fetcher import fetch_kline, fetch_stock_info, CommodityFetcher
from indicators import calc_indicators
from analysis import find_support_resistance, describe_sr_relation
from ai_advisor import build_prompt, AIAdvisor
from decision import make_final_decision


class StockScheduler:
    def __init__(self, cfg: Config):
        self.cfg = cfg

        self.ai_advisor = None
        if cfg.enable_ai:
            if not cfg.ai_api_key:
                logger.warning("ENABLE_AI=True 但 DEEPSEEK_API_KEY 未设置，AI 功能将禁用")
            else:
                self.ai_advisor = AIAdvisor(
                    api_key=cfg.ai_api_key,
                    base_url=cfg.ai_base_url,
                    model=cfg.ai_model,
                    temperature=cfg.ai_temperature,
                    max_tokens=cfg.ai_max_tokens,
                    timeout=cfg.ai_timeout,
                )
                logger.info(f"AI 已就绪，模型：{cfg.ai_model}，接口：{cfg.ai_base_url}")

        self.commodity_fetcher = CommodityFetcher(
            api_key=cfg.wallstreet_api_key,
            commodity_codes=cfg.commodity_codes,
        )

        # 结果历史（内存）
        self._results: list[dict] = []

    # ────────────────────────────────────────────────────────────
    #  主任务
    # ────────────────────────────────────────────────────────────

    def run_job(self):
        """执行一轮所有股票分析"""
        now = datetime.datetime.now()
        logger.info(f"─── 开始新一轮分析 {now.strftime('%Y-%m-%d %H:%M:%S')} ───")

        if not self._in_trading_hours(now):
            logger.info("当前不在配置的交易时段，跳过本轮")
            return

        # 大宗商品数据（预留）
        commodity_data = {}
        if self.cfg.enable_commodity and self.commodity_fetcher.is_configured():
            commodity_data = self.commodity_fetcher.fetch()
        commodity_context = self.commodity_fetcher.format_for_prompt(commodity_data)

        for symbol in self.cfg.stock_codes:
            try:
                self._analyze_one(symbol, commodity_context)
            except Exception as e:
                logger.error(f"[{symbol}] 分析失败（将在下一轮重试）: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        logger.info(f"─── 本轮分析完成，下次将在 {self.cfg.interval_minutes} 分钟后执行 ───\n")

    def _analyze_one(self, symbol: str, commodity_context: str = ""):
        logger.info(f"[{symbol}] 开始分析...")

        # 1. 数据抓取
        df = fetch_kline(symbol, days=self.cfg.kline_days)
        if df is None or len(df) < 60:
            logger.warning(f"[{symbol}] 数据不足 60 条，跳过")
            return

        stock_info = fetch_stock_info(symbol)

        # 2. 技术指标
        df = calc_indicators(df)

        # 3. 支撑/压力位
        supports, resistances = find_support_resistance(
            df,
            window=self.cfg.sr_window,
            keep=self.cfg.sr_count,
        )
        sr_rel = describe_sr_relation(
            current_price=float(df.iloc[-1]["close"]),
            supports=supports,
            resistances=resistances,
            tolerance_pct=self.cfg.support_tolerance_pct,
        )

        # 4. AI 分析
        ai_result = None
        if self.ai_advisor:
            prompt = build_prompt(
                symbol=symbol,
                stock_info=stock_info,
                df=df,
                supports=supports,
                resistances=resistances,
                sr_relation=sr_rel,
                commodity_context=commodity_context,
            )
            logger.debug(f"[{symbol}] Prompt 长度：{len(prompt)} 字符")
            ai_result = self.ai_advisor.query(prompt)
            logger.debug(f"[{symbol}] AI 原始回复: {json.dumps(ai_result, ensure_ascii=False)}")

        # 5. 综合决策
        result = make_final_decision(
            symbol=symbol,
            stock_name=stock_info.get("name", symbol),
            df=df,
            supports=supports,
            resistances=resistances,
            sr_relation=sr_rel,
            ai_result=ai_result,
        )

        # 6. 输出
        logger.info("\n" + result.to_log_string())
        self._results.append(result.to_dict())
        self._save_result(result)

        # 7. 报警
        if result.alert_level == "strong":
            self._alert(result)

    # ────────────────────────────────────────────────────────────
    #  定时器
    # ────────────────────────────────────────────────────────────

    def start(self):
        interval_sec = self.cfg.interval_minutes * 60
        logger.info(f"定时任务启动，间隔 {self.cfg.interval_minutes} 分钟")

        while True:
            try:
                time.sleep(interval_sec)
                self.run_job()
            except SystemExit:
                logger.info("收到退出信号，调度器停止")
                break
            except KeyboardInterrupt:
                logger.info("用户中断，调度器停止")
                break
            except Exception as e:
                logger.error(f"主循环异常（将在 60 秒后重试）: {e}")
                time.sleep(60)

    # ────────────────────────────────────────────────────────────
    #  工具
    # ────────────────────────────────────────────────────────────

    def _in_trading_hours(self, now: datetime.datetime) -> bool:
        """检查当前是否在配置的交易时段内（留空则全天运行）"""
        if not self.cfg.trading_hours:
            return True
        segments = self.cfg.trading_hours.split(",")
        current = now.time()
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            parts = seg.split("-")
            if len(parts) != 2:
                continue
            try:
                start = datetime.time(*[int(x) for x in parts[0].split(":")])
                end = datetime.time(*[int(x) for x in parts[1].split(":")])
                if start <= current <= end:
                    return True
            except ValueError:
                pass
        return False

    def _save_result(self, result):
        """将决策结果追加保存为 JSONL 日志"""
        try:
            log_dir = "logs"
            os.makedirs(log_dir, exist_ok=True)
            today = datetime.date.today().strftime("%Y-%m-%d")
            path = os.path.join(log_dir, f"decisions_{today}.jsonl")
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning(f"保存决策结果失败: {e}")

    def _alert(self, result):
        """强信号报警"""
        msg = f"🔔 强信号！{result.symbol} {result.stock_name} → {result.final_decision}  价格：{result.price:.3f}"
        logger.warning(msg)

        if self.cfg.enable_sound:
            try:
                import winsound
                for _ in range(3):
                    winsound.Beep(1000, 500)
                    time.sleep(0.3)
            except Exception:
                pass  # 非 Windows 或 winsound 不可用，静默忽略
