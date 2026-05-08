"""
ws_test.py  ─  WebSocket 可行性验证（独立脚本，不影响主程序）
════════════════════════════════════════════════════════════════
验证 Flask-SocketIO 推送股票价格更新可行性。

安装依赖（不在主 requirements.txt 中，仅测试用）：
    pip install flask-socketio eventlet

启动：
    python ws_test.py

访问：
    http://localhost:5001/ws_test

效果：
    页面每2秒自动收到服务端推送的模拟价格更新，无需轮询。

────────────────────────────────────────────────────────────────
集成到主程序的迁移路径（待全部功能稳定后）：
  1. server.py 改为 socketio.run(app, ...)
  2. 股票数据更新后调用 socketio.emit("stock_update", data)
  3. 前端用 socket.on("stock_update", cb) 替代 setInterval 轮询
  4. 大宗商品刷新后 emit("commodity_update", data)
  5. 预警触发时 emit("alert_triggered", alert_data) 实时通知
────────────────────────────────────────────────────────────────
"""

import time
import random
import threading

try:
    from flask import Flask, render_template_string
    from flask_socketio import SocketIO, emit
except ImportError:
    print("[错误] 请先安装依赖：pip install flask-socketio eventlet")
    raise SystemExit(1)

app    = Flask(__name__)
app.config["SECRET_KEY"] = "ws_test_secret"
sio    = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── 模拟股票数据 ─────────────────────────────────────────────
MOCK_STOCKS = {
    "600519": {"name": "贵州茅台", "price": 1560.00},
    "000001": {"name": "平安银行", "price":   11.23},
    "300750": {"name": "宁德时代", "price":  182.50},
}

TEST_PAGE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>WS 推送测试</title>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
  <style>
    body { font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 30px; }
    h2   { color: #58a6ff; }
    .ticker { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
              padding: 12px 16px; margin: 8px 0; display: flex; gap: 20px; }
    .pos { color: #3fb950; } .neg { color: #f85149; }
    #log { height: 180px; overflow-y: auto; background: #0d1117;
           border: 1px solid #21262d; padding: 10px; font-size: 11px; color: #8b949e; }
  </style>
</head>
<body>
  <h2>🔌 WebSocket 实时推送测试</h2>
  <p style="color:#8b949e">绿色 = 上涨推送，红色 = 下跌推送。全程无轮询，由服务端主动推送。</p>
  <div id="stocks"></div>
  <h4>事件日志</h4>
  <div id="log"></div>

  <script>
    const socket = io();
    const prices = {};

    socket.on('connect',    () => log('✓ WebSocket 已连接  sid=' + socket.id));
    socket.on('disconnect', () => log('✗ WebSocket 已断开'));

    socket.on('stock_update', data => {
      prices[data.code] = data;
      renderStocks();
      log(`[推送] ${data.name}(${data.code}) → ${data.price}  ${data.change >= 0 ? '▲' : '▼'}${Math.abs(data.change).toFixed(2)}`);
    });

    socket.on('batch_update', list => {
      list.forEach(d => prices[d.code] = d);
      renderStocks();
    });

    function renderStocks() {
      document.getElementById('stocks').innerHTML = Object.values(prices).map(d =>
        `<div class="ticker">
          <span style="width:80px;color:#e6edf3">${d.code}</span>
          <span style="width:100px">${d.name}</span>
          <span class="${d.change>=0?'pos':'neg'}" style="width:80px">${d.price.toFixed(2)}</span>
          <span class="${d.change>=0?'pos':'neg'}">${d.change>=0?'+':''}${d.change.toFixed(2)}</span>
          <span style="color:#8b949e;font-size:10px">${d.time}</span>
        </div>`
      ).join('');
    }

    let logLines = [];
    function log(msg) {
      logLines.unshift(new Date().toTimeString().slice(0,8) + '  ' + msg);
      if (logLines.length > 30) logLines.pop();
      document.getElementById('log').innerHTML = logLines.join('<br>');
    }
  </script>
</body>
</html>
"""


@app.route("/ws_test")
def ws_test_page():
    return render_template_string(TEST_PAGE)


@sio.on("connect")
def on_connect():
    print(f"[WS] 客户端连接")
    # 连接时立即推送当前状态
    batch = []
    for code, s in MOCK_STOCKS.items():
        batch.append({
            "code": code, "name": s["name"],
            "price": s["price"], "change": 0.0,
            "time": time.strftime("%H:%M:%S"),
        })
    emit("batch_update", batch)


def _push_loop():
    """后台线程：每 2 秒随机更新一只股票并广播"""
    import random
    codes = list(MOCK_STOCKS.keys())
    while True:
        time.sleep(2)
        code  = random.choice(codes)
        stock = MOCK_STOCKS[code]
        delta = round(random.uniform(-0.5, 0.5), 2)
        stock["price"] = round(stock["price"] + delta, 2)

        sio.emit("stock_update", {
            "code":   code,
            "name":   stock["name"],
            "price":  stock["price"],
            "change": delta,
            "time":   time.strftime("%H:%M:%S"),
        })


if __name__ == "__main__":
    print("=" * 50)
    print("  WebSocket 推送可行性测试")
    print("  访问: http://localhost:5001/ws_test")
    print("=" * 50)

    t = threading.Thread(target=_push_loop, daemon=True)
    t.start()

    sio.run(app, host="0.0.0.0", port=5001, debug=False)
