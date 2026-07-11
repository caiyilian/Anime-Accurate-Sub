import os
import sys

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

repo_id = sys.argv[1]
local_dir = sys.argv[2]

from huggingface_hub import snapshot_download

print(f"Downloading {repo_id} to {local_dir} ...")
snapshot_download(
    repo_id=repo_id,
    local_dir=local_dir,
    local_dir_use_symlinks=False,
    resume_download=True,
)
print("Download complete")