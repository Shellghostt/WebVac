
import os
import re

moves = {
    "crawler": "core",
    "scraper": "core",
    "pipeline": "core",
    "browser": "utils",
    "detection": "utils",
    "proxy": "utils",
    "robots": "utils",
    "screenshot": "utils",
    "auth": "auth",
    "default_creds": "auth",
    "extractor": "extractors",
    "storage": "data",
    "config": "config",
}

def process_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # We need to replace imports
    for mod, folder in moves.items():
        # from mod import ... -> from folder.mod import ...
        content = re.sub(rf"^from {mod} import ", rf"from {folder}.{mod} import ", content, flags=re.MULTILINE)
        content = re.sub(rf"^from {mod}\.", rf"from {folder}.{mod}.", content, flags=re.MULTILINE)
        
        # import mod -> from folder import mod
        content = re.sub(rf"^import {mod}(\s|$)", rf"from {folder} import {mod}\1", content, flags=re.MULTILINE)
        
        # What if it says: import x, mod? We assume they are mostly on separate lines based on our previous grep

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

for root, dirs, files in os.walk("."):
    if "scrapy-master" in root or "venv" in root or "__pycache__" in root or ".git" in root:
        continue
    for file in files:
        if file.endswith(".py") and file != "refactor.py":
            process_file(os.path.join(root, file))

print("Imports updated!")

