"""
commodity_ai.py
───────────────
大宗商品 AI 分析模块

输入：当前大宗商品价格列表
输出：各品种对产业/行业的短期影响分析（JSON 结构）

返回格式：
{
  "updated_at": "...",
  "summary": "一句话宏观概述",
  "items": [
    {
      "commodity": "原油(WTI)",
      "code": "CL",
      "price": 82.35,
      "change_pct": -0.54,
      "trend": "下行",         # 上行 / 下行 / 震荡
      "affected_sectors": [
        {
          "sector": "化工",
          "impact": "利多",     # 利多 / 利空 / 中性
          "reason": "原油下跌降低乙烯/PTA 等化工原料成本，利好中下游化工企业利润修复",
          "stocks_hint": "万华化学、恒力石化、荣盛石化"
        },
        ...
      ]
    }
  ]
}
"""

import json
import re
import datetime
from loguru import logger

try:
    from openai import OpenAI, APIError, APITimeoutError, RateLimitError
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    logger.warning("openai 未安装，大宗商品 AI 分析不可用")


# ── 产业影响映射（规则兜底，AI 离线时使用）────────────────────
RULE_IMPACT = {
    "CL": [  # 原油
        {"sector": "化工", "up": "利空（成本上升）", "down": "利多（成本下降）"},
        {"sector": "航空", "up": "利空（航油成本上升）", "down": "利多（航油成本下降）"},
        {"sector": "能源", "up": "利多（油气股业绩改善）", "down": "利空（油气股业绩承压）"},
        {"sector": "交通运输", "up": "利空（燃油成本上升）", "down": "利多（燃油成本下降）"},
    ],
    "GC": [  # 黄金
        {"sector": "黄金珠宝", "up": "利多（黄金股随金价上涨）", "down": "利空（黄金股承压）"},
        {"sector": "避险情绪", "up": "利空权益（市场避险情绪升温）", "down": "利多权益（避险需求减弱）"},
    ],
    "HG": [  # 铜
        {"sector": "新能源", "up": "利空（铜成本上升，影响电车/光伏）", "down": "利多（新能源用铜成本改善）"},
        {"sector": "电气设备", "up": "利空（变压器/电线原材料成本上升）", "down": "利多（原材料成本下降）"},
        {"sector": "地产建筑", "up": "利空（建材成本上升）", "down": "利多（建材成本下降）"},
    ],
    "RB": [  # 螺纹钢
        {"sector": "钢铁", "up": "利多（钢价上涨改善钢企利润）", "down": "利空（钢企利润承压）"},
        {"sector": "地产建筑", "up": "利空（建材成本上升压缩利润）", "down": "利多（建材成本下降）"},
        {"sector": "机械设备", "up": "利空（制造成本上升）", "down": "利多（制造成本下降）"},
    ],
    "ZS": [  # 大豆
        {"sector": "农牧饲料", "up": "利空（豆粕饲料成本上升）", "down": "利多（饲料成本下降利好养殖端）"},
        {"sector": "食品", "up": "利空（食用油/豆制品原料成本上升）", "down": "利多（食品原料成本下降）"},
    ],
    "ZC": [  # 玉米
        {"sector": "农牧饲料", "up": "利空（玉米饲料成本上升）", "down": "利多（饲料成本改善）"},
        {"sector": "生物燃料", "up": "利多（燃料乙醇价值提升）", "down": "利空（燃料乙醇盈利空间压缩）"},
    ],
}


class CommodityAIAdvisor:
    def __init__(self, api_key: str, base_url: str, model: str,
                 temperature: float = 0.3, max_tokens: int = 2000, timeout: int = 90):
        self.api_key    = api_key
        self.base_url   = base_url
        self.model      = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout    = timeout
        self._client    = None

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
        """
        发送大宗商品数据到 AI，返回结构化产业影响分析
        """
        if not HAS_OPENAI or not self.api_key:
            return self._rule_fallback(commodities)

        try:
            client  = self._get_client()
            prompt  = self._build_prompt(commodities)
            resp    = client.chat.completions.create(
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
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            raw = resp.choices[0].message.content.strip()
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

    # ────────────────────────────────────────────────────────
    #  Prompt 构建
    # ────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────
    #  解析 AI 回复
    # ────────────────────────────────────────────────────────
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

    # ────────────────────────────────────────────────────────
    #  规则引擎兜底（AI 不可用时）
    # ────────────────────────────────────────────────────────
    def _rule_fallback(self, commodities: list[dict]) -> dict:
        items = []
        for c in commodities:
            code    = c["code"]
            pct     = c["change_pct"]
            is_up   = pct >= 0
            trend   = "上行" if pct > 0.5 else "下行" if pct < -0.5 else "震荡"
            sectors = []

            for mapping in RULE_IMPACT.get(code, []):
                impact_text = mapping["up"] if is_up else mapping["down"]
                # 判断利多/利空/中性
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
                "commodity":       c["name"],
                "code":            code,
                "price":           c["price"],
                "change_pct":      pct,
                "trend":           trend,
                "affected_sectors": sectors,
            })

        return {
            "summary": "当前大宗商品数据已加载，AI 分析需配置 DeepSeek API Key（ENABLE_AI=True）。",
            "items":   items,
            "updated_at": datetime.datetime.now().isoformat(),
            "source": "rule",
        }
