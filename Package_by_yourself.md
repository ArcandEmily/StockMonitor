# 🛠️ StockMonitor · 自己打包 EXE 完整指南

> 适用于 Windows 10 / 11  
> 打包后只需 `server.exe` + `.env` 两个文件，双击即可运行

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

确认目录下有这些文件再继续：

```
server.py
dashboard.html
commodity_fetcher.py
commodity_ai.py
config.py
.env
requirements.txt
...
```

---

## 第二步：创建干净的虚拟环境

> 用干净环境打包，避免把本机无关的包也打进去

```bat
:: 删除旧环境（如果有）
rmdir /s /q venv_clean

:: 查找 Python 路径
where python
```

把 `where python` 显示的路径复制出来，例如 `C:\Python314\python.exe`，然后：

```bat
:: 用完整路径创建干净虚拟环境（把下面路径换成你自己的）
C:\Python314\python.exe -m venv venv_clean

:: 激活
venv_clean\Scripts\activate
```

激活成功后命令行前缀会变成 `(venv_clean)`

---

## 第三步：安装依赖

```bat
pip install --upgrade pip

pip install ^
    akshare ^
    pandas ^
    numpy ^
    scipy ^
    openai ^
    loguru ^
    python-dotenv ^
    flask ^
    requests ^
    pyinstaller
```

> ⏱️ 首次安装约需 3~8 分钟，akshare 体积较大

安装完成后验证：

```bat
pip list | findstr /i "akshare flask pyinstaller"
```

能看到三行版本信息即为成功。

---

## 第四步：准备 .env 文件

确认项目根目录有 `.env` 文件，内容示例：

```env
DEEPSEEK_API_KEY=sk-你的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
ENABLE_AI=True
AI_MAX_TOKENS=2000
AI_TEMPERATURE=0.2
STOCK_CODES=000001,600519,300750
KLINE_DAYS=250
INTERVAL_MINUTES=60
```

---

## 第五步：执行打包

```bat
pyinstaller --onefile --console --clean ^
    --collect-data akshare ^
    --add-data "dashboard.html;." ^
    --add-data "commodity_fetcher.py;." ^
    --add-data "commodity_ai.py;." ^
    --add-data ".env;." ^
    --hidden-import akshare ^
    --hidden-import loguru ^
    --hidden-import flask ^
    --hidden-import requests ^
    --hidden-import openai ^
    --hidden-import dotenv ^
    server.py
```

**参数说明：**

| 参数 | 作用 |
|------|------|
| `--onefile` | 打包成单个 exe |
| `--console` | 保留命令行窗口（方便看日志） |
| `--clean` | 每次打包前清理缓存 |
| `--collect-data akshare` | 把 akshare 的数据文件一起打包（必须） |
| `--add-data "xxx;."` | 把附加文件打包进 exe 内部 |
| `--hidden-import xxx` | 强制包含被动态导入的模块 |

> ⏱️ 打包过程约 3~10 分钟，正常现象，耐心等待

---

## 第六步：找到 exe

打包成功后在 `dist` 目录下：

```
StockMonitor\
└── dist\
    └── server.exe   ← 这就是打包好的文件
```

---

## 第七步：运行

只需两个文件放在同一目录：

```
📁 任意目录\
├── server.exe   ← 打包好的主程序（所有代码和资源已内置）
└── .env         ← 配置文件（含 API Key，可随时修改）
```

双击 `server.exe`，看到以下输出即为成功：

```
===================================================
  StockMonitor · Web 仪表盘后端
===================================================
  模式：真实数据 (akshare + AI)
  地址：http://localhost:5000
  按 Ctrl+C 停止
===================================================
```

打开浏览器访问：**http://localhost:5000**

> 💡 `.env` 是唯一需要保留在外部的文件，方便随时修改股票代码和 API Key，  
> 修改后重启 exe 即可生效，**无需重新打包**

---

## 常见报错 & 解决方法

### ❌ `ModuleNotFoundError: No module named 'akshare'`

```bat
:: 把 --collect-data 换成 --collect-all
--collect-all akshare
```

### ❌ exe 打开一闪而过

原因：程序报错后窗口立刻关闭，用命令行运行查看完整报错：

```bat
cd 你的exe所在目录
server.exe
```

### ❌ 端口 5000 已被占用

```bat
:: 查找占用进程
netstat -ano | findstr :5000

:: 结束对应进程（替换为实际 PID）
taskkill /PID 12345 /F
```

### ❌ `WARNING: Hidden import not found`

警告不是错误，忽略即可，不影响运行。

---

## 更新流程

修改代码后重新打包，然后只替换 exe：

```bat
cd C:\你的项目路径\StockMonitor
venv_clean\Scripts\activate

pyinstaller --onefile --console --clean ^
    --collect-data akshare ^
    --add-data "dashboard.html;." ^
    --add-data "commodity_fetcher.py;." ^
    --add-data "commodity_ai.py;." ^
    --add-data ".env;." ^
    --hidden-import akshare ^
    --hidden-import loguru ^
    --hidden-import flask ^
    --hidden-import requests ^
    --hidden-import openai ^
    --hidden-import dotenv ^
    server.py

:: 替换旧 exe（.env 不需要动）
copy /y dist\server.exe 你的发布目录\server.exe
```

---

## 文件大小参考

| 情况 | 大小 |
|------|------|
| 正常范围 | 80 ~ 150 MB |
| akshare 数据文件贡献 | ~60 MB |
| 超过 200 MB | 检查是否混入了不必要的包 |

---

## 已验证的依赖版本（参考）

```
akshare          1.18.60
Flask            3.1.3
numpy            2.4.4
openai           2.34.0
pandas           3.0.2
pyinstaller      6.20.0
python-dotenv    1.2.2
requests         2.33.1
scipy            1.17.1
loguru           0.7.3
```
