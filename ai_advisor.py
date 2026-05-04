"""
AI 辅助决策模块
- 构建精细化 prompt（含完整数值数据，非简单定性描述）
- 调用 DeepSeek API（OpenAI 兼容接口）
- 解析 AI 回复，提取结构化建议
"""
import os
import json
import re
from loguru import logger

try:
    from openai import OpenAI, APIError, APITimeoutError, RateLimitError
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai 库未安装，AI 功能不可用")

from indicators import get_recent_snapshot


# ────────────────────────────────────────────────────────────────
#  Prompt 构建
# ────────────────────────────────────────────────────────────────

def build_prompt(
    symbol: str,
    stock_info: dict,
    df,                   # 完整 DataFrame（含指标）
    supports: list,
    resistances: list,
    sr_relation: dict,
    commodity_context: str = "",   # 大宗商品段落（可为空）
) -> str:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    recent = get_recent_snapshot(df, n=10)   # 最近 10 根K线详细数据

    # ── 当前价格状态 ────────────────────────────────────────────
    price = last["close"]
    change_pct = last.get("change_pct", 0) or 0

    # ── MACD 状态 ───────────────────────────────────────────────
    dif = last.get("dif", 0) or 0
    dea = last.get("dea", 0) or 0
    hist = last.get("macd_hist", 0) or 0
    prev_dif = prev.get("dif", 0) or 0
    prev_dea = prev.get("dea", 0) or 0
    prev_hist = prev.get("macd_hist", 0) or 0

    if dif > dea and prev_dif <= prev_dea:
        macd_cross = "今日金叉（DIF上穿DEA）"
    elif dif < dea and prev_dif >= prev_dea:
        macd_cross = "今日死叉（DIF下穿DEA）"
    else:
        macd_cross = "无交叉"

    # 是否在零轴上方
    macd_above_zero = "是" if dif > 0 else "否"

    # 底背离/顶背离判断（简化版：近10根内价格创新低但MACD未创新低）
    recent_close = df["close"].tail(10)
    recent_hist = df["macd_hist"].tail(10)
    divergence = "无"
    if recent_close.iloc[-1] <= recent_close.min() and recent_hist.iloc[-1] > recent_hist.min():
        divergence = "疑似底背离（价格新低但MACD柱未创新低）"
    elif recent_close.iloc[-1] >= recent_close.max() and recent_hist.iloc[-1] < recent_hist.max():
        divergence = "疑似顶背离（价格新高但MACD柱未创新高）"

    # ── 布林带 ──────────────────────────────────────────────────
    bb_upper = last.get("bb_upper", 0) or 0
    bb_mid = last.get("bb_mid", 0) or 0
    bb_lower = last.get("bb_lower", 0) or 0
    bb_width = last.get("bb_width", 0) or 0
    bb_pct = last.get("bb_pct", 0.5) or 0.5

    # 带宽是否收窄（相对近 20 日均值）
    recent_bw = df["bb_width"].tail(20)
    bb_squeeze = "是（布林带收窄，可能变盘）" if bb_width < recent_bw.mean() * 0.85 else "否"

    # ── 均线系统 ────────────────────────────────────────────────
    ma_lines = {}
    for n in [5, 10, 20, 60]:
        col = f"ma{n}"
        if col in last.index:
            ma_lines[f"MA{n}"] = round(last[col], 3)

    ma_arrangement = _describe_ma_arrangement(price, ma_lines)

    # ── 成交量 ──────────────────────────────────────────────────
    volume = last.get("volume", 0) or 0
    vol_ratio = last.get("vol_ratio", 1) or 1
    turnover_rate = last.get("turnover_rate", 0) or 0
    tr_ma5 = last.get("turnover_rate_ma5", 0) or 0

    vol_desc = (
        f"成交量：{volume:,.0f}手，量比：{vol_ratio:.2f}"
        f"（{_vol_desc(vol_ratio)}）"
    )
    tr_desc = f"换手率：{turnover_rate:.2f}%（5日均换手率：{tr_ma5:.2f}%）"

    # ── RSI ─────────────────────────────────────────────────────
    rsi = last.get("rsi", 50) or 50

    # ── 支撑/压力位关系 ──────────────────────────────────────────
    ns = sr_relation.get("nearest_support")
    nr = sr_relation.get("nearest_resistance")
    pct_sup = sr_relation.get("pct_above_support")
    pct_res = sr_relation.get("pct_below_resistance")

    sr_text = []
    if ns:
        sr_text.append(f"最近支撑：{ns}（当前价高于支撑 {pct_sup:+.2f}%）")
    if nr:
        sr_text.append(f"最近压力：{nr}（压力高于当前价 {pct_res:.2f}%）")
    if sr_relation.get("broke_support"):
        sr_text.append("⚠️ 当前价已跌破最近支撑！")
    if sr_relation.get("near_support"):
        sr_text.append("📌 当前价接近支撑位")
    if sr_relation.get("near_resistance"):
        sr_text.append("📌 当前价接近压力位")

    # ── 组装 prompt ─────────────────────────────────────────────
    prompt = f"""你是一位专业的A股技术分析师，请根据以下完整数据给出严谨的操作建议。

═══════════════════════════════════════════════
【基本信息】
股票代码：{symbol}　股票名称：{stock_info.get('name', symbol)}
行业：{stock_info.get('industry', 'N/A')}　市盈率：{stock_info.get('pe_ratio', 'N/A')}　市净率：{stock_info.get('pb_ratio', 'N/A')}
最新交易日：{last['date'].strftime('%Y-%m-%d') if hasattr(last['date'], 'strftime') else last['date']}
当日收盘价：{price:.3f}元　涨跌幅：{change_pct:+.2f}%

═══════════════════════════════════════════════
【支撑位与压力位】（综合极值法 + 量价聚类 + 整数关口）
所有支撑位（升序）：{supports}
所有压力位（升序）：{resistances}
{chr(10).join(sr_text)}

═══════════════════════════════════════════════
【均线系统】
{ma_arrangement}
各均线数值：{json.dumps(ma_lines, ensure_ascii=False)}

═══════════════════════════════════════════════
【MACD 指标】（12/26/9）
DIF：{dif:.4f}　DEA：{dea:.4f}　MACD柱：{hist:.4f}
前一日 DIF：{prev_dif:.4f}　前一日 DEA：{prev_dea:.4f}　前一日 MACD柱：{prev_hist:.4f}
金/死叉情况：{macd_cross}
DIF是否在零轴上方：{macd_above_zero}
背离信号：{divergence}

═══════════════════════════════════════════════
【布林带】（20日 2倍标准差）
上轨：{bb_upper:.3f}　中轨（MA20）：{bb_mid:.3f}　下轨：{bb_lower:.3f}
当前价在带内位置：{bb_pct:.1%}（0%=下轨, 100%=上轨）
带宽（波动率指标）：{bb_width:.2f}%　带宽是否收窄：{bb_squeeze}

═══════════════════════════════════════════════
【成交量与换手率】
{vol_desc}
{tr_desc}

═══════════════════════════════════════════════
【RSI（14日）】
RSI：{rsi:.2f}　（超卖区<30，超买区>70）

═══════════════════════════════════════════════
【最近10根K线完整数据】（用于判断形态、趋势和量价配合）
{json.dumps(recent, ensure_ascii=False, indent=2)}

{commodity_context}

═══════════════════════════════════════════════
【请严格按以下JSON格式回答，只返回JSON，不要有任何额外文字】
{{
  "decision": "买入 / 卖出 / 持有 / 观望",
  "confidence": "高 / 中 / 低",
  "key_reasons": ["原因1（结合具体数值）", "原因2", "原因3"],
  "risk_warnings": ["风险1", "风险2"],
  "suggested_entry": 建议买入价（数字，如不适用填null）,
  "suggested_stop_loss": 建议止损价（数字，如不适用填null）,
  "suggested_target_short": 短期目标价（数字，如不适用填null）,
  "suggested_target_long": 长期目标价（数字，如不适用填null）,
  "summary": "一句话综合判断"
}}
仅返回 JSON，不要任何额外解释。
"""
    return prompt


# ────────────────────────────────────────────────────────────────
#  AI 调用
# ────────────────────────────────────────────────────────────────

class AIAdvisor:
    def __init__(self, api_key: str, base_url: str, model: str,
                 temperature: float = 0.2, max_tokens: int = 800, timeout: int = 60):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _get_client(self):
        if not HAS_OPENAI:
            raise RuntimeError("openai 库未安装")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def query(self, prompt: str) -> dict:
        """
        调用 AI，返回解析后的结构化建议字典
        失败时返回 {"decision": "ERROR", "summary": 错误信息}
        """
        try:
            client = self._get_client()
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位资深A股技术分析师，擅长结合MACD、布林带、量价关系和支撑压力位进行综合研判。"
                            "你的回答严格以JSON格式输出，数据驱动，不主观臆测。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            raw = response.choices[0].message.content.strip()
            return self._parse_response(raw)

        except APITimeoutError:
            logger.error("AI 调用超时")
            return {"decision": "ERROR", "summary": "AI调用超时"}
        except RateLimitError:
            logger.error("AI 调用触发限速")
            return {"decision": "ERROR", "summary": "API限速，请稍后重试"}
        except APIError as e:
            logger.error(f"AI API 错误: {e}")
            return {"decision": "ERROR", "summary": str(e)}
        except Exception as e:
            logger.error(f"AI 调用未知错误: {e}")
            return {"decision": "ERROR", "summary": str(e)}

    @staticmethod
    def _parse_response(raw: str) -> dict:
        """从 AI 返回文本中提取 JSON"""
        # 去除 markdown 代码块
        clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()

        # 尝试直接解析
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        # 尝试找 JSON 对象
        match = re.search(r"\{.*\}", clean, re.DOTALL)
if match:
    candidate = match.group(1)
    # 如果以逗号结尾，去掉末尾逗号并补上 }
    if candidate.rstrip().endswith(','):
        candidate = candidate.rstrip()[:-1] + '}'
    # 如果明显不完整（最后不是 }），尝试补全
    if not candidate.strip().endswith('}'):
        # 尝试补全闭合
        candidate = candidate + '}'
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # 最后手段：只提取 decision 字段
        dec_match = re.search(r'"decision"\s*:\s*"([^"]+)"', candidate)
        if dec_match:
            return {"decision": dec_match.group(1), "summary": "AI 回复被截断", "raw": candidate}
            
        # 最后：从文本提取关键词
        logger.warning(f"AI 回复无法解析为 JSON，原文：{raw[:200]}")
        decision = "观望"
        for kw in ["买入", "卖出", "持有", "观望"]:
            if kw in raw:
                decision = kw
                break
        return {"decision": decision, "summary": raw[:300], "raw": raw}


# ────────────────────────────────────────────────────────────────
#  工具函数
# ────────────────────────────────────────────────────────────────

def _vol_desc(vol_ratio: float) -> str:
    if vol_ratio >= 3:
        return "天量，极度放量"
    if vol_ratio >= 2:
        return "大幅放量"
    if vol_ratio >= 1.5:
        return "明显放量"
    if vol_ratio >= 0.8:
        return "量能正常"
    if vol_ratio >= 0.5:
        return "明显缩量"
    return "极度缩量"


def _describe_ma_arrangement(price: float, ma_lines: dict) -> str:
    """描述均线多/空头排列"""
    values = [(k, v) for k, v in ma_lines.items() if v and v > 0]
    if not values:
        return "均线数据不足"

    above = [k for k, v in values if price > v]
    below = [k for k, v in values if price < v]

    parts = []
    if above:
        parts.append(f"价格高于 {', '.join(above)}")
    if below:
        parts.append(f"价格低于 {', '.join(below)}")

    # 判断多/空头排列（MA5 > MA10 > MA20 > MA60）
    ma_vals = {k: v for k, v in values}
    if all([
        ma_vals.get("MA5", 0) >= ma_vals.get("MA10", 0),
        ma_vals.get("MA10", 0) >= ma_vals.get("MA20", 0),
        ma_vals.get("MA20", 0) >= ma_vals.get("MA60", 0),
    ]):
        parts.append("均线呈多头排列")
    elif all([
        ma_vals.get("MA5", 999) <= ma_vals.get("MA10", 999),
        ma_vals.get("MA10", 999) <= ma_vals.get("MA20", 999),
        ma_vals.get("MA20", 999) <= ma_vals.get("MA60", 999),
    ]):
        parts.append("均线呈空头排列")
    else:
        parts.append("均线交织，趋势不明")

    return "；".join(parts)
