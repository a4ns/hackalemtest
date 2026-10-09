#!/usr/bin/env bash
# Packs the editable project (no renders, no caches) into ../deliverables/hackalem-ai-intro-project.zip
set -euo pipefail
cd "$(dirname "$0")/.."
out="../deliverables/hackalem-ai-intro-project.zip"
mkdir -p ../deliverables
rm -f "$out"
cd ..
zip -qr "deliverables/hackalem-ai-intro-project.zip" video \
  -x "video/renders/*" "video/node_modules/*" "video/.hyperframes/*" "*/__pycache__/*" "*.pyc" "video/.gitignore" || true
echo "packed -> deliverables/hackalem-ai-intro-project.zip"
unzip -l "deliverables/hackalem-ai-intro-project.zip" | tail -1
