#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import subprocess
import threading
import signal
import shutil
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_file
import psutil

# ============ KONFİGÜRASYON ============
PORT = int(os.environ.get('PORT', 5000))
BOTS_DIR = "bots"
VERSIONS_DIR = "python_versions"
ALLOWED_VERSIONS = ["3.8", "3.9", "3.10", "3.11", "3.12"]

# ============ LOG AYARLARI ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_manager.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============ FLASK UYGULAMASI ============
app = Flask(__name__)
app.secret_key = os.urandom(24)

# ============ BOT YÖNETİCİ ============
class UniversalBotManager:
    def __init__(self):
        self.bots = {}
        self.processes = {}
        self.python_versions = self.detect_python_versions()
        self.init_directories()
        self.load_bots()
        self.start_auto_restart_thread()
        logger.info(f"✅ Bot Manager başlatıldı. Python sürümleri: {self.python_versions}")
    
    def detect_python_versions(self):
        """Sistemdeki Python sürümlerini tespit et"""
        versions = {}
        
        # Önce sistemdeki Python sürümlerini kontrol et
        for ver in ALLOWED_VERSIONS:
            # Python sürümünü dene
            python_cmd = f"python{ver}"
            try:
                result = subprocess.run(
                    [python_cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    versions[ver] = {
                        "path": python_cmd,
                        "version": result.stdout.strip(),
                        "available": True
                    }
                    logger.info(f"✅ Python {ver} bulundu: {python_cmd}")
            except:
                # pyenv veya conda ile dene
                try:
                    result = subprocess.run(
                        ["pyenv", "which", f"python{ver}"],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        versions[ver] = {
                            "path": result.stdout.strip(),
                            "version": f"Python {ver}",
                            "available": True
                        }
                        logger.info(f"✅ Python {ver} pyenv'de bulundu")
                except:
                    pass
        
        # Hiçbir sürüm bulunamazsa varsayılanı kullan
        if not versions:
            logger.warning("⚠️ Hiç Python sürümü bulunamadı, varsayılan kullanılıyor")
            versions["3.11"] = {
                "path": "python3",
                "version": "Python 3.11 (default)",
                "available": True
            }
        
        return versions
    
    def init_directories(self):
        """Gerekli dizinleri oluştur"""
        for dir_name in [BOTS_DIR, VERSIONS_DIR]:
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
                logger.info(f"📁 Dizin oluşturuldu: {dir_name}")
    
    def load_bots(self):
        """Kayıtlı botları yükle"""
        bots_file = "bots_data.json"
        if os.path.exists(bots_file):
            try:
                with open(bots_file, 'r') as f:
                    self.bots = json.load(f)
                logger.info(f"📂 {len(self.bots)} bot yüklendi")
                # Botları başlat
                for bot_name, bot_data in self.bots.items():
                    if bot_data.get("auto_start", True):
                        self.start_bot(bot_name)
            except Exception as e:
                logger.error(f"Botlar yüklenemedi: {e}")
                self.bots = {}
    
    def save_bots(self):
        """Bot verilerini kaydet"""
        bots_file = "bots_data.json"
        try:
            with open(bots_file, 'w') as f:
                json.dump(self.bots, f, indent=4)
            logger.info("💾 Bot verileri kaydedildi")
        except Exception as e:
            logger.error(f"Bot verileri kaydedilemedi: {e}")
    
    def get_python_path(self, version):
        """Python sürümüne göre yolu getir"""
        if version in self.python_versions:
            return self.python_versions[version]["path"]
        # Varsayılan olarak ilk bulunanı kullan
        if self.python_versions:
            return list(self.python_versions.values())[0]["path"]
        return "python3"
    
    def create_venv(self, bot_name, python_version="3.11"):
        """Bot için sanal ortam oluştur"""
        bot_path = os.path.join(BOTS_DIR, bot_name)
        venv_path = os.path.join(bot_path, "venv")
        
        if os.path.exists(venv_path):
            return venv_path
        
        python_path = self.get_python_path(python_version)
        
        try:
            # Sanal ortam oluştur
            subprocess.run(
                [python_path, "-m", "venv", venv_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            logger.info(f"✅ Sanal ortam oluşturuldu: {bot_name} (Python {python_version})")
            
            # Sanal ortam bilgisini kaydet
            if bot_name in self.bots:
                self.bots[bot_name]["python_version"] = python_version
                self.bots[bot_name]["venv_path"] = venv_path
                self.save_bots()
            
            return venv_path
        except Exception as e:
            logger.error(f"❌ Sanal ortam oluşturulamadı: {e}")
            return None
    
    def install_packages(self, bot_name, packages):
        """Bot için paket yükle"""
        bot_path = os.path.join(BOTS_DIR, bot_name)
        venv_path = os.path.join(bot_path, "venv")
        
        if not os.path.exists(venv_path):
            self.create_venv(bot_name)
        
        # Python yürütücü yolu
        if os.name == 'nt':  # Windows
            python_exe = os.path.join(venv_path, "Scripts", "python.exe")
            pip_exe = os.path.join(venv_path, "Scripts", "pip.exe")
        else:  # Linux/Mac
            python_exe = os.path.join(venv_path, "bin", "python")
            pip_exe = os.path.join(venv_path, "bin", "pip")
        
        # Pip'i güncelle
        try:
            subprocess.run([pip_exe, "install", "--upgrade", "pip"], 
                         check=True, capture_output=True, timeout=30)
        except:
            pass
        
        # Paketleri yükle
        installed = []
        failed = []
        for package in packages:
            try:
                result = subprocess.run(
                    [pip_exe, "install", package],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                installed.append(package)
                logger.info(f"📦 Paket yüklendi: {package} -> {bot_name}")
            except Exception as e:
                failed.append(package)
                logger.error(f"❌ Paket yüklenemedi: {package} -> {e}")
        
        return installed, failed
    
    def start_bot(self, bot_name):
        """Bot'u başlat"""
        if bot_name not in self.bots:
            logger.error(f"❌ Bot bulunamadı: {bot_name}")
            return False
        
        bot_data = self.bots[bot_name]
        bot_path = os.path.join(BOTS_DIR, bot_name)
        bot_file = bot_data.get("bot_file", "bot.py")
        
        # Python sürümünü al
        python_version = bot_data.get("python_version", "3.11")
        venv_path = os.path.join(bot_path, "venv")
        
        # Sanal ortam yoksa oluştur
        if not os.path.exists(venv_path):
            self.create_venv(bot_name, python_version)
        
        # Python yürütücü yolu
        if os.name == 'nt':
            python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            python_exe = os.path.join(venv_path, "bin", "python")
        
        bot_script = os.path.join(bot_path, bot_file)
        
        if not os.path.exists(bot_script):
            logger.error(f"❌ Bot dosyası bulunamadı: {bot_script}")
            return False
        
        try:
            # Bot'u arka planda başlat
            log_file = open(os.path.join(bot_path, "bot.log"), "a")
            
            process = subprocess.Popen(
                [python_exe, bot_script],
                cwd=bot_path,
                stdout=log_file,
                stderr=log_file,
                stdin=subprocess.DEVNULL,
                start_new_session=True
            )
            
            self.processes[bot_name] = process
            bot_data["status"] = "running"
            bot_data["pid"] = process.pid
            bot_data["start_time"] = datetime.now().isoformat()
            bot_data["python_version"] = python_version
            self.save_bots()
            
            logger.info(f"✅ Bot başlatıldı: {bot_name} (PID: {process.pid}, Python: {python_version})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Bot başlatılamadı: {e}")
            bot_data["status"] = "error"
            self.save_bots()
            return False
    
    def stop_bot(self, bot_name):
        """Bot'u durdur"""
        if bot_name in self.processes:
            process = self.processes[bot_name]
            try:
                # Graceful shutdown
                process.terminate()
                time.sleep(2)
                if process.poll() is None:
                    process.kill()
                
                del self.processes[bot_name]
                self.bots[bot_name]["status"] = "stopped"
                self.bots[bot_name]["pid"] = None
                self.save_bots()
                logger.info(f"⏹ Bot durduruldu: {bot_name}")
                return True
            except Exception as e:
                logger.error(f"❌ Bot durdurulamadı: {e}")
                return False
        return False
    
    def restart_bot(self, bot_name):
        """Bot'u yeniden başlat"""
        if self.stop_bot(bot_name):
            time.sleep(2)
            return self.start_bot(bot_name)
        return False
    
    def delete_bot(self, bot_name):
        """Bot'u sil"""
        self.stop_bot(bot_name)
        bot_path = os.path.join(BOTS_DIR, bot_name)
        try:
            shutil.rmtree(bot_path)
            if bot_name in self.bots:
                del self.bots[bot_name]
                self.save_bots()
            logger.info(f"🗑 Bot silindi: {bot_name}")
            return True
        except Exception as e:
            logger.error(f"❌ Bot silinemedi: {e}")
            return False
    
    def create_bot(self, bot_name, bot_code, python_version="3.11", requirements=None):
        """Yeni bot oluştur"""
        if bot_name in self.bots:
            return False, "Bot zaten var"
        
        bot_path = os.path.join(BOTS_DIR, bot_name)
        try:
            os.makedirs(bot_path)
            
            # Bot dosyasını oluştur
            with open(os.path.join(bot_path, "bot.py"), 'w') as f:
                f.write(bot_code)
            
            # Sanal ortam oluştur
            venv_path = self.create_venv(bot_name, python_version)
            
            # Gereksinimleri yükle
            if requirements:
                self.install_packages(bot_name, requirements)
            
            # Bot'u kaydet
            self.bots[bot_name] = {
                "status": "stopped",
                "pid": None,
                "python_version": python_version,
                "venv_path": venv_path,
                "bot_file": "bot.py",
                "auto_start": True,
                "created_at": datetime.now().isoformat()
            }
            self.save_bots()
            
            logger.info(f"✅ Yeni bot oluşturuldu: {bot_name} (Python {python_version})")
            return True, "Bot oluşturuldu"
            
        except Exception as e:
            logger.error(f"❌ Bot oluşturulamadı: {e}")
            return False, str(e)
    
    def get_bot_logs(self, bot_name, lines=100):
        """Bot loglarını getir"""
        bot_path = os.path.join(BOTS_DIR, bot_name)
        log_file = os.path.join(bot_path, "bot.log")
        
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    logs = f.readlines()
                    return logs[-lines:] if logs else ["Log boş"]
            except:
                return ["Log okunamadı"]
        return ["Log dosyası bulunamadı"]
    
    def get_bot_status(self, bot_name):
        """Bot durumunu getir"""
        if bot_name in self.processes:
            process = self.processes[bot_name]
            if process.poll() is None:
                return "running"
            else:
                return "crashed"
        return self.bots.get(bot_name, {}).get("status", "unknown")
    
    def auto_restart_loop(self):
        """Otomatik yeniden başlatma döngüsü"""
        while True:
            try:
                for bot_name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        logger.warning(f"⚠️ Bot çöktü, yeniden başlatılıyor: {bot_name}")
                        self.restart_bot(bot_name)
                time.sleep(30)
            except Exception as e:
                logger.error(f"❌ Otomatik yeniden başlatma hatası: {e}")
                time.sleep(10)
    
    def start_auto_restart_thread(self):
        """Otomatik yeniden başlatma thread'ini başlat"""
        thread = threading.Thread(target=self.auto_restart_loop, daemon=True)
        thread.start()

# ============ FLASK ROUTES ============
manager = UniversalBotManager()

@app.route('/')
def index():
    """Ana sayfa - Tek dosya arayüz"""
    return render_template('index.html', 
                         bots=manager.bots,
                         versions=ALLOWED_VERSIONS,
                         python_versions=manager.python_versions)

@app.route('/api/bots', methods=['GET'])
def get_bots():
    """Bot listesini getir"""
    return jsonify(manager.bots)

@app.route('/api/bot/start', methods=['POST'])
def api_start_bot():
    """Bot başlat"""
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success = manager.start_bot(bot_name)
    return jsonify({"success": success})

@app.route('/api/bot/stop', methods=['POST'])
def api_stop_bot():
    """Bot durdur"""
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success = manager.stop_bot(bot_name)
    return jsonify({"success": success})

@app.route('/api/bot/restart', methods=['POST'])
def api_restart_bot():
    """Bot yeniden başlat"""
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success = manager.restart_bot(bot_name)
    return jsonify({"success": success})

@app.route('/api/bot/delete', methods=['POST'])
def api_delete_bot():
    """Bot sil"""
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success = manager.delete_bot(bot_name)
    return jsonify({"success": success})

@app.route('/api/bot/create', methods=['POST'])
def api_create_bot():
    """Yeni bot oluştur"""
    data = request.json
    bot_name = data.get('bot_name')
    bot_code = data.get('bot_code', '')
    python_version = data.get('python_version', '3.11')
    requirements = data.get('requirements', [])
    
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success, message = manager.create_bot(bot_name, bot_code, python_version, requirements)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/install', methods=['POST'])
def api_install_packages():
    """Paket yükle"""
    data = request.json
    bot_name = data.get('bot_name')
    packages = data.get('packages', [])
    
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    if not packages:
        return jsonify({"error": "Paket listesi gerekli"}), 400
    
    installed, failed = manager.install_packages(bot_name, packages)
    return jsonify({
        "success": len(failed) == 0,
        "installed": installed,
        "failed": failed
    })

@app.route('/api/bot/logs', methods=['GET'])
def api_get_logs():
    """Bot loglarını getir"""
    bot_name = request.args.get('bot_name')
    lines = int(request.args.get('lines', 100))
    
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    logs = manager.get_bot_logs(bot_name, lines)
    return jsonify({"logs": logs})

@app.route('/api/bot/status', methods=['GET'])
def api_get_status():
    """Bot durumunu getir"""
    bot_name = request.args.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    status = manager.get_bot_status(bot_name)
    return jsonify({"status": status})

@app.route('/api/versions', methods=['GET'])
def api_get_versions():
    """Python sürümlerini getir"""
    return jsonify(manager.python_versions)

# ============ TEMPLATE ============
import jinja2

TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Universal Bot Hosting Manager</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        .header h1 {
            color: #333;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .header .subtitle {
            color: #666;
            font-size: 1.1em;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .card {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
            transition: transform 0.3s ease;
        }
        .card:hover {
            transform: translateY(-5px);
        }
        .card-title {
            font-size: 1.3em;
            font-weight: bold;
            color: #333;
            margin-bottom: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .status-badge {
            display: inline-block;
            padding: 5px 15px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: bold;
        }
        .status-running { background: #4CAF50; color: white; }
        .status-stopped { background: #f44336; color: white; }
        .status-crashed { background: #ff9800; color: white; }
        .status-unknown { background: #9e9e9e; color: white; }
        .bot-info {
            color: #666;
            font-size: 0.9em;
            margin: 10px 0;
        }
        .btn-group {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin: 15px 0;
        }
        .btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9em;
            font-weight: 500;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }
        .btn:hover {
            transform: scale(1.05);
            box-shadow: 0 3px 10px rgba(0,0,0,0.2);
        }
        .btn-start { background: #4CAF50; color: white; }
        .btn-stop { background: #f44336; color: white; }
        .btn-restart { background: #ff9800; color: white; }
        .btn-delete { background: #9c27b0; color: white; }
        .btn-create { background: #2196F3; color: white; }
        .btn-install { background: #009688; color: white; }
        .btn-log { background: #607d8b; color: white; }
        .panel {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }
        .panel h2 {
            color: #333;
            margin-bottom: 20px;
            font-size: 1.8em;
        }
        .form-group {
            margin-bottom: 15px;
        }
        .form-group label {
            display: block;
            color: #333;
            font-weight: 500;
            margin-bottom: 5px;
        }
        .form-control {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
            transition: border-color 0.3s ease;
        }
        .form-control:focus {
            border-color: #667eea;
            outline: none;
        }
        textarea.form-control {
            min-height: 200px;
            font-family: 'Courier New', monospace;
        }
        .log-container {
            background: #1e1e1e;
            color: #d4d4d4;
            padding: 15px;
            border-radius: 8px;
            max-height: 300px;
            overflow-y: auto;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
            white-space: pre-wrap;
        }
        .flex-row {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }
        .flex-row > * {
            flex: 1;
            min-width: 200px;
        }
        .badge {
            display: inline-block;
            padding: 3px 10px;
            background: #e0e0e0;
            border-radius: 12px;
            font-size: 0.8em;
            color: #333;
        }
        @media (max-width: 768px) {
            .grid {
                grid-template-columns: 1fr;
            }
            .header h1 {
                font-size: 1.8em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🤖 Universal Bot Hosting Manager</h1>
            <div class="subtitle">
                Tüm Python Sürümleriyle Uyumlu | 7/24 Aktif | Otomatik Yeniden Başlatma
            </div>
            <div style="margin-top: 10px;">
                <span class="badge">🐍 Python Versiyonları: {{ python_versions|join(', ') }}</span>
                <span class="badge">📦 Toplam Bot: {{ bots|length }}</span>
            </div>
        </div>

        <!-- Yeni Bot Oluştur -->
        <div class="panel">
            <h2>📦 Yeni Bot Oluştur</h2>
            <form id="createBotForm">
                <div class="flex-row">
                    <div class="form-group">
                        <label>Bot Adı</label>
                        <input type="text" id="botName" class="form-control" placeholder="örnek: my_bot" required>
                    </div>
                    <div class="form-group">
                        <label>Python Sürümü</label>
                        <select id="pythonVersion" class="form-control">
                            {% for ver in versions %}
                            <option value="{{ ver }}" {% if ver == '3.11' %}selected{% endif %}>
                                Python {{ ver }}
                                {% if ver in python_versions %}✅{% endif %}
                            </option>
                            {% endfor %}
                        </select>
                    </div>
                    <div class="form-group">
                        <label>Gereksinimler (virgülle ayır)</label>
                        <input type="text" id="requirements" class="form-control" placeholder="requests, telethon, flask">
                    </div>
                </div>
                <div class="form-group">
                    <label>Bot Kodu</label>
                    <textarea id="botCode" class="form-control" placeholder="Bot kodunuzu buraya yapıştırın..."></textarea>
                </div>
                <button type="submit" class="btn btn-create" style="width: 100%;">🚀 Bot Oluştur</button>
            </form>
        </div>

        <!-- Bot Listesi -->
        <div class="panel">
            <h2>📊 Botlarım</h2>
            <div id="botsContainer">
                <div class="grid" id="botsGrid">
                    {% if bots %}
                        {% for name, data in bots.items() %}
                        <div class="card" id="bot-{{ name }}">
                            <div class="card-title">
                                {{ name }}
                                <span class="status-badge status-{{ data.status }}">
                                    {{ data.status|upper }}
                                </span>
                            </div>
                            <div class="bot-info">
                                <div>🐍 Python: {{ data.python_version }}</div>
                                <div>🆔 PID: {{ data.pid or 'N/A' }}</div>
                                <div>📁 Dosya: {{ data.bot_file }}</div>
                                <div>📅 Oluşturuldu: {{ data.created_at[:19] if data.created_at else 'N/A' }}</div>
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-start" onclick="controlBot('{{ name }}', 'start')">▶ Başlat</button>
                                <button class="btn btn-stop" onclick="controlBot('{{ name }}', 'stop')">⏹ Durdur</button>
                                <button class="btn btn-restart" onclick="controlBot('{{ name }}', 'restart')">🔄 Yeniden Başlat</button>
                                <button class="btn btn-delete" onclick="deleteBot('{{ name }}')">🗑 Sil</button>
                            </div>
                            <div style="display: flex; gap: 8px; margin-top: 10px;">
                                <input type="text" id="pkg-{{ name }}" class="form-control" placeholder="Paket adı" style="flex: 1;">
                                <button class="btn btn-install" onclick="installPackage('{{ name }}')">📦 Yükle</button>
                                <button class="btn btn-log" onclick="showLogs('{{ name }}')">📄 Log</button>
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div style="text-align: center; padding: 50px; color: #666;">
                            <h3>Henüz bot yok</h3>
                            <p>Yukarıdaki formdan ilk botunuzu oluşturun!</p>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- Log Gösterici -->
        <div class="panel" id="logPanel" style="display: none;">
            <h2>📄 Bot Logları</h2>
            <div id="logContent" class="log-container">Loglar burada görünecek...</div>
            <button class="btn btn-log" onclick="document.getElementById('logPanel').style.display='none'">Kapat</button>
        </div>
    </div>

    <script>
        // ============ API İŞLEMLERİ ============
        
        function controlBot(name, action) {
            fetch(`/api/bot/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bot_name: name })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    location.reload();
                } else {
                    alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                }
            })
            .catch(err => alert('❌ Bağlantı hatası: ' + err));
        }

        function deleteBot(name) {
            if (confirm(`❓ "${name}" botunu silmek istediğinize emin misiniz?`)) {
                fetch('/api/bot/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bot_name: name })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        location.reload();
                    } else {
                        alert('❌ Hata: ' + (data.error || 'Bilinmeyen hata'));
                    }
                });
            }
        }

        function installPackage(name) {
            const pkgInput = document.getElementById(`pkg-${name}`);
            const packages = pkgInput.value.split(',').map(p => p.trim()).filter(p => p);
            
            if (!packages.length) {
                alert('⚠️ En az bir paket adı girin!');
                return;
            }
            
            fetch('/api/bot/install', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    bot_name: name,
                    packages: packages
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Paketler başarıyla yüklendi!\n' + data.installed.join('\n'));
                    pkgInput.value = '';
                } else {
                    alert('❌ Bazı paketler yüklenemedi:\n' + (data.failed || []).join('\n'));
                }
            });
        }

        function showLogs(name) {
            fetch(`/api/bot/logs?bot_name=${name}&lines=100`)
                .then(res => res.json())
                .then(data => {
                    const panel = document.getElementById('logPanel');
                    const content = document.getElementById('logContent');
                    content.textContent = data.logs.join('');
                    panel.style.display = 'block';
                    panel.scrollIntoView({ behavior: 'smooth' });
                });
        }

        // ============ YENİ BOT OLUŞTUR ============
        
        document.getElementById('createBotForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const name = document.getElementById('botName').value.trim();
            const code = document.getElementById('botCode').value;
            const version = document.getElementById('pythonVersion').value;
            const reqs = document.getElementById('requirements').value.split(',').map(p => p.trim()).filter(p => p);
            
            if (!name) {
                alert('⚠️ Bot adı gerekli!');
                return;
            }
            
            if (!code) {
                alert('⚠️ Bot kodu gerekli!');
                return;
            }
            
            fetch('/api/bot/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    bot_name: name,
                    bot_code: code,
                    python_version: version,
                    requirements: reqs
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Bot başarıyla oluşturuldu!');
                    location.reload();
                } else {
                    alert('❌ Hata: ' + data.message);
                }
            })
            .catch(err => alert('❌ Bağlantı hatası: ' + err));
        });

        // ============ OTOMATİK YENİLEME ============
        
        // Her 30 saniyede bir durumu kontrol et
        setInterval(() => {
            fetch('/api/bots')
                .then(res => res.json())
                .then(data => {
                    // Sadece durum badge'lerini güncelle
                    for (const [name, info] of Object.entries(data)) {
                        const card = document.getElementById(`bot-${name}`);
                        if (card) {
                            const badge = card.querySelector('.status-badge');
                            if (badge) {
                                badge.className = `status-badge status-${info.status}`;
                                badge.textContent = info.status.toUpperCase();
                            }
                            const pidSpan = card.querySelector('.bot-info div:nth-child(2)');
                            if (pidSpan) {
                                pidSpan.textContent = `🆔 PID: ${info.pid || 'N/A'}`;
                            }
                        }
                    }
                })
                .catch(err => console.error('Refresh error:', err));
        }, 30000);
    </script>
</body>
</html>
"""

# ============ TEMPLATE'İ KAYDET ============
@app.route('/templates/index.html')
def get_template():
    return TEMPLATE

# ============ ANA ÇALIŞTIRICI ============
def main():
    """Ana fonksiyon"""
    logger.info("🚀 Universal Bot Hosting Manager başlatılıyor...")
    logger.info(f"📌 Port: {PORT}")
    logger.info(f"🐍 Python versiyonları: {list(manager.python_versions.keys())}")
    
    # Flask'ı başlat
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)

if __name__ == '__main__':
    main()
