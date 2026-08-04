# pipeline/env.sh — caminhos da toolchain portátil (source antes de usar o pipeline)
export BLENDER="$HOME/apps/blender/blender"   # 4.0.2 — a versão que escreveu scene.blend
# ffmpeg portátil se existir; senão o do sistema
export FFMPEG="$([ -x "$HOME/apps/ffmpeg" ] && echo "$HOME/apps/ffmpeg" || command -v ffmpeg)"
export VENV="$HOME/.venvs/tour-press"
export PY="$VENV/bin/python"
