"""
ai.py — AI 辅助决策
────────────────────
合并自旧版两个模块：
  - ai_advisor.py    → 个股 AI（AIAdvisor + build_prompt）
  - commodity_ai.py  → 大宗商品 AI（CommodityAIAdvisor）

对外接口保持兼容：
  build_prompt, AIAdvisor          ← 旧 ai_advisor
  CommodityAIAdvisor               ← 旧 commodity_ai
"""
import os
import json
import re
import datetime
from loguru import logger

try:
    from openai import OpenAI, APIError, APITimeoutError, RateLimitError
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai 库未安装，AI 功能不可用")

# 从合并后的 analysis 模块取 snapshot helper
from analysis import get_recent_snapshot


# ════════════════════════════════════════════════════════════════
# Part 1：个股 AI prompt 构建
# ════════════════════════════════════════════════════════════════

def build_prompt(
    symbol: str,
    stock_info: dict,
    df,
    supports: list,
    resistances: list,
    sr_relation: dict,
    commodity_context: str = "",
) -> str:
    last = df.iloc[-1]
    prev = df.iloc[-2]
    recent = get_recent_snapshot(df, n=10)

    # ── 当前价格状态 ────────────────────────────────────
    price = last["close"]
    change_pct = last.get("change_pct", 0) or 0

    # ── MACD ───────────────────────────────────────────
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

    macd_above_zero = "是" if dif > 0 else "否"

    recent_close = df["close"].tail(10)
    recent_hist = df["macd_hist"].tail(10)
    divergence = "无"
    if recent_close.iloc[-1] <= recent_close.min() and recent_hist.iloc[-1] > recent_hist.min():
        divergence = "疑似底背离（价格新低但MACD柱未创新低）"
    elif recent_close.iloc[-1] >= recent_close.max() and recent_hist.iloc[-1] < recent_hist.max():
        divergence = "疑似顶背离（价格新高但MACD柱未创新高）"

    # ── 布林带 ──────────────────────────────────────────
    bb_upper = last.get("bb_upper", 0) or 0
    bb_mid = last.get("bb_mid", 0) or 0
    bb_lower = last.get("bb_lower", 0) or 0
    bb_width = last.get("bb_width", 0) or 0
    bb_pct = last.get("bb_pct", 0.5) or 0.5

    recent_bw = df["bb_width"].tail(20)
    bb_squeeze = "是（布林带收窄，可能变盘）" if bb_width < recent_bw.mean() * 0.85 else "否"

    # ── 均线 ────────────────────────────────────────────
    ma_lines = {}
    for n in [5, 10, 20, 60]:
        col = f"ma{n}"
        if col in last.index:
            ma_lines[f"MA{n}"] = round(last[col], 3)
    ma_arrangement = _describe_ma_arrangement(price, ma_lines)

    # ── 成交量 ──────────────────────────────────────────
    volume = last.get("volume", 0) or 0
    vol_ratio = last.get("vol_ratio", 1) or 1
    turnover_rate = last.get("turnover_rate", 0) or 0
    tr_ma5 = last.get("turnover_rate_ma5", 0) or 0

    vol_desc = (f"成交量：{volume:,.0f}手，量比：{vol_ratio:.2f}"
                f"（{_vol_desc(vol_ratio)}）")
    tr_desc = f"换手率：{turnover_rate:.2f}%（5日均换手率：{tr_ma5:.2f}%）"

    # ── RSI ─────────────────────────────────────────────
    rsi = last.get("rsi", 50) or 50

    # ── 支撑/压力位 ─────────────────────────────────────
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

    # ── 组装 prompt ─────────────────────────────────────
    prompt = f"""你是一位专业的A股技术分析师，请根据以下完整数据给出严谨的操作建议。

═══════════════════════════════════════════════
【基本信息】
股票代码:{symbol}　股票名称:{stock_info.get('name', symbol)}
行业:{stock_info.get('industry', 'N/A')}　市盈率:{stock_info.get('pe_ratio', 'N/A')}　市净率:{stock_info.get('pb_ratio', 'N/A')}
最新交易日:{last['date'].strftime('%Y-%m-%d') if hasattr(last['date'], 'strftime') else last['date']}
当日收盘价:{price:.3f}元　涨跌幅:{change_pct:+.2f}%

═══════════════════════════════════════════════
【支撑位与压力位】(综合极值法+量价聚类+整数关口)
所有支撑位(升序):{supports}
所有压力位(升序):{resistances}
{chr(10).join(sr_text)}

═══════════════════════════════════════════════
【均线系统】
{ma_arrangement}
各均线数值:{json.dumps(ma_lines, ensure_ascii=False)}

═══════════════════════════════════════════════
【MACD指标】(12/26/9)
DIF:{dif:.4f}　DEA:{dea:.4f}　MACD柱:{hist:.4f}
前一日 DIF:{prev_dif:.4f}　前一日 DEA:{prev_dea:.4f}　前一日 MACD柱:{prev_hist:.4f}
金/死叉情况:{macd_cross}
DIF是否在零轴上方:{macd_above_zero}
背离信号:{divergence}

═══════════════════════════════════════════════
【布林带】(20日 2倍标准差)
上轨:{bb_upper:.3f}　中轨(MA20):{bb_mid:.3f}　下轨:{bb_lower:.3f}
当前价在带内位置:{bb_pct:.1%}(0%=下轨, 100%=上轨)
带宽(波动率指标):{bb_width:.2f}%　带宽是否收窄:{bb_squeeze}

═══════════════════════════════════════════════
【成交量与换手率】
{vol_desc}
{tr_desc}

═══════════════════════════════════════════════
【RSI(14日)】
RSI:{rsi:.2f}　(超卖区<30,超买区>70)

═══════════════════════════════════════════════
【最近10根K线完整数据】(用于判断形态、趋势和量价配合)
{json.dumps(recent, ensure_ascii=False, indent=2)}

{commodity_context}

═══════════════════════════════════════════════
【请严格按以下JSON格式回答,只返回JSON,不要有任何额外文字】
{{
  "decision": "买入 / 卖出 / 持有 / 观望",
  "confidence": "高 / 中 / 低",
  "key_reasons": ["原因1(结合具体数值)", "原因2", "原因3"],
  "risk_warnings": ["风险1", "风险2"],
  "suggested_entry": 建议买入价(数字,如不适用填null),
  "suggested_stop_loss": 建议止损价(数字,如不适用填null),
  "suggested_target_short": 短期目标价(数字,如不适用填null),
  "suggested_target_long": 长期目标价(数字,如不适用填null),
  "summary": "一句话综合判断"
}}
仅返回 JSON,不要任何额外解释。
"""
    return prompt


# ════════════════════════════════════════════════════════════════
# Part 2：个股 AI 调用
# ════════════════════════════════════════════════════════════════

class AIAdvisor:
    def __init__(self, api_key: str, base_url: str, model: str,
                 temperature: float = 0.2, max_tokens: int = 800, timeout: int = 60,
                 enable_thinking: bool = False, thinking_effort: str = "high"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.enable_thinking = enable_thinking
        self.thinking_effort = thinking_effort
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
        """调用 AI 返回解析后的字典；失败时返回 {decision: ERROR, summary: ...}"""
        try:
            client = self._get_client()

            kwargs = dict(
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
                max_tokens=self.max_tokens,
            )

            if self.enable_thinking:
                kwargs["reasoning_effort"] = self.thinking_effort
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                logger.debug(f"AI 思考模式已开启（effort={self.thinking_effort}）")
            else:
                kwargs["temperature"] = self.temperature

            response = client.chat.completions.create(**kwargs)
            raw = response.choices[0].message.content.strip()

            if self.enable_thinking:
                rc = getattr(response.choices[0].message, "reasoning_content", None)
                if rc:
                    logger.debug(f"思维链（前200字）: {rc[:200]}")

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
        clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        try:
            return json.loads(clean)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if match:
            candidate = match.group(0)
            if candidate.rstrip().endswith(','):
                candidate = candidate.rstrip()[:-1] + '}'
            if not candidate.strip().endswith('}'):
                candidate = candidate + '}'
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                dec_match = re.search(r'"decision"\s*:\s*"([^"]+)"', candidate)
                if dec_match:
                    return {"decision": dec_match.group(1), "summary": "AI 回复被截断", "raw": candidate}

        logger.warning(f"AI 回复无法解析为 JSON，原文：{raw[:200]}")
        decision = "观望"
        for kw in ["买入", "卖出", "持有", "观望"]:
            if kw in raw:
                decision = kw
                break
        return {"decision": decision, "summary": raw[:300], "raw": raw}


# ════════════════════════════════════════════════════════════════
# Part 3：内部工具函数
# ════════════════════════════════════════════════════════════════

def _vol_desc(vol_ratio: float) -> str:
    if vol_ratio >= 3:   return "天量，极度放量"
    if vol_ratio >= 2:   return "大幅放量"
    if vol_ratio >= 1.5: return "明显放量"
    if vol_ratio >= 0.8: return "量能正常"
    if vol_ratio >= 0.5: return "明显缩量"
    return "极度缩量"


def _describe_ma_arrangement(price: float, ma_lines: dict) -> str:
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

    ma_vals = dict(values)
    if all([
        ma_vals.get("MA5", 0)  >= ma_vals.get("MA10", 0),
        ma_vals.get("MA10", 0) >= ma_vals.get("MA20", 0),
        ma_vals.get("MA20", 0) >= ma_vals.get("MA60", 0),
    ]):
        parts.append("均线呈多头排列")
    elif all([
        ma_vals.get("MA5", 999)  <= ma_vals.get("MA10", 999),
        ma_vals.get("MA10", 999) <= ma_vals.get("MA20", 999),
        ma_vals.get("MA20", 999) <= ma_vals.get("MA60", 999),
    ]):
        parts.append("均线呈空头排列")
    else:
        parts.append("均线交织，趋势不明")

    return "；".join(parts)


# ════════════════════════════════════════════════════════════════
# Part 4：大宗商品 AI（原 commodity_ai.py）
# ════════════════════════════════════════════════════════════════

# 产业影响映射表（AI 离线时的规则兜底）
RULE_IMPACT = {
    "CL": [
        {"sector": "化工",     "up": "利空（成本上升）",          "down": "利多（成本下降）"},
        {"sector": "航空",     "up": "利空（航油成本上升）",      "down": "利多（航油成本下降）"},
        {"sector": "能源",     "up": "利多（油气股业绩改善）",    "down": "利空（油气股业绩承压）"},
        {"sector": "交通运输", "up": "利空（燃油成本上升）",      "down": "利多（燃油成本下降）"},
    ],
    "GC": [
        {"sector": "黄金珠宝", "up": "利多（黄金股随金价上涨）", "down": "利空（黄金股承压）"},
        {"sector": "避险情绪", "up": "利空权益（市场避险情绪升温）", "down": "利多权益（避险需求减弱）"},
    ],
    "HG": [
        {"sector": "新能源",   "up": "利空（铜成本上升，影响电车/光伏）", "down": "利多（新能源用铜成本改善）"},
        {"sector": "电气设备", "up": "利空（变压器/电线原材料成本上升）", "down": "利多（原材料成本下降）"},
        {"sector": "地产建筑", "up": "利空（建材成本上升）",      "down": "利多（建材成本下降）"},
    ],
    "RB": [
        {"sector": "钢铁",     "up": "利多（钢价上涨改善钢企利润）", "down": "利空（钢企利润承压）"},
        {"sector": "地产建筑", "up": "利空（建材成本上升压缩利润）", "down": "利多（建材成本下降）"},
        {"sector": "机械设备", "up": "利空（制造成本上升）",      "down": "利多（制造成本下降）"},
    ],
    "ZS": [
        {"sector": "农牧饲料", "up": "利空（豆粕饲料成本上升）",  "down": "利多（饲料成本下降利好养殖端）"},
        {"sector": "食品",     "up": "利空（食用油/豆制品原料成本上升）", "down": "利多（食品原料成本下降）"},
    ],
    "ZC": [
        {"sector": "农牧饲料", "up": "利空（玉米饲料成本上升）",  "down": "利多（饲料成本改善）"},
        {"sector": "生物燃料", "up": "利多（燃料乙醇价值提升）",  "down": "利空（燃料乙醇盈利空间压缩）"},
    ],
}


class CommodityAIAdvisor:
    def __init__(self, api_key: str, base_url: str, model: str,
                 temperature: float = 0.3, max_tokens: int = 2000, timeout: int = 90,
                 enable_thinking: bool = False, thinking_effort: str = "high"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.enable_thinking = enable_thinking
        self.thinking_effort = thinking_effort
        self._client = None

    def _get_client(self):
        if not HAS_OPENAI:
            raise RuntimeError("openai 未安装")
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def analyze(self, commodities: list[dict]) -> dict:
        if not HAS_OPENAI or not self.api_key:
            return self._rule_fallback(commodities)

        try:
            client = self._get_client()
            prompt = self._build_prompt(commodities)

            kwargs = dict(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "你是一位资深大宗商品分析师和行业研究员，精通大宗商品价格变动对A股各行业的传导机制。"
                            "请严格按 JSON 格式输出，不要有任何额外解释。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=self.max_tokens,
            )

            if self.enable_thinking:
                kwargs["reasoning_effort"] = self.thinking_effort
                kwargs["extra_body"] = {"thinking": {"type": "enabled"}}
                logger.debug(f"大宗商品 AI 思考模式已开启（effort={self.thinking_effort}）")
            else:
                kwargs["temperature"] = self.temperature

            resp = client.chat.completions.create(**kwargs)
            raw  = resp.choices[0].message.content.strip()
            return self._parse(raw, commodities)

        except APITimeoutError:
            logger.error("大宗商品 AI 超时，使用规则兜底")
            return self._rule_fallback(commodities)
        except RateLimitError:
            logger.error("大宗商品 AI 限速，使用规则兜底")
            return self._rule_fallback(commodities)
        except Exception as e:
            logger.error(f"大宗商品 AI 分析失败: {e}")
            return self._rule_fallback(commodities)

    def _build_prompt(self, commodities: list[dict]) -> str:
        lines = []
        for c in commodities:
            sign = "+" if c["change_pct"] >= 0 else ""
            lines.append(
                f"  {c['name']}（{c['code']}）：{c['price']} {c['unit']}，"
                f"涨跌幅 {sign}{c['change_pct']}%"
            )
        comm_text = "\n".join(lines)

        return f"""以下是当前全球大宗商品最新行情：

{comm_text}

请分析每个大宗商品的价格走势对A股相关产业与行业的**短期影响**（1-4周内）。

要求：
1. 每个商品分析 2-3 个受影响最大的行业/板块
2. 每个行业说明：是利多还是利空，以及核心传导逻辑（结合具体数值）
3. 举出 2-3 个代表性A股公司代码或名称（仅供参考）
4. 最后给出整体宏观一句话总结

请严格按以下 JSON 格式返回，不要有 markdown 或额外说明：

{{
  "summary": "当前大宗商品整体走势宏观一句话判断",
  "items": [
    {{
      "commodity": "商品中文名",
      "code": "商品代码",
      "price": 数字,
      "change_pct": 数字,
      "trend": "上行/下行/震荡",
      "affected_sectors": [
        {{
          "sector": "行业名称",
          "impact": "利多/利空/中性",
          "reason": "传导逻辑（含数值）",
          "stocks_hint": "代表性公司（2-3个）"
        }}
      ]
    }}
  ]
}}"""

    def _parse(self, raw: str, commodities: list[dict]) -> dict:
        clean = re.sub(r"```(?:json)?", "", raw).strip().strip("`").strip()
        try:
            result = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", clean, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except Exception:
                    return self._rule_fallback(commodities)
            else:
                return self._rule_fallback(commodities)

        result["updated_at"] = datetime.datetime.now().isoformat()
        result["source"] = "ai"
        return result

    def _rule_fallback(self, commodities: list[dict]) -> dict:
        items = []
        for c in commodities:
            code  = c["code"]
            pct   = c["change_pct"]
            is_up = pct >= 0
            trend = "上行" if pct > 0.5 else "下行" if pct < -0.5 else "震荡"
            sectors = []

            for mapping in RULE_IMPACT.get(code, []):
                impact_text = mapping["up"] if is_up else mapping["down"]
                if "利多" in impact_text:
                    impact = "利多"
                elif "利空" in impact_text:
                    impact = "利空"
                else:
                    impact = "中性"
                sectors.append({
                    "sector":      mapping["sector"],
                    "impact":      impact,
                    "reason":      f"{c['name']} {'上涨' if is_up else '下跌'} {abs(pct):.2f}%，{impact_text}",
                    "stocks_hint": "请参考行业龙头企业"
                })

            items.append({
                "commodity":        c["name"],
                "code":             code,
                "price":            c["price"],
                "change_pct":       pct,
                "trend":            trend,
                "affected_sectors": sectors,
            })

        return {
            "summary":    "当前大宗商品数据已加载，AI 分析需配置 DeepSeek API Key（ENABLE_AI=True）。",
            "items":      items,
            "updated_at": datetime.datetime.now().isoformat(),
            "source":     "rule",
        }
