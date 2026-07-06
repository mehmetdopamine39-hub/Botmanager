#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import json
import time
import subprocess
import threading
import shutil
import logging
import re
import uuid
from datetime import datetime
from flask import Flask, render_template_string, request, jsonify, send_file
import requests

# ============ KONFİGÜRASYON ============
PORT = int(os.environ.get('PORT', 10000))
BOTS_DIR = "bots"
UPLOAD_DIR = "uploads"
ALLOWED_VERSIONS = []

# ============ LOG AYARLARI ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============ FLASK UYGULAMASI ============
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# ============ TELEGRAM BOT ============
TELEGRAM_TOKEN = "8747646346:AAHWb1lbNTVCFRuF4dqN_0AJE6rm73-9WEA"
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ============ BOT YÖNETİCİ ============
class UniversalBotManager:
    def __init__(self):
        self.bots = {}
        self.processes = {}
        self.python_versions = self.detect_all_python_versions()
        self.init_directories()
        self.load_bots()
        self.start_auto_restart_thread()
        self.start_telegram_thread()
        logger.info(f"✅ Bot Manager başlatıldı")
        logger.info(f"🐍 Tespit edilen Python sürümleri: {list(self.python_versions.keys())}")
    
    def detect_all_python_versions(self):
        """Sistemdeki TÜM Python sürümlerini tespit et"""
        versions = {}
        
        # 1. Sistemdeki Python sürümlerini ara
        python_patterns = [
            "python3.12", "python3.11", "python3.10", "python3.9", 
            "python3.8", "python3.7", "python3.6", "python3.5",
            "python3", "python"
        ]
        
        for cmd in python_patterns:
            try:
                result = subprocess.run(
                    [cmd, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    version_match = re.search(r'(\d+\.\d+)', result.stdout)
                    if version_match:
                        ver = version_match.group(1)
                        versions[ver] = {
                            "path": cmd,
                            "version": result.stdout.strip(),
                            "available": True,
                            "type": "system"
                        }
                        logger.info(f"✅ Python {ver} bulundu: {cmd}")
            except:
                pass
        
        # 2. Pyenv ile kurulu sürümleri ara
        try:
            result = subprocess.run(
                ["pyenv", "versions"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    version_match = re.search(r'(\d+\.\d+\.\d+)', line)
                    if version_match:
                        ver = version_match.group(1)[:3]  # 3.11 gibi
                        if ver not in versions:
                            try:
                                path_result = subprocess.run(
                                    ["pyenv", "which", f"python{ver}"],
                                    capture_output=True,
                                    text=True,
                                    timeout=2
                                )
                                if path_result.returncode == 0:
                                    versions[ver] = {
                                        "path": path_result.stdout.strip(),
                                        "version": f"Python {ver} (pyenv)",
                                        "available": True,
                                        "type": "pyenv"
                                    }
                                    logger.info(f"✅ Python {ver} pyenv'de bulundu")
                            except:
                                pass
        except:
            pass
        
        # 3. Conda ile kurulu sürümleri ara
        try:
            result = subprocess.run(
                ["conda", "list", "python"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'python' in line.lower():
                        version_match = re.search(r'(\d+\.\d+)', line)
                        if version_match:
                            ver = version_match.group(1)
                            if ver not in versions:
                                versions[ver] = {
                                    "path": "python",
                                    "version": f"Python {ver} (conda)",
                                    "available": True,
                                    "type": "conda"
                                }
                                logger.info(f"✅ Python {ver} conda'da bulundu")
        except:
            pass
        
        # Hiçbir sürüm bulunamazsa varsayılan
        if not versions:
            versions["3.11"] = {
                "path": "python3",
                "version": "Python 3.11 (default)",
                "available": True,
                "type": "default"
            }
            logger.warning("⚠️ Hiç Python sürümü bulunamadı, varsayılan kullanılıyor")
        
        return versions
    
    def init_directories(self):
        for dir_name in [BOTS_DIR, UPLOAD_DIR]:
            if not os.path.exists(dir_name):
                os.makedirs(dir_name)
                logger.info(f"📁 Dizin oluşturuldu: {dir_name}")
    
    def load_bots(self):
        bots_file = "bots_data.json"
        if os.path.exists(bots_file):
            try:
                with open(bots_file, 'r') as f:
                    self.bots = json.load(f)
                logger.info(f"📂 {len(self.bots)} bot yüklendi")
                for bot_name, bot_data in self.bots.items():
                    if bot_data.get("auto_start", True):
                        self.start_bot(bot_name)
            except Exception as e:
                logger.error(f"Botlar yüklenemedi: {e}")
                self.bots = {}
    
    def save_bots(self):
        bots_file = "bots_data.json"
        try:
            with open(bots_file, 'w') as f:
                json.dump(self.bots, f, indent=4)
        except Exception as e:
            logger.error(f"Bot verileri kaydedilemedi: {e}")
    
    def get_python_path(self, version):
        """Python sürümüne göre yolu getir - TÜM sürümler için"""
        if version in self.python_versions:
            return self.python_versions[version]["path"]
        
        # Versiyon numarasını dene
        for ver, info in self.python_versions.items():
            if ver.startswith(version):
                return info["path"]
        
        # Python3 dene
        return "python3"
    
    def get_best_python_version(self, bot_code=""):
        """Bot kodu için en uygun Python sürümünü bul"""
        # Önce mevcut sürümleri kontrol et
        available = list(self.python_versions.keys())
        
        # Eğer bot kodu varsa, içindeki sürüm bilgisini ara
        if bot_code:
            # Python sürümü ipuçlarını ara
            version_patterns = [
                r'python(\d+\.\d+)',
                r'#!.*python(\d+\.\d+)',
                r'requires.*python(\d+\.\d+)',
            ]
            for pattern in version_patterns:
                match = re.search(pattern, bot_code.lower())
                if match:
                    ver = match.group(1)
                    if ver in available:
                        return ver
        
        # Varsayılan olarak en yüksek sürümü kullan
        if available:
            return max(available, key=lambda x: float(x))
        return "3.11"
    
    def create_venv(self, bot_name, python_version=None):
        """Bot için sanal ortam oluştur - ZORLA çalıştır"""
        bot_path = os.path.join(BOTS_DIR, bot_name)
        venv_path = os.path.join(bot_path, "venv")
        
        if os.path.exists(venv_path):
            return venv_path
        
        # Python sürümünü bul
        if not python_version:
            python_version = self.get_best_python_version()
        
        python_path = self.get_python_path(python_version)
        
        try:
            # Önce venv modülünü kontrol et
            check_result = subprocess.run(
                [python_path, "-c", "import venv; print('OK')"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if check_result.returncode != 0:
                # Venv yoksa pip ile yükle
                subprocess.run(
                    [python_path, "-m", "pip", "install", "--upgrade", "venv"],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            
            # Sanal ortam oluştur
            subprocess.run(
                [python_path, "-m", "venv", venv_path],
                check=True,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            logger.info(f"✅ Sanal ortam oluşturuldu: {bot_name} (Python {python_version})")
            
            # Bot bilgilerini güncelle
            if bot_name in self.bots:
                self.bots[bot_name]["python_version"] = python_version
                self.bots[bot_name]["venv_path"] = venv_path
                self.save_bots()
            
            return venv_path
            
        except Exception as e:
            logger.error(f"❌ Sanal ortam oluşturulamadı: {e}")
            # Farklı bir sürüm dene
            for ver in self.python_versions.keys():
                if ver != python_version:
                    try:
                        return self.create_venv(bot_name, ver)
                    except:
                        continue
            return None
    
    def install_packages(self, bot_name, packages):
        """Bot için paket yükle - HATAZIS"""
        bot_path = os.path.join(BOTS_DIR, bot_name)
        venv_path = os.path.join(bot_path, "venv")
        
        if not os.path.exists(venv_path):
            self.create_venv(bot_name)
            venv_path = os.path.join(bot_path, "venv")
        
        # Pip yolunu bul
        if os.name == 'nt':
            pip_exe = os.path.join(venv_path, "Scripts", "pip.exe")
            python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            pip_exe = os.path.join(venv_path, "bin", "pip")
            python_exe = os.path.join(venv_path, "bin", "python")
        
        # Pip'i güncelle
        try:
            subprocess.run(
                [python_exe, "-m", "pip", "install", "--upgrade", "pip"],
                capture_output=True,
                text=True,
                timeout=30
            )
        except:
            pass
        
        installed = []
        failed = []
        
        for package in packages:
            try:
                result = subprocess.run(
                    [pip_exe, "install", package],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    installed.append(package)
                    logger.info(f"📦 Paket yüklendi: {package}")
                else:
                    failed.append(package)
                    logger.error(f"❌ Paket yüklenemedi: {package} - {result.stderr}")
            except Exception as e:
                failed.append(package)
                logger.error(f"❌ Paket yüklenemedi: {package} - {e}")
        
        return installed, failed
    
    def start_bot(self, bot_name):
        """Bot'u başlat - ZORLA çalıştır"""
        if bot_name not in self.bots:
            return False, "Bot bulunamadı"
        
        bot_data = self.bots[bot_name]
        bot_path = os.path.join(BOTS_DIR, bot_name)
        bot_file = bot_data.get("bot_file", "bot.py")
        python_version = bot_data.get("python_version")
        
        # Python sürümünü bul
        if not python_version or python_version not in self.python_versions:
            python_version = self.get_best_python_version()
        
        # Sanal ortam
        venv_path = os.path.join(bot_path, "venv")
        if not os.path.exists(venv_path):
            self.create_venv(bot_name, python_version)
            venv_path = os.path.join(bot_path, "venv")
        
        # Python yolu
        if os.name == 'nt':
            python_exe = os.path.join(venv_path, "Scripts", "python.exe")
        else:
            python_exe = os.path.join(venv_path, "bin", "python")
        
        # Bot dosyası
        bot_script = os.path.join(bot_path, bot_file)
        
        if not os.path.exists(bot_script):
            return False, "Bot dosyası bulunamadı"
        
        try:
            # Bot'u arka planda çalıştır
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
            return True, f"Bot başlatıldı (PID: {process.pid})"
            
        except Exception as e:
            logger.error(f"❌ Bot başlatılamadı: {e}")
            bot_data["status"] = "error"
            self.save_bots()
            return False, str(e)
    
    def stop_bot(self, bot_name):
        """Bot'u durdur"""
        if bot_name in self.processes:
            process = self.processes[bot_name]
            try:
                process.terminate()
                time.sleep(2)
                if process.poll() is None:
                    process.kill()
                
                del self.processes[bot_name]
                self.bots[bot_name]["status"] = "stopped"
                self.bots[bot_name]["pid"] = None
                self.save_bots()
                return True, "Bot durduruldu"
            except Exception as e:
                return False, str(e)
        return False, "Bot çalışmıyor"
    
    def restart_bot(self, bot_name):
        """Bot'u yeniden başlat"""
        self.stop_bot(bot_name)
        time.sleep(2)
        return self.start_bot(bot_name)
    
    def delete_bot(self, bot_name):
        """Bot'u sil"""
        self.stop_bot(bot_name)
        bot_path = os.path.join(BOTS_DIR, bot_name)
        try:
            shutil.rmtree(bot_path)
            if bot_name in self.bots:
                del self.bots[bot_name]
                self.save_bots()
            return True, "Bot silindi"
        except Exception as e:
            return False, str(e)
    
    def create_bot(self, bot_name, bot_code, python_version=None, requirements=None):
        """Yeni bot oluştur"""
        if bot_name in self.bots:
            return False, "Bot zaten var"
        
        bot_path = os.path.join(BOTS_DIR, bot_name)
        try:
            os.makedirs(bot_path)
            
            # Bot dosyasını oluştur
            with open(os.path.join(bot_path, "bot.py"), 'w') as f:
                f.write(bot_code)
            
            # Python sürümünü belirle
            if not python_version:
                python_version = self.get_best_python_version(bot_code)
            
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
                "auto_start": False,
                "created_at": datetime.now().isoformat(),
                "requirements": requirements or []
            }
            self.save_bots()
            
            logger.info(f"✅ Yeni bot oluşturuldu: {bot_name} (Python {python_version})")
            return True, f"Bot oluşturuldu (Python {python_version})"
            
        except Exception as e:
            logger.error(f"❌ Bot oluşturulamadı: {e}")
            return False, str(e)
    
    def upload_bot_file(self, file_content, filename):
        """Bot dosyası yükle"""
        bot_name = os.path.splitext(filename)[0]
        bot_path = os.path.join(BOTS_DIR, bot_name)
        
        try:
            os.makedirs(bot_path, exist_ok=True)
            
            # Dosyayı kaydet
            file_path = os.path.join(bot_path, filename)
            with open(file_path, 'wb') as f:
                f.write(file_content)
            
            # Python sürümünü tespit et
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    bot_code = f.read()
                python_version = self.get_best_python_version(bot_code)
            except:
                python_version = self.get_best_python_version()
            
            # Sanal ortam oluştur
            venv_path = self.create_venv(bot_name, python_version)
            
            # Bot'u kaydet
            self.bots[bot_name] = {
                "status": "stopped",
                "pid": None,
                "python_version": python_version,
                "venv_path": venv_path,
                "bot_file": filename,
                "auto_start": False,
                "created_at": datetime.now().isoformat(),
                "uploaded": True
            }
            self.save_bots()
            
            return True, f"Dosya yüklendi: {filename}"
            
        except Exception as e:
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
    
    def get_all_bots_info(self):
        """Tüm bot bilgilerini getir"""
        info = {}
        for name, data in self.bots.items():
            status = self.get_bot_status(name)
            info[name] = {
                "status": status,
                "pid": data.get("pid"),
                "python_version": data.get("python_version"),
                "created_at": data.get("created_at"),
                "bot_file": data.get("bot_file"),
                "requirements": data.get("requirements", [])
            }
        return info
    
    def auto_restart_loop(self):
        """Otomatik yeniden başlatma"""
        while True:
            try:
                for bot_name, process in list(self.processes.items()):
                    if process.poll() is not None:
                        logger.warning(f"⚠️ Bot çöktü: {bot_name}")
                        self.restart_bot(bot_name)
                time.sleep(30)
            except Exception as e:
                logger.error(f"❌ Otomatik yeniden başlatma hatası: {e}")
                time.sleep(10)
    
    def start_auto_restart_thread(self):
        thread = threading.Thread(target=self.auto_restart_loop, daemon=True)
        thread.start()
    
    def start_telegram_thread(self):
        thread = threading.Thread(target=self.telegram_bot_loop, daemon=True)
        thread.start()
    
    def telegram_bot_loop(self):
        """Telegram bot döngüsü"""
        last_update_id = 0
        while True:
            try:
                # Mesajları kontrol et
                url = f"{TELEGRAM_API}/getUpdates"
                params = {"offset": last_update_id + 1, "timeout": 30}
                response = requests.get(url, params=params, timeout=35)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            last_update_id = update["update_id"]
                            self.handle_telegram_message(update)
                
                time.sleep(1)
            except Exception as e:
                logger.error(f"Telegram hatası: {e}")
                time.sleep(5)
    
    def handle_telegram_message(self, update):
        """Telegram mesajlarını işle"""
        try:
            message = update.get("message")
            if not message:
                return
            
            chat_id = message["chat"]["id"]
            text = message.get("text", "")
            document = message.get("document")
            
            # Komutları işle
            if text.startswith("/"):
                self.handle_telegram_command(chat_id, text, message)
            elif document:
                self.handle_telegram_file(chat_id, document)
            else:
                self.send_telegram_message(chat_id, "❓ Bilinmeyen komut. /help yazın.")
                
        except Exception as e:
            logger.error(f"Telegram mesaj işleme hatası: {e}")
    
    def handle_telegram_command(self, chat_id, text, message):
        """Telegram komutlarını işle"""
        command = text.split()[0].lower()
        args = text.split()[1:] if len(text.split()) > 1 else []
        
        if command == "/start" or command == "/help":
            help_text = """
🤖 **Universal Bot Hosting Manager**

📌 **Komutlar:**
/start - Başlat
/help - Yardım
/list - Botları listele
/status <bot_adı> - Bot durumu
/startbot <bot_adı> - Bot başlat
/stopbot <bot_adı> - Bot durdur
/restartbot <bot_adı> - Bot yeniden başlat
/deletebot <bot_adı> - Bot sil
/logs <bot_adı> - Bot logları
/create <bot_adı> - Bot oluştur (mesaja kod yapıştır)
/install <bot_adı> <paketler> - Paket yükle

📎 **Dosya Yükleme:**
.py dosyası gönder → Otomatik bot oluştur

⚡ **Özellikler:**
• Tüm Python sürümleriyle uyumlu
• Otomatik yeniden başlatma
• 7/24 çalışma
"""
            self.send_telegram_message(chat_id, help_text)
        
        elif command == "/list":
            bots = self.get_all_bots_info()
            if not bots:
                self.send_telegram_message(chat_id, "📭 Hiç bot yok.")
            else:
                msg = "📊 **Bot Listesi:**\n\n"
                for name, info in bots.items():
                    status_emoji = "🟢" if info["status"] == "running" else "🔴"
                    msg += f"{status_emoji} **{name}**\n"
                    msg += f"   • Durum: {info['status']}\n"
                    msg += f"   • Python: {info.get('python_version', 'N/A')}\n"
                    msg += f"   • PID: {info.get('pid', 'N/A')}\n\n"
                self.send_telegram_message(chat_id, msg)
        
        elif command == "/status":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /status <bot_adı>")
                return
            bot_name = args[0]
            if bot_name not in self.bots:
                self.send_telegram_message(chat_id, f"❌ Bot bulunamadı: {bot_name}")
                return
            info = self.bots[bot_name]
            status = self.get_bot_status(bot_name)
            msg = f"📊 **{bot_name}**\n"
            msg += f"• Durum: {status}\n"
            msg += f"• Python: {info.get('python_version', 'N/A')}\n"
            msg += f"• PID: {info.get('pid', 'N/A')}\n"
            msg += f"• Dosya: {info.get('bot_file', 'N/A')}\n"
            msg += f"• Oluşturuldu: {info.get('created_at', 'N/A')[:19]}\n"
            self.send_telegram_message(chat_id, msg)
        
        elif command == "/startbot":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /startbot <bot_adı>")
                return
            bot_name = args[0]
            success, message = self.start_bot(bot_name)
            self.send_telegram_message(chat_id, f"{'✅' if success else '❌'} {message}")
        
        elif command == "/stopbot":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /stopbot <bot_adı>")
                return
            bot_name = args[0]
            success, message = self.stop_bot(bot_name)
            self.send_telegram_message(chat_id, f"{'✅' if success else '❌'} {message}")
        
        elif command == "/restartbot":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /restartbot <bot_adı>")
                return
            bot_name = args[0]
            success, message = self.restart_bot(bot_name)
            self.send_telegram_message(chat_id, f"{'✅' if success else '❌'} {message}")
        
        elif command == "/deletebot":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /deletebot <bot_adı>")
                return
            bot_name = args[0]
            success, message = self.delete_bot(bot_name)
            self.send_telegram_message(chat_id, f"{'✅' if success else '❌'} {message}")
        
        elif command == "/logs":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /logs <bot_adı>")
                return
            bot_name = args[0]
            logs = self.get_bot_logs(bot_name, 50)
            if logs and logs != ["Log dosyası bulunamadı"]:
                log_text = "\n".join(logs[-30:])  # Son 30 satır
                if len(log_text) > 4000:
                    log_text = log_text[-4000:]
                self.send_telegram_message(chat_id, f"📄 **{bot_name} Logları:**\n```\n{log_text}\n```")
            else:
                self.send_telegram_message(chat_id, f"📄 {bot_name}: {logs[0] if logs else 'Log yok'}")
        
        elif command == "/create":
            if not args:
                self.send_telegram_message(chat_id, "❌ Bot adı girin: /create <bot_adı>\nMesaja bot kodunu yapıştırın.")
                return
            bot_name = args[0]
            # Mesajın devamını kod olarak al
            code_parts = text.split(maxsplit=1)
            if len(code_parts) > 1:
                bot_code = code_parts[1]
                success, message = self.create_bot(bot_name, bot_code)
                self.send_telegram_message(chat_id, f"{'✅' if success else '❌'} {message}")
            else:
                self.send_telegram_message(chat_id, "❌ Bot kodunu mesaja yapıştırın: /create <bot_adı> <kod>")
        
        elif command == "/install":
            if len(args) < 2:
                self.send_telegram_message(chat_id, "❌ Kullanım: /install <bot_adı> <paket1,paket2>")
                return
            bot_name = args[0]
            packages = args[1].split(",")
            installed, failed = self.install_packages(bot_name, packages)
            msg = "📦 **Paket Yükleme Sonucu:**\n"
            if installed:
                msg += f"✅ Yüklenen: {', '.join(installed)}\n"
            if failed:
                msg += f"❌ Yüklenemeyen: {', '.join(failed)}"
            self.send_telegram_message(chat_id, msg)
        
        else:
            self.send_telegram_message(chat_id, f"❌ Bilinmeyen komut: {command}\n/help yazın.")
    
    def handle_telegram_file(self, chat_id, document):
        """Telegram'dan gelen dosyayı işle"""
        try:
            file_name = document.get("file_name", "")
            if not file_name.endswith(".py"):
                self.send_telegram_message(chat_id, "❌ Sadece .py dosyaları kabul edilir.")
                return
            
            file_id = document["file_id"]
            file_url = f"{TELEGRAM_API}/getFile?file_id={file_id}"
            response = requests.get(file_url)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    file_path = data["result"]["file_path"]
                    download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
                    
                    # Dosyayı indir
                    file_response = requests.get(download_url)
                    if file_response.status_code == 200:
                        success, message = self.upload_bot_file(
                            file_response.content,
                            file_name
                        )
                        self.send_telegram_message(chat_id, f"{'✅' if success else '❌'} {message}")
                    else:
                        self.send_telegram_message(chat_id, "❌ Dosya indirilemedi.")
                else:
                    self.send_telegram_message(chat_id, "❌ Dosya bilgisi alınamadı.")
            else:
                self.send_telegram_message(chat_id, "❌ Telegram API hatası.")
                
        except Exception as e:
            self.send_telegram_message(chat_id, f"❌ Hata: {str(e)}")
    
    def send_telegram_message(self, chat_id, text):
        """Telegram mesajı gönder"""
        try:
            url = f"{TELEGRAM_API}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            requests.post(url, json=data, timeout=10)
        except Exception as e:
            logger.error(f"Telegram mesaj gönderme hatası: {e}")

# ============ FLASK ROUTES ============
manager = UniversalBotManager()

@app.route('/')
def index():
    return render_template_string(TEMPLATE, 
                         bots=manager.get_all_bots_info(),
                         versions=manager.python_versions)

@app.route('/api/bots', methods=['GET'])
def get_bots():
    return jsonify(manager.get_all_bots_info())

@app.route('/api/bot/start', methods=['POST'])
def api_start_bot():
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success, message = manager.start_bot(bot_name)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/stop', methods=['POST'])
def api_stop_bot():
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success, message = manager.stop_bot(bot_name)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/restart', methods=['POST'])
def api_restart_bot():
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success, message = manager.restart_bot(bot_name)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/delete', methods=['POST'])
def api_delete_bot():
    data = request.json
    bot_name = data.get('bot_name')
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    success, message = manager.delete_bot(bot_name)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/create', methods=['POST'])
def api_create_bot():
    data = request.json
    bot_name = data.get('bot_name')
    bot_code = data.get('bot_code', '')
    python_version = data.get('python_version')
    requirements = data.get('requirements', [])
    
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    if not bot_code:
        return jsonify({"error": "Bot kodu gerekli"}), 400
    
    success, message = manager.create_bot(bot_name, bot_code, python_version, requirements)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/upload', methods=['POST'])
def api_upload_bot():
    if 'file' not in request.files:
        return jsonify({"error": "Dosya gerekli"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Dosya seçilmedi"}), 400
    
    if not file.filename.endswith('.py'):
        return jsonify({"error": "Sadece .py dosyaları"}), 400
    
    success, message = manager.upload_bot_file(file.read(), file.filename)
    return jsonify({"success": success, "message": message})

@app.route('/api/bot/install', methods=['POST'])
def api_install_packages():
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
    bot_name = request.args.get('bot_name')
    lines = int(request.args.get('lines', 100))
    
    if not bot_name:
        return jsonify({"error": "Bot adı gerekli"}), 400
    
    logs = manager.get_bot_logs(bot_name, lines)
    return jsonify({"logs": logs})

@app.route('/api/versions', methods=['GET'])
def api_get_versions():
    return jsonify(manager.python_versions)

# ============ TEMPLATE ============
TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🤖 Universal Bot Hosting</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        .header {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.1);
        }
        .header h1 { color: #333; font-size: 2.5em; }
        .header .subtitle { color: #666; font-size: 1.1em; }
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
        .card:hover { transform: translateY(-5px); }
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
        .status-error { background: #f44336; color: white; }
        .status-unknown { background: #9e9e9e; color: white; }
        .bot-info { color: #666; font-size: 0.9em; margin: 10px 0; }
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
        }
        .btn:hover { transform: scale(1.05); }
        .btn-start { background: #4CAF50; color: white; }
        .btn-stop { background: #f44336; color: white; }
        .btn-restart { background: #ff9800; color: white; }
        .btn-delete { background: #9c27b0; color: white; }
        .btn-create { background: #2196F3; color: white; }
        .btn-install { background: #009688; color: white; }
        .btn-log { background: #607d8b; color: white; }
        .btn-upload { background: #3f51b5; color: white; }
        .panel {
            background: rgba(255,255,255,0.95);
            border-radius: 15px;
            padding: 25px;
            margin-bottom: 30px;
            box-shadow: 0 5px 20px rgba(0,0,0,0.1);
        }
        .panel h2 { color: #333; margin-bottom: 20px; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; color: #333; font-weight: 500; margin-bottom: 5px; }
        .form-control {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
        }
        .form-control:focus { border-color: #667eea; outline: none; }
        textarea.form-control { min-height: 200px; font-family: 'Courier New', monospace; }
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
        .flex-row { display: flex; gap: 15px; flex-wrap: wrap; }
        .flex-row > * { flex: 1; min-width: 200px; }
        .badge {
            display: inline-block;
            padding: 3px 10px;
            background: #e0e0e0;
            border-radius: 12px;
            font-size: 0.8em;
            color: #333;
            margin: 3px;
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: 1fr; }
            .header h1 { font-size: 1.8em; }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🤖 Universal Bot Hosting</h1>
            <div class="subtitle">
                Tüm Python Sürümleriyle Uyumlu | 7/24 Aktif | Otomatik Yeniden Başlatma
            </div>
            <div style="margin-top: 10px;">
                <span class="badge">🐍 Python Sürümleri: {{ versions|join(', ') }}</span>
                <span class="badge">📦 Toplam Bot: {{ bots|length }}</span>
            </div>
        </div>

        <!-- Yeni Bot Oluştur -->
        <div class="panel">
            <h2>📦 Yeni Bot Oluştur / Yükle</h2>
            
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div>
                    <h3>📝 Kod ile Oluştur</h3>
                    <form id="createBotForm">
                        <div class="form-group">
                            <label>Bot Adı</label>
                            <input type="text" id="botName" class="form-control" placeholder="my_bot" required>
                        </div>
                        <div class="form-group">
                            <label>Python Sürümü (Opsiyonel)</label>
                            <select id="pythonVersion" class="form-control">
                                <option value="">Otomatik</option>
                                {% for ver in versions %}
                                <option value="{{ ver }}">Python {{ ver }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <div class="form-group">
                            <label>Gereksinimler (virgülle)</label>
                            <input type="text" id="requirements" class="form-control" placeholder="requests, telethon">
                        </div>
                        <div class="form-group">
                            <label>Bot Kodu</label>
                            <textarea id="botCode" class="form-control" placeholder="print('Hello Bot!')"></textarea>
                        </div>
                        <button type="submit" class="btn btn-create" style="width:100%;">🚀 Bot Oluştur</button>
                    </form>
                </div>
                
                <div>
                    <h3>📎 Dosya Yükle</h3>
                    <form id="uploadForm" enctype="multipart/form-data">
                        <div class="form-group">
                            <label>.py Dosyası Seç</label>
                            <input type="file" id="fileInput" class="form-control" accept=".py" required>
                        </div>
                        <button type="submit" class="btn btn-upload" style="width:100%;">📤 Dosyayı Yükle</button>
                    </form>
                    
                    <div style="margin-top: 20px; padding: 15px; background: #f5f5f5; border-radius: 8px;">
                        <h4>📱 Telegram Bot</h4>
                        <p>Bot üzerinden de yönetebilirsiniz:</p>
                        <code style="background: #333; color: #fff; padding: 5px; border-radius: 5px; display: block; word-break: break-all;">
                            @UniversalBotHost_bot
                        </code>
                        <p style="margin-top: 10px; font-size: 0.9em;">
                            /help - Tüm komutları göster
                        </p>
                    </div>
                </div>
            </div>
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
                                <span class="status-badge status-{{ data.status }}">{{ data.status|upper }}</span>
                            </div>
                            <div class="bot-info">
                                <div>🐍 Python: {{ data.python_version or 'N/A' }}</div>
                                <div>🆔 PID: {{ data.pid or 'N/A' }}</div>
                                <div>📅 Oluşturuldu: {{ data.created_at[:19] if data.created_at else 'N/A' }}</div>
                                {% if data.requirements %}
                                <div>📦 Paketler: {{ data.requirements|join(', ') }}</div>
                                {% endif %}
                            </div>
                            <div class="btn-group">
                                <button class="btn btn-start" onclick="controlBot('{{ name }}', 'start')">▶ Başlat</button>
                                <button class="btn btn-stop" onclick="controlBot('{{ name }}', 'stop')">⏹ Durdur</button>
                                <button class="btn btn-restart" onclick="controlBot('{{ name }}', 'restart')">🔄 Yeniden Başlat</button>
                                <button class="btn btn-delete" onclick="deleteBot('{{ name }}')">🗑 Sil</button>
                            </div>
                            <div style="display:flex; gap:8px; margin-top:10px;">
                                <input type="text" id="pkg-{{ name }}" class="form-control" placeholder="Paket adı" style="flex:1;">
                                <button class="btn btn-install" onclick="installPackage('{{ name }}')">📦 Yükle</button>
                                <button class="btn btn-log" onclick="showLogs('{{ name }}')">📄 Log</button>
                            </div>
                        </div>
                        {% endfor %}
                    {% else %}
                        <div style="text-align:center; padding:50px; color:#666;">
                            <h3>📭 Henüz bot yok</h3>
                            <p>Yukarıdaki formdan bot oluşturun veya dosya yükleyin!</p>
                        </div>
                    {% endif %}
                </div>
            </div>
        </div>

        <!-- Log Gösterici -->
        <div class="panel" id="logPanel" style="display:none;">
            <h2>📄 Bot Logları</h2>
            <div id="logContent" class="log-container">Loglar burada...</div>
            <button class="btn btn-log" onclick="document.getElementById('logPanel').style.display='none'" style="margin-top:10px;">Kapat</button>
        </div>
    </div>

    <script>
        function controlBot(name, action) {
            fetch(`/api/bot/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bot_name: name })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) { 
                    alert('✅ ' + data.message);
                    location.reload();
                } else {
                    alert('❌ Hata: ' + (data.message || data.error || 'Bilinmeyen hata'));
                }
            })
            .catch(err => alert('❌ Bağlantı hatası: ' + err));
        }

        function deleteBot(name) {
            if (confirm(`"${name}" botunu silmek istediğinize emin misiniz?`)) {
                fetch('/api/bot/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bot_name: name })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) { 
                        alert('✅ ' + data.message);
                        location.reload();
                    } else {
                        alert('❌ Hata: ' + (data.message || data.error));
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
                body: JSON.stringify({ bot_name: name, packages: packages })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ Paketler yüklendi!\n' + data.installed.join('\n'));
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
                    document.getElementById('logContent').textContent = data.logs.join('');
                    document.getElementById('logPanel').style.display = 'block';
                    document.getElementById('logPanel').scrollIntoView({ behavior: 'smooth' });
                });
        }

        document.getElementById('createBotForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const name = document.getElementById('botName').value.trim();
            const code = document.getElementById('botCode').value;
            const version = document.getElementById('pythonVersion').value;
            const reqs = document.getElementById('requirements').value.split(',').map(p => p.trim()).filter(p => p);
            
            if (!name) { alert('⚠️ Bot adı gerekli!'); return; }
            if (!code) { alert('⚠️ Bot kodu gerekli!'); return; }
            
            fetch('/api/bot/create', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    bot_name: name,
                    bot_code: code,
                    python_version: version || null,
                    requirements: reqs
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ ' + data.message);
                    location.reload();
                } else {
                    alert('❌ Hata: ' + data.message);
                }
            });
        });

        document.getElementById('uploadForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const fileInput = document.getElementById('fileInput');
            if (!fileInput.files.length) {
                alert('⚠️ Dosya seçin!');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            
            fetch('/api/bot/upload', {
                method: 'POST',
                body: formData
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    alert('✅ ' + data.message);
                    location.reload();
                } else {
                    alert('❌ Hata: ' + data.message);
                }
            });
        });

        // Otomatik yenileme
        setInterval(() => {
            fetch('/api/bots')
                .then(res => res.json())
                .then(data => {
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
                .catch(() => {});
        }, 30000);
    </script>
</body>
</html>
"""

# ============ ANA ÇALIŞTIRICI ============
def main():
    logger.info("🚀 Universal Bot Hosting Manager başlatılıyor...")
    logger.info(f"📌 Port: {PORT}")
    logger.info(f"🐍 Python sürümleri: {list(manager.python_versions.keys())}")
    logger.info(f"🤖 Telegram bot aktif: @UniversalBotHost_bot")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)

if __name__ == '__main__':
    main()
