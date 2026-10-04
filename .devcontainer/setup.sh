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