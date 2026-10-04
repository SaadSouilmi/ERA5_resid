#!/bin/bash
set -e

echo "Updating package lists..."
sudo apt update

echo "Installing LaTeX and tools..."
sudo apt install -y \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-bibtex-extra \
    biber \
    latexmk \
    git-lfs

echo "Configuring Git LFS..."
git lfs install
# git lfs uninstall

echo "Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh

# Ensure uv is added to the shell profile for future terminal sessions
echo 'export PATH="$HOME/.local/bin:$PATH""' >> ~/.bashrc