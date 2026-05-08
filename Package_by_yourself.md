# 🛠️ StockMonitor · 自己打包 EXE 完整指南

> 适用于 Windows 10 / 11  
> 打包后只需 **`server.exe` + `config.yaml`** 两个文件，双击即可运行

---

## 前置要求

| 工具 | 要求 | 检查命令 |
|------|------|----------|
| Python | 3.10 及以上（含 3.14） | `python --version` |
| Git | 任意版本 | `git --version` |
| 磁盘空间 | 打包目录至少 2 GB | — |

> ⚠️ Python 安装时必须勾选 **"Add to PATH"**，否则命令行找不到

---

## 第一步：进入项目目录

```bat
cd C:\你的项目路径\StockMonitor
```

确认以下文件存在再继续：

```
server.py
dashboard.html
config.yaml
commodity_fetcher.py  commodity_ai.py
sector_fetcher.py     capital_fetcher.py    calendar_fetcher.py
requirements.txt
```

---

## 第二步：创建干净的虚拟环境

> 干净环境打包，避免把本机无关的包打进去，减小体积

```bat
:: 删除旧环境（如果有）
rmdir /s /q venv_clean

:: 查找 Python 路径
where python
```

把 `where python` 输出的路径复制出来，替换下面的示例路径：

```bat
C:\Python314\python.exe -m venv venv_clean
venv_clean\Scripts\activate
```

激活成功后，命令行前缀变为 `(venv_clean)`

---

## 第三步：安装依赖

```bat
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
```

> ⏱️ 首次安装约需 3~8 分钟，akshare 体积较大

验证安装：

```bat
pip list | findstr /i "akshare flask pyinstaller pyyaml"
```

看到四行版本信息即正常。

---

## 第四步：确认 config.yaml 已填写

打开 `config.yaml`，把 API Key 填进去：

```yaml
ai:
  api_key: "sk-你的真实密钥"    ← 填这里，其余保持默认即可
```

---

## 第五步：执行打包

```bat
pyinstaller --onefile --console --clean ^
    --collect-data akshare ^
    --add-data "dashboard.html;." ^
    --add-data "commodity_fetcher.py;." ^
    --add-data "commodity_ai.py;." ^
    --add-data "sector_fetcher.py;." ^
    --add-data "capital_fetcher.py;." ^
    --add-data "calendar_fetcher.py;." ^
    --hidden-import akshare ^
    --hidden-import loguru ^
    --hidden-import flask ^
    --hidden-import requests ^
    --hidden-import openai ^
    --hidden-import yaml ^
    server.py
```

**参数说明：**

| 参数 | 作用 |
|------|------|
| `--onefile` | 打包成单个 exe |
| `--console` | 保留命令行窗口（方便看日志） |
| `--clean` | 每次打包前清理缓存 |
| `--collect-data akshare` | 打包 akshare 的数据文件（必须，否则运行报错） |
| `--add-data "xxx;."` | 把附加文件打包进 exe 内部，`;.` 表示放在根目录 |
| `--hidden-import xxx` | 强制包含被动态导入的模块 |

> ⏱️ 打包约 3~10 分钟，正常现象，耐心等待  
> ⚠️ `ws_test.py` **不需要**打包进去，它是独立验证脚本

---

## 第六步：取出并运行

打包成功后，在 `dist\` 目录找到 `server.exe`。

**只需两个文件放在同一目录：**

```
📁 任意目录\
├── server.exe     ← 打包好的主程序（含所有代码和资源）
└── config.yaml    ← 配置文件（API Key、股票代码、刷新间隔等）
```

双击 `server.exe`，看到以下输出即为成功：

```
=====================================================
  StockMonitor · Web 仪表盘后端
=====================================================
  模式：真实数据 (akshare + AI)
  地址：http://localhost:5000
  按 Ctrl+C 停止
```

打开浏览器访问 **http://localhost:5000**

> 💡 修改 `config.yaml`（股票代码、API Key、刷新间隔等）后，**重启 exe 即可生效，无需重新打包**

---

## config.yaml 常用配置

```yaml
ai:
  api_key: "sk-你的密钥"          # DeepSeek API Key（必填）
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  enabled: true
  max_tokens: 2000
  temperature: 0.2
  timeout: 60
  thinking:
    enabled: false               # 思考模式（更准但更贵，默认关闭）
    effort: "high"               # high 或 max

stocks:
  codes:
    - "000001"
    - "600519"
    - "300750"
  kline_days: 250
  interval_minutes: 60           # 自动刷新间隔（分钟）

alerts:
  enable_sound: false
```

**切换到 GPT-4o：**
```yaml
ai:
  api_key: "sk-你的OpenAI密钥"
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
```

**切换到本地 Ollama（免费，需先安装 Ollama）：**
```yaml
ai:
  api_key: "ollama"
  base_url: "http://localhost:11434/v1"
  model: "qwen2.5:7b"
```

---

## 常见报错 & 解决方法

### ❌ `ModuleNotFoundError: No module named 'yaml'`

打包命令已包含 `--hidden-import yaml`，若仍报错，在虚拟环境里补装：
```bat
pip install pyyaml
```
然后重新打包。

### ❌ `ModuleNotFoundError: No module named 'akshare'`

akshare 有额外数据文件，把 `--collect-data akshare` 换成更彻底的：
```bat
--collect-all akshare
```

### ❌ exe 打开一闪而过

程序内部报错但窗口关闭太快，改用命令行运行查看完整错误：
```bat
cd 你的exe目录
server.exe
```

### ❌ 端口 5000 已被占用

```bat
netstat -ano | findstr :5000
taskkill /PID 替换为实际PID /F
```

### ❌ 板块联动 / 北向资金 显示"暂不可用"

这两个功能依赖 akshare 调用 A 股交易所接口，**非交易时段（收盘后/周末）会返回空数据**，属正常现象，交易时间内可正常显示。

### ❌ `WARNING: Hidden import not found`

警告不是错误，忽略即可，不影响运行。

---

## 更新流程

代码有修改时，重新打包后只替换 exe，**config.yaml 不需要动**：

```bat
cd C:\你的项目路径\StockMonitor
venv_clean\Scripts\activate

pyinstaller --onefile --console --clean ^
    --collect-data akshare ^
    --add-data "dashboard.html;." ^
    --add-data "commodity_fetcher.py;." ^
    --add-data "commodity_ai.py;." ^
    --add-data "sector_fetcher.py;." ^
    --add-data "capital_fetcher.py;." ^
    --add-data "calendar_fetcher.py;." ^
    --hidden-import akshare ^
    --hidden-import loguru ^
    --hidden-import flask ^
    --hidden-import requests ^
    --hidden-import openai ^
    --hidden-import yaml ^
    server.py

:: 替换发布目录里的旧 exe
copy /y dist\server.exe 你的发布目录\server.exe
```

---

## 文件大小参考

| 情况 | 大小 |
|------|------|
| 正常范围 | 80 ~ 150 MB |
| akshare 数据文件贡献 | ~60 MB |
| 超过 200 MB | 检查是否混入了无关包 |

---

## 已验证依赖版本

```
akshare          1.18.60
Flask            3.1.3
numpy            2.4.4
openai           2.34.0
pandas           3.0.2
pyinstaller      6.20.0
pyyaml           6.0.3
requests         2.33.1
scipy            1.17.1
loguru           0.7.3
openpyxl         3.1.5
```
