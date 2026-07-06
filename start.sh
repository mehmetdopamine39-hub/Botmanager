#!/bin/bash

echo "🚀 Universal Bot Hosting Başlatılıyor..."

# Python 3.11 kontrol et (varsayılan)
if ! command -v python3.11 &> /dev/null; then
    echo "⚠️ Python 3.11 bulunamadı, varsayılan Python kullanılacak"
fi

# Gereksinimleri yükle
pip install -r requirements.txt

# Uygulamayı başlat
python app.py
