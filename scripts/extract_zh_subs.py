"""提取中文字幕为纯文本参考文件"""
import pathlib, re, json

cn_dir = pathlib.Path(r"E:\projects\Anime-Accurate-Sub\data\S1")
out_dir = pathlib.Path(r"E:\projects\Anime-Accurate-Sub\data\test")

all_eps = []
for f in sorted(cn_dir.glob("*.ass")):
    ep = int(f.stem.split("EP")[1])
    content = f.read_text(encoding="utf-8")
    dialogues = []
    for line in content.split("\n"):
        line = line.strip()
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        text = re.sub(r"\{[^}]*\}", "", parts[9]).strip()
        if text:
            dialogues.append(text)

    all_eps.append({"episode": ep, "lines": dialogues})
    print(f"EP{ep:02d}: {len(dialogues)} 行")

# 输出完整 JSON
out_path = out_dir / "k-on_zh_subs.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(all_eps, f, ensure_ascii=False, indent=2)
print(f"\n输出: {out_path}")

# 输出一个预览文本
txt_path = out_dir / "k-on_zh_preview.txt"
with open(txt_path, "w", encoding="utf-8") as f:
    for ep in all_eps[:3]:
        f.write(f"=== EP{ep['episode']:02d} ===\n")
        for l in ep["lines"][:10]:
            f.write(f"  {l[:60]}\n")
        f.write("\n")
print(f"预览: {txt_path}")