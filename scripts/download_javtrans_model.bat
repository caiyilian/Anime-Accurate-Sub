@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set HF_ENDPOINT=https://hf-mirror.com
set http_proxy=
set https_proxy=

echo ========================================
echo Download JAVTrans Qwen3-ASR models
echo Mirror: hf-mirror.com
echo ========================================
echo.

echo [1/2] Download 1.7B model (~3.8GB) ...
echo.
python scripts\download_model.py jaykwok/Qwen3-ASR-1.7B-JA-Anime-Galgame-hf "E:\projects\Anime-Accurate-Sub\packages\reference-projects\Sprint-2\JAVTrans\models\jaykwok-Qwen3-ASR-1.7B-JA-Anime-Galgame-hf"
if %ERRORLEVEL% neq 0 (
    echo [FAILED] 1.7B download error code: %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)
echo [OK] 1.7B model done
echo.

echo [2/2] Download 0.6B model (~1.5GB, optional) ...
echo Skip this if you have 8GB+ VRAM (press Ctrl+C to skip)
echo.
python scripts\download_model.py jaykwok/Qwen3-ASR-0.6B-JA-Anime-Galgame-hf "E:\projects\Anime-Accurate-Sub\packages\reference-projects\Sprint-2\JAVTrans\models\jaykwok-Qwen3-ASR-0.6B-JA-Anime-Galgame-hf"
if %ERRORLEVEL% neq 0 (
    echo [FAILED] 0.6B download error code: %ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)
echo [OK] 0.6B model done
echo.

echo ========================================
echo All done!
echo ========================================
pause