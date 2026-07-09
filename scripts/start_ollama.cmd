@echo off
chcp 65001 >nul
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890
echo 启动 Ollama 服务（带代理）
echo HTTP_PROXY=%HTTP_PROXY%
echo HTTPS_PROXY=%HTTPS_PROXY%
echo.
start /min "" "E:\AI\Ollama\ollama.exe" serve
echo Ollama 服务已启动
echo.
echo 然后在另一个 CMD 窗口运行 pull 命令:
echo ollama pull EasonONLINE/Sakura-qwen2.5-v1.0:7b
echo.
echo 注意: pull 命令的 CMD 窗口不要设 HTTP_PROXY，否则客户端会走代理连本地服务器
echo 只需要服务端设代理即可
pause