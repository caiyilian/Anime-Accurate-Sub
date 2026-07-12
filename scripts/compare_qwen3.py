"""
S4.2: Qwen3-ASR-1.7B-JA vs Anime Whisper comparison report
"""
import json
from pathlib import Path

OUT_DIR = Path("docs/evaluation")

# Load results
with open(OUT_DIR / "S3.2_results_int8f16_b8_novad.json", encoding="utf-8") as f:
    aw_data = json.load(f)

with open(OUT_DIR / "S4.2_results_qwen3.json", encoding="utf-8") as f:
    qw_data = json.load(f)

aw_samples = {r["sample"]: r for r in aw_data.get("results", [])}
qw_samples = {r["sample"]: r for r in qw_data.get("results", [])}

# Proper nouns in the test set
proper_nouns = [
    "隼斗", "杏璃", "杏鈴", "珠樹", "義宗", "紫苑",
    "信行", "徳田", "神泉", "桃太郎", "アンゴルモア", "江都"
]

print("=== Proper noun recognition comparison ===\n")
count = 0
for sample_name in sorted(aw_samples.keys()):
    if sample_name not in qw_samples:
        continue
    ref = aw_samples[sample_name]["reference"]
    found = [n for n in proper_nouns if n in ref]
    if not found:
        continue

    aw_text = aw_samples[sample_name]["transcription"]
    qw_text = qw_samples[sample_name]["transcription"]

    # Check which model correctly recognized the noun
    aw_correct = sum(1 for n in found if n in aw_text)
    qw_correct = sum(1 for n in found if n in qw_text)

    print(f"{sample_name}:")
    print(f"  Ref: {ref}")
    print(f"  AW:  {aw_text}")
    print(f"  Q3:  {qw_text}")
    print(f"  Nouns: {found} -> AW={aw_correct}/{len(found)}, Q3={qw_correct}/{len(found)}")
    print()
    count += 1
    if count >= 15:
        break

# Summary table
print("\n=== Overall comparison ===")
print(f"{'Model':<35} {'Avg CER':<10} {'Med CER':<10} {'RTF':<8}")
print("-" * 63)
for name, data in [("Anime Whisper (S3.2 best)", aw_data), ("Qwen3-ASR-1.7B", qw_data)]:
    print(f"{name:<35} {data['avg_cer']:<10.4f} {data['median_cer']:<10.4f} {data['rtf']:<8.4f}")