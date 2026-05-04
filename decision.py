"""
综合决策模块
将规则引擎 + AI 建议整合，输出最终决策
"""
import json
from dataclasses import dataclass, field
from loguru import logger


# ────────────────────────────────────────────────────────────────
#  数据类
# ────────────────────────────────────────────────────────────────

@dataclass
class DecisionResult:
    symbol: str
    stock_name: str
    price: float
    date: str

    rule_signal: str = "观望"        # 规则引擎信号
    rule_reasons: list = field(default_factory=list)

    ai_decision: str = "N/A"        # AI 建议
    ai_confidence: str = "N/A"
    ai_reasons: list = field(default_factory=list)
    ai_risks: list = field(default_factory=list)
    ai_entry: float = None
    ai_stop_loss: float = None
    ai_target: float = None
    ai_target_short: float = None
    ai_target_long: float = None
    ai_summary: str = ""


    final_decision: str = "观望"    # 综合最终决策
    alert_level: str = "normal"     # normal / warning / strong

    def to_log_string(self) -> str:
        lines = [
            f"{'=' * 55}",
            f"  [{self.symbol}] {self.stock_name}  {self.date}  收盘：{self.price:.3f}",
            f"{'=' * 55}",
            f"  规则信号：{self.rule_signal}",
        ]
        for r in self.rule_reasons:
            lines.append(f"    · {r}")
        if self.ai_decision != "N/A":
            lines.append(f"  AI 建议：{self.ai_decision}（置信度：{self.ai_confidence}）")
            lines.append(f"  AI 摘要：{self.ai_summary}")
            for r in self.ai_reasons:
                lines.append(f"    · {r}")
            if self.ai_entry:
                lines.append(f"  建议入场：{self.ai_entry}  止损：{self.ai_stop_loss}  短期目标：{self.ai_target_short}  长期目标：{self.ai_target_long}")
            if self.ai_risks:
                lines.append("  风险提示：" + "；".join(self.ai_risks))
        lines.append(f"  ★ 最终决策：{self.final_decision}  [{self.alert_level.upper()}]")
        lines.append(f"{'=' * 55}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.stock_name,
            "price": self.price,
            "date": self.date,
            "rule_signal": self.rule_signal,
            "ai_target_short": self.ai_target_short,
            "ai_target_long": self.ai_target_long,
            "ai_decision": self.ai_decision,
            "final_decision": self.final_decision,
            "alert_level": self.alert_level,
            "ai_summary": self.ai_summary,
        }


# ────────────────────────────────────────────────────────────────
#  规则引擎
# ────────────────────────────────────────────────────────────────

def rule_engine(df, supports: list, resistances: list, sr_relation: dict) -> tuple[str, list]:
    """
    返回 (信号, 原因列表)
    信号：买入 / 卖出 / 持有 / 观望
    """
    last = df.iloc[-1]
    prev = df.iloc[-2]
    reasons = []
    buy_score = 0
    sell_score = 0

    price = last["close"]

    # ── 支撑/压力位 ──────────────────────────────────────────────
    if sr_relation.get("broke_support"):
        sell_score += 3
        reasons.append(f"⚠️ 价格跌破最近支撑位 {sr_relation['nearest_support']}")
    elif sr_relation.get("near_support"):
        buy_score += 1
        reasons.append(f"✓ 价格接近支撑位 {sr_relation['nearest_support']}（距支撑 {sr_relation['pct_above_support']:+.2f}%）")
    if sr_relation.get("near_resistance"):
        sell_score += 1
        reasons.append(f"⚠️ 价格接近压力位 {sr_relation['nearest_resistance']}（距压力 {sr_relation['pct_below_resistance']:.2f}%）")

    # ── MACD ─────────────────────────────────────────────────────
    dif = last.get("dif", 0) or 0
    dea = last.get("dea", 0) or 0
    hist = last.get("macd_hist", 0) or 0
    prev_dif = prev.get("dif", 0) or 0
    prev_dea = prev.get("dea", 0) or 0

    if dif > dea and prev_dif <= prev_dea:
        buy_score += 2
        reasons.append(f"✓ MACD 金叉（DIF={dif:.4f} 上穿 DEA={dea:.4f}）")
    elif dif < dea and prev_dif >= prev_dea:
        sell_score += 2
        reasons.append(f"⚠️ MACD 死叉（DIF={dif:.4f} 下穿 DEA={dea:.4f}）")

    if hist > 0 and (prev.get("macd_hist", 0) or 0) <= 0:
        buy_score += 1
        reasons.append("✓ MACD 柱由负转正")
    elif hist < 0 and (prev.get("macd_hist", 0) or 0) >= 0:
        sell_score += 1
        reasons.append("⚠️ MACD 柱由正转负")

    # ── 布林带 ────────────────────────────────────────────────────
    bb_lower = last.get("bb_lower", 0) or 0
    bb_upper = last.get("bb_upper", 0) or 0
    bb_mid = last.get("bb_mid", 0) or 0

    if bb_lower > 0 and price <= bb_lower * 1.005:
        buy_score += 2
        reasons.append(f"✓ 价格触及布林下轨（下轨={bb_lower:.3f}）")
    if bb_upper > 0 and price >= bb_upper * 0.995:
        sell_score += 2
        reasons.append(f"⚠️ 价格触及布林上轨（上轨={bb_upper:.3f}）")

    # ── 均线 ──────────────────────────────────────────────────────
    ma5 = last.get("ma5", 0) or 0
    ma20 = last.get("ma20", 0) or 0
    ma60 = last.get("ma60", 0) or 0
    prev_ma5 = prev.get("ma5", 0) or 0
    prev_ma20 = prev.get("ma20", 0) or 0

    # 价格站上 MA20（均线金叉思路）
    if ma20 > 0 and price > ma20 and prev["close"] <= prev_ma20:
        buy_score += 1
        reasons.append(f"✓ 价格站上 MA20（{ma20:.3f}）")
    if ma20 > 0 and price < ma20 and prev["close"] >= prev_ma20:
        sell_score += 1
        reasons.append(f"⚠️ 价格跌破 MA20（{ma20:.3f}）")

    # MA5 金叉 MA20
    if ma5 > 0 and ma20 > 0:
        if ma5 > ma20 and prev_ma5 <= prev_ma20:
            buy_score += 1
            reasons.append("✓ MA5 上穿 MA20（短期金叉）")
        elif ma5 < ma20 and prev_ma5 >= prev_ma20:
            sell_score += 1
            reasons.append("⚠️ MA5 下穿 MA20（短期死叉）")

    # ── RSI ────────────────────────────────────────────────────
    rsi = last.get("rsi", 50) or 50
    if rsi < 30:
        buy_score += 1
        reasons.append(f"✓ RSI 超卖（RSI={rsi:.1f}）")
    elif rsi > 70:
        sell_score += 1
        reasons.append(f"⚠️ RSI 超买（RSI={rsi:.1f}）")

    # ── 成交量配合 ────────────────────────────────────────────────
    vol_ratio = last.get("vol_ratio", 1) or 1
    if buy_score > sell_score and vol_ratio >= 1.5:
        buy_score += 1
        reasons.append(f"✓ 放量配合多方信号（量比={vol_ratio:.2f}）")
    elif sell_score > buy_score and vol_ratio >= 1.5:
        sell_score += 1
        reasons.append(f"⚠️ 放量配合空方信号（量比={vol_ratio:.2f}）")

    # ── 最终信号 ──────────────────────────────────────────────────
    if buy_score >= 4 and buy_score > sell_score + 1:
        signal = "买入"
    elif sell_score >= 4 and sell_score > buy_score + 1:
        signal = "卖出"
    elif buy_score >= 2 and buy_score > sell_score:
        signal = "持有"   # 偏多但不强烈
    elif sell_score >= 2 and sell_score > buy_score:
        signal = "观望"   # 偏空但不强烈
    else:
        signal = "观望"

    reasons.insert(0, f"规则得分 → 买入信号：{buy_score}分，卖出信号：{sell_score}分")
    return signal, reasons


# ────────────────────────────────────────────────────────────────
#  综合决策
# ────────────────────────────────────────────────────────────────

def make_final_decision(
    symbol: str,
    stock_name: str,
    df,
    supports: list,
    resistances: list,
    sr_relation: dict,
    ai_result: dict = None,
) -> DecisionResult:

    last = df.iloc[-1]
    price = float(last["close"])
    date_str = str(last["date"])[:10]

    result = DecisionResult(
        symbol=symbol,
        stock_name=stock_name,
        price=price,
        date=date_str,
    )
    result.ai_target_short = ai_result.get("suggested_target_short") if ai_result else None
    result.ai_target_long = ai_result.get("suggested_target_long") if ai_result else None
    # 规则引擎
    rule_signal, rule_reasons = rule_engine(df, supports, resistances, sr_relation)
    result.rule_signal = rule_signal
    result.rule_reasons = rule_reasons

    # AI 结果
    if ai_result and ai_result.get("decision") not in ("ERROR", None):
        result.ai_decision = ai_result.get("decision", "观望")
        result.ai_confidence = ai_result.get("confidence", "低")
        result.ai_reasons = ai_result.get("key_reasons", [])
        result.ai_risks = ai_result.get("risk_warnings", [])
        result.ai_entry = ai_result.get("suggested_entry")
        result.ai_stop_loss = ai_result.get("suggested_stop_loss")
        result.ai_target = ai_result.get("suggested_target")
        result.ai_summary = ai_result.get("summary", "")

    # ── 最终综合逻辑 ──────────────────────────────────────────────
    ai_d = result.ai_decision
    rule_d = result.rule_signal

    BUY_WORDS = {"买入"}
    SELL_WORDS = {"卖出"}

    both_buy = rule_d in BUY_WORDS and ai_d in BUY_WORDS
    both_sell = rule_d in SELL_WORDS and ai_d in SELL_WORDS
    rule_buy_ai_hold = rule_d in BUY_WORDS and ai_d in {"持有", "观望"}
    ai_buy_rule_hold = ai_d in BUY_WORDS and rule_d in {"持有", "观望"}
    both_conflict = (rule_d in BUY_WORDS and ai_d in SELL_WORDS) or \
                    (rule_d in SELL_WORDS and ai_d in BUY_WORDS)

    if both_buy:
        result.final_decision = "强烈买入"
        result.alert_level = "strong"
    elif both_sell:
        result.final_decision = "强烈卖出"
        result.alert_level = "strong"
    elif both_conflict:
        result.final_decision = "信号冲突，观望"
        result.alert_level = "warning"
    elif rule_buy_ai_hold or ai_buy_rule_hold:
        result.final_decision = "买入（信号一般）"
        result.alert_level = "warning"
    elif rule_d in SELL_WORDS or ai_d in SELL_WORDS:
        result.final_decision = "倾向卖出/减仓"
        result.alert_level = "warning"
    elif ai_d == "N/A":
        result.final_decision = rule_signal
        result.alert_level = "normal" if rule_signal == "观望" else "warning"
    else:
        result.final_decision = "观望"
        result.alert_level = "normal"

    return result
