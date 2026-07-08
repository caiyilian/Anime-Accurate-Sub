# Network Proxy Skill

本项目的开发环境需要通过代理访问外部网络（GitHub、HuggingFace、PyPI 等）。
代理地址：`http://127.0.0.1:7890`

**每次执行涉及网络的命令前，必须先设置代理环境变量。**

---

## 快速命令

### PowerShell 设置代理
```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"; $env:HTTPS_PROXY="http://127.0.0.1:7890"
```

### Git 配置代理（已持久化）
```powershell
git config http.proxy http://127.0.0.1:7890
git config https.proxy http://127.0.0.1:7890
```

### 取消 Git 代理（直连 GitHub）
```powershell
git config --unset http.proxy
git config --unset https.proxy
```

---

## 涉及网络的命令

| 场景 | 命令 | 是否需要代理 |
|------|------|------------|
| git push/clone | `git push` | 需要（已配持久化） |
| pip/uv 安装包 | `uv pip install` | 需要 |
| HuggingFace 下载模型 | huggingface_hub | 需要 |
| Ollama pull 模型 | `ollama pull` | 需要 |
| gh CLI | `gh pr create` 等 | 需要 |
| 直连 GitHub | 无代理 | 不需要（某些场景更快） |

---

## 常用组合命令

### 一次性设置代理并执行
```powershell
$env:HTTP_PROXY="http://127.0.0.1:7890"; $env:HTTPS_PROXY="http://127.0.0.1:7890"; <your_command>
```

### 临时取消 Git 代理再恢复
```powershell
git config --unset http.proxy; git config --unset https.proxy
# 执行直连操作...
git config http.proxy http://127.0.0.1:7890; git config https.proxy http://127.0.0.1:7890
```