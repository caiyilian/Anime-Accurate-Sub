@echo off
set HTTP_PROXY=http://127.0.0.1:7890
set HTTPS_PROXY=http://127.0.0.1:7890
start /min "" "E:\AI\Ollama\ollama.exe" serve
echo ollama serve started