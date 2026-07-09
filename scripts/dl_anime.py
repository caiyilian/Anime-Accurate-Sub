"""下载 K-On! 第一集"""
import yt_dlp

url = "https://play.modujx10.com/20230909/xBgvxeNt/index.m3u8"
out = "E:/projects/Anime-Accurate-Sub/data/video/k-on_ep01.%(ext)s"

ydl = yt_dlp.YoutubeDL({"outtmpl": out, "quiet": False})
ydl.download([url])
print("Done")