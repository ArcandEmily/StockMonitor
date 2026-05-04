"""
StockMonitor · Flask 后端
────────────────────────
启动方式：
    python server.py
然后浏览器打开 http://localhost:5000

API 路由：
    GET  /api/stocks          → 所有股票摘要列表
    GET  /api/stock/<code>    → 单只股票完整数据
    POST /api/stock/add       → 添加股票  body: {"code":"600519"}
    POST /api/stock/remove    → 删除股票  body: {"code":"600519"}
    POST /api/stock/refresh   → 刷新单只  body: {"code":"600519"}
    GET  /api/status          → 服务状态
"""

import os
import sys
import json
import time
import threading
import datetime
import traceback

from flask import Flask, jsonify, request, send_from_directory

# ── 项目模块 ───────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
    from config import Config
    from fetcher import fetch_kline, fetch_stock_info
    from indicators import calc_indicators
    from analysis import find_support_resistance, describe_sr_relation
    from ai_advisor import build_prompt, AIAdvisor
    from decision import make_final_decision, rule_engine
    HAS_MODULES = True
except ImportError as e:
    print(f"[警告] 部分模块未安装，将使用 Demo 数据: {e}")
    HAS_MODULES = False

# ══════════════════════════════════════════════════════════════
#  Demo 数据（无依赖时使用）
# ══════════════════════════════════════════════════════════════
DEMO_STOCKS = {
    "600519": {
        "code": "600519", "name": "贵州茅台", "price": 1567.00, "change": 36.60,
        "decision": "强烈买入", "rule": "买入",
        "dif": 12.45, "dea": 8.32, "hist": 8.26,
        "bbU": 1602, "bbM": 1548, "bbL": 1494, "bbPct": 0.64, "bbW": 6.97,
        "rsi": 58.4, "vr": 1.82, "tr": 1.23,
        "ma5": 1552, "ma10": 1538, "ma20": 1548, "ma60": 1490,
        "sups": [1520, 1490, 1455], "ress": [1600, 1650, 1700],
        "aiDecision": "强烈买入", "aiConf": "高",
        "aiSum": "MACD金叉形成，DIF(12.45)站稳零轴上方，配合布林带中轨之上运行，带口向上扩展。量比1.82明显放量，多方力度占优。最近支撑1520元较扎实（当前价高于支撑+3.1%），综合技术面偏强。",
        "aiR": [
            "MACD DIF(12.45) > DEA(8.32)，金叉持续有效，柱线走强",
            "价格(1567)站布林中轨(1548)，位于带内64%，趋势健康",
            "量比1.82，放量支撑上涨，无量价背离信号",
            "RSI=58.4，尚未进入超买区域，上升空间充足",
            "均线多头排列：MA5(1552)>MA20(1548)>MA60(1490)"
        ],
        "aiE": 1555, "aiS": 1490, "aiT": 1680,
        "macdD": [2.1, 3.4, 5.2, 4.8, 7.2, 9.1, 10.3, 11.8, 12.4, 12.45],
        "deaD":  [1.2, 1.8, 2.9, 3.5, 4.8, 5.9, 7.1, 7.9, 8.2, 8.32],
        "priceD": [1510, 1522, 1498, 1515, 1530, 1545, 1552, 1558, 1562, 1567],
        "lbls": ["5/20","5/21","5/22","5/23","5/24","5/27","5/28","5/29","5/30","5/31"],
        "updatedAt": datetime.datetime.now().isoformat(),
    },
    "000001": {
        "code": "000001", "name": "平安银行", "price": 11.23, "change": -0.18,
        "decision": "观望", "rule": "观望",
        "dif": -0.12, "dea": 0.08, "hist": -0.40,
        "bbU": 11.85, "bbM": 11.45, "bbL": 11.05, "bbPct": 0.48, "bbW": 7.25,
        "rsi": 44.2, "vr": 0.72, "tr": 0.58,
        "ma5": 11.35, "ma10": 11.42, "ma20": 11.45, "ma60": 11.80,
        "sups": [11.05, 10.80, 10.50], "ress": [11.45, 11.85, 12.20],
        "aiDecision": "观望", "aiConf": "中",
        "aiSum": "MACD于零轴下方死叉，价格处于布林带中轨下方，量比0.72属缩量状态。均线呈空头排列，短期下行压力较大，建议耐心等待底部信号确认。",
        "aiR": [
            "MACD死叉且DIF(-0.12)在零轴下方，空头占优",
            "均线空头排列，MA5(11.35)<MA20(11.45)<MA60(11.80)",
            "缩量下跌，动能不足，反弹力度存疑"
        ],
        "aiE": None, "aiS": None, "aiT": None,
        "macdD": [0.5, 0.3, 0.1, -0.05, -0.08, -0.1, -0.11, -0.12, -0.12, -0.12],
        "deaD":  [0.4, 0.35, 0.28, 0.2, 0.15, 0.12, 0.10, 0.09, 0.08, 0.08],
        "priceD": [11.52, 11.48, 11.45, 11.40, 11.38, 11.32, 11.28, 11.25, 11.24, 11.23],
        "lbls": ["5/20","5/21","5/22","5/23","5/24","5/27","5/28","5/29","5/30","5/31"],
        "updatedAt": datetime.datetime.now().isoformat(),
    },
    "300750": {
        "code": "300750", "name": "宁德时代", "price": 182.50, "change": 1.86,
        "decision": "买入（信号一般）", "rule": "买入",
        "dif": 1.23, "dea": 0.85, "hist": 0.76,
        "bbU": 190, "bbM": 180, "bbL": 170, "bbPct": 0.63, "bbW": 11.0,
        "rsi": 55.3, "vr": 1.35, "tr": 2.14,
        "ma5": 180, "ma10": 178, "ma20": 180, "ma60": 175,
        "sups": [178, 175, 168], "ress": [190, 198, 210],
        "aiDecision": "买入", "aiConf": "中",
        "aiSum": "底部构筑完成，MACD金叉，量能温和放大，布林带开始上行扩口。整体技术形态偏多，建议分批介入。",
        "aiR": [
            "MACD零轴上方金叉，趋势转多",
            "量比1.35，稳健温和放量上涨",
            "布林中轨支撑有效，带口开始扩张"
        ],
        "aiE": 180, "aiS": 170, "aiT": 198,
        "macdD": [-1.2, -0.8, -0.3, 0.1, 0.4, 0.7, 0.9, 1.1, 1.2, 1.23],
        "deaD":  [-1.0, -0.9, -0.7, -0.5, -0.2, 0.1, 0.4, 0.65, 0.78, 0.85],
        "priceD": [172, 174, 176, 178, 179, 180, 181, 181.5, 182, 182.5],
        "lbls": ["5/20","5/21","5/22","5/23","5/24","5/27","5/28","5/29","5/30","5/31"],
        "updatedAt": datetime.datetime.now().isoformat(),
    },
}

# ══════════════════════════════════════════════════════════════
#  数据层
# ══════════════════════════════════════════════════════════════

# 内存存储，key = 股票代码
_stocks: dict = {}
_lock = threading.Lock()
_loading: set = set()   # 正在加载中的代码


def _init_stocks():
    """初始化：优先读 .env 配置，否则用 Demo 数据"""
    global _stocks
    if HAS_MODULES:
        try:
            cfg = Config()
            _stocks = {}
            for code in cfg.stock_codes:
                _stocks[code] = {"code": code, "name": code, "loading": True}
            # 后台线程拉取数据
            for code in list(cfg.stock_codes):
                t = threading.Thread(target=_fetch_stock, args=(code,), daemon=True)
                t.start()
            return
        except Exception as e:
            print(f"[警告] 读取 Config 失败，使用 Demo 数据: {e}")

    _stocks = dict(DEMO_STOCKS)


def _pv(row, col, default=0.0):
    """安全取 DataFrame 行的数值"""
    v = row.get(col, default)
    try:
        fv = float(v)
        return fv if fv == fv else default  # NaN check
    except (TypeError, ValueError):
        return default


def _fetch_stock(code: str) -> dict:
    """拉取单只股票数据，写入 _stocks，返回数据 dict"""
    _loading.add(code)
    try:
        df = fetch_kline(code, days=60)
        if df is None or len(df) < 20:
            raise ValueError("数据不足")

        info = fetch_stock_info(code)
        df = calc_indicators(df)
        sups, ress = find_support_resistance(df, keep=3)
        last = df.iloc[-1]
        prev = df.iloc[-2]

        price  = float(last["close"])
        change = float(last.get("change_amount", 0) or 0)

        # 支撑压力位关系
        sr_rel = describe_sr_relation(price, sups, ress)

        # 规则引擎
        rule_signal, rule_reasons = rule_engine(df, sups, ress, sr_rel)

        # AI（如已配置）
        ai_result = None
        try:
            cfg = Config()
            if cfg.enable_ai and cfg.ai_api_key:
                advisor = AIAdvisor(
                    api_key=cfg.ai_api_key,
                    base_url=cfg.ai_base_url,
                    model=cfg.ai_model,
                    temperature=cfg.ai_temperature,
                    max_tokens=cfg.ai_max_tokens,
                    timeout=cfg.ai_timeout,
                )
                prompt = build_prompt(
                    symbol=code,
                    stock_info=info,
                    df=df,
                    supports=sups,
                    resistances=ress,
                    sr_relation=sr_rel,
                )
                ai_result = advisor.query(prompt)
        except Exception as ae:
            print(f"[{code}] AI 分析跳过: {ae}")

        # 综合决策
        result = make_final_decision(
            symbol=code,
            stock_name=info.get("name", code),
            df=df,
            supports=sups,
            resistances=ress,
            sr_relation=sr_rel,
            ai_result=ai_result,
        )

        # 组装前端需要的数据格式
        stock_data = {
            "code": code,
            "name": info.get("name", code),
            "price": price,
            "change": change,
            "decision": result.final_decision,
            "rule": result.rule_signal,
            "ruleReasons": result.rule_reasons,

            # MACD
            "dif":  _pv(last, "dif"),
            "dea":  _pv(last, "dea"),
            "hist": _pv(last, "macd_hist"),

            # 布林带
            "bbU":  _pv(last, "bb_upper"),
            "bbM":  _pv(last, "bb_mid"),
            "bbL":  _pv(last, "bb_lower"),
            "bbPct": _pv(last, "bb_pct", 0.5),
            "bbW":  _pv(last, "bb_width"),

            # 其他指标
            "rsi": _pv(last, "rsi", 50),
            "vr":  _pv(last, "vol_ratio", 1),
            "tr":  _pv(last, "turnover_rate"),

            # 均线
            "ma5":  _pv(last, "ma5"),
            "ma10": _pv(last, "ma10"),
            "ma20": _pv(last, "ma20"),
            "ma60": _pv(last, "ma60"),

            # 支撑/压力
            "sups": sups or [round(price * 0.95, 2)],
            "ress": ress or [round(price * 1.05, 2)],

            # AI
            "aiDecision": result.ai_decision if result.ai_decision != "N/A" else rule_signal,
            "aiConf": result.ai_confidence if result.ai_confidence != "N/A" else "低",
            "aiSum":  result.ai_summary or "AI 未返回分析结果",
            "aiR":    result.ai_reasons or rule_reasons[1:4],
            "aiE":    result.ai_entry,
            "aiS":    result.ai_stop_loss,
            "aiTShort": result.ai_target_short,
            "aiTLong": result.ai_target_long,

            # 图表数据（最近10根）
            "macdD":  df["dif"].tail(10).fillna(0).round(4).tolist(),
            "deaD":   df["dea"].tail(10).fillna(0).round(4).tolist(),
            "priceD": df["close"].tail(10).round(2).tolist(),
            "lbls":   df["date"].tail(10).dt.strftime("%m/%d").tolist(),

            "updatedAt": datetime.datetime.now().isoformat(),
            "loading": False,
            "error": None,
        }

        with _lock:
            _stocks[code] = stock_data

        print(f"[{code}] ✓ 数据更新完成  价格={price}  决策={result.final_decision}")
        return stock_data

    except Exception as e:
        err = str(e)
        print(f"[{code}] ✗ 数据加载失败: {err}")
        with _lock:
            existing = _stocks.get(code, {})
            existing.update({"loading": False, "error": err})
            _stocks[code] = existing
        return _stocks.get(code, {})
    finally:
        _loading.discard(code)


# ══════════════════════════════════════════════════════════════
#  Flask App
# ══════════════════════════════════════════════════════════════

app = Flask(__name__, static_folder=".")


@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type"
    r.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return r


# ── 静态文件：dashboard ──────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(".", "dashboard.html")


# ── API: 全部股票列表（轻量，侧边栏用）────────────────────────
@app.route("/api/stocks")
def api_stocks():
    with _lock:
        codes = list(_stocks.keys())

    result = []
    for code in codes:
        with _lock:
            s = dict(_stocks.get(code, {}))
        # 只返回侧边栏需要的字段
        result.append({
            "code":     s.get("code", code),
            "name":     s.get("name", code),
            "price":    s.get("price", 0),
            "change":   s.get("change", 0),
            "decision": s.get("decision", "观望"),
            "rule":     s.get("rule", "观望"),
            "priceD":   s.get("priceD", []),
            "loading":  s.get("loading", False),
            "error":    s.get("error", None),
            "updatedAt": s.get("updatedAt", ""),
        })
    return jsonify({"ok": True, "stocks": result})


# ── API: 单只股票完整数据（主面板用）──────────────────────────
@app.route("/api/stock/<code>")
def api_stock(code):
    with _lock:
        s = dict(_stocks.get(code, {}))

    if not s:
        return jsonify({"ok": False, "error": f"股票 {code} 不存在"}), 404

    s.setdefault("loading", False)
    s.setdefault("error", None)
    return jsonify({"ok": True, "stock": s})


# ── API: 添加股票 ────────────────────────────────────────────
@app.route("/api/stock/add", methods=["POST", "OPTIONS"])
def api_add():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True) or {}
    code = str(data.get("code", "")).strip()
    if not code:
        return jsonify({"ok": False, "error": "缺少 code 参数"}), 400

    with _lock:
        if code in _stocks:
            return jsonify({"ok": False, "error": f"{code} 已在监控列表中"}), 400

    # 先插入 loading 占位
    with _lock:
        _stocks[code] = {"code": code, "name": code, "loading": True, "error": None}

    if HAS_MODULES:
        t = threading.Thread(target=_fetch_stock, args=(code,), daemon=True)
        t.start()
    else:
        # Demo 模式
        with _lock:
            _stocks[code] = {
                **DEMO_STOCKS.get("000001", {}),
                "code": code, "name": code,
                "loading": False, "error": None,
                "updatedAt": datetime.datetime.now().isoformat(),
            }

    return jsonify({"ok": True, "code": code, "message": "已加入监控，数据加载中…"})


# ── API: 删除股票 ────────────────────────────────────────────
@app.route("/api/stock/remove", methods=["POST", "OPTIONS"])
def api_remove():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True) or {}
    code = str(data.get("code", "")).strip()
    with _lock:
        if code not in _stocks:
            return jsonify({"ok": False, "error": "股票不存在"}), 404
        if len(_stocks) <= 1:
            return jsonify({"ok": False, "error": "至少保留一只股票"}), 400
        del _stocks[code]
    return jsonify({"ok": True})


# ── API: 刷新单只数据 ────────────────────────────────────────
@app.route("/api/stock/refresh", methods=["POST", "OPTIONS"])
def api_refresh():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True) or {}
    code = str(data.get("code", "")).strip()

    with _lock:
        if code not in _stocks:
            return jsonify({"ok": False, "error": "股票不存在"}), 404
        if code in _loading:
            return jsonify({"ok": False, "error": "正在加载中，请稍候"}), 429

    if HAS_MODULES:
        with _lock:
            _stocks[code]["loading"] = True
        t = threading.Thread(target=_fetch_stock, args=(code,), daemon=True)
        t.start()
        return jsonify({"ok": True, "message": "已开始刷新，约 5-10 秒后请求数据"})
    else:
        # Demo 模式：模拟小幅价格变动
        import random
        with _lock:
            s = _stocks.get(code, {})
            if s and "price" in s:
                s["price"] = round(s["price"] * (1 + random.uniform(-0.005, 0.005)), 2)
                s["updatedAt"] = datetime.datetime.now().isoformat()
                s["loading"] = False
        return jsonify({"ok": True, "message": "Demo 模式：价格已模拟刷新"})


# ── API: 服务状态 ────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify({
        "ok": True,
        "mode": "real" if HAS_MODULES else "demo",
        "stocks": len(_stocks),
        "loading": list(_loading),
        "time": datetime.datetime.now().isoformat(),
    })


# ══════════════════════════════════════════════════════════════
#  自动定时刷新（仅真实模式）
# ══════════════════════════════════════════════════════════════

def _auto_refresh_loop():
    if not HAS_MODULES:
        return
    try:
        cfg = Config()
        interval = cfg.interval_minutes * 60
    except Exception:
        interval = 3600

    while True:
        time.sleep(interval)
        print(f"[定时] 开始自动刷新所有股票 ({len(_stocks)} 只)...")
        with _lock:
            codes = list(_stocks.keys())
        for code in codes:
            t = threading.Thread(target=_fetch_stock, args=(code,), daemon=True)
            t.start()
            time.sleep(2)  # 错开请求，避免并发过高


# ══════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  StockMonitor · Web 仪表盘后端")
    print("=" * 55)
    print(f"  模式：{'真实数据 (akshare + AI)' if HAS_MODULES else 'Demo 演示数据'}")
    print("  地址：http://localhost:5000")
    print("  按 Ctrl+C 停止")
    print("=" * 55)

    _init_stocks()

    # 后台自动刷新线程
    t = threading.Thread(target=_auto_refresh_loop, daemon=True)
    t.start()

    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
