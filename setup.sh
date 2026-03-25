#!/bin/bash

echo "--- Initializing HDD Prep Station Setup ---"

# 1. Install System Dependencies
sudo apt update
sudo apt install -y python3-pip smartmontools hdparm tmux

# 2. Install Python Dependencies
pip3 install -r requirements.txt --break-system-packages

# 3. Create Data Folders
mkdir -p certificates

# 4. Create the 'prep' Alias
if ! grep -q "alias prep=" ~/.bashrc; then
    echo "alias prep='sudo python3 $(pwd)/main.py'" >> ~/.bashrc
    echo "✔ Alias 'prep' created."
else
    echo "✔ Alias 'prep' already exists."
fi

echo "------------------------------------------------"
echo "HDD STATION READY: run 'source ~/.bashrc && prep'"
echo "------------------------------------------------"
