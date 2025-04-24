#!/usr/bin/env python3
# filepath: /home/c09l/datima-tigo/python-taptap/tigo-monitor.py

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt module not installed. Run: pip install paho-mqtt")
    sys.exit(1)

try:
    from tabulate import tabulate
except ImportError:
    print("Error: tabulate module not installed. Run: pip install tabulate")
    sys.exit(1)

# Global state
device_data = {}
last_update = 0
refresh_interval = 2  # seconds
should_exit = False

# ANSI color codes
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def on_connect(client, userdata, flags, rc):
    """Callback when connected to MQTT broker"""
    if rc == 0:
        print(f"Connected to MQTT broker at {args.mqtt_server}:{args.mqtt_port}")
        # Subscribe to all topics under prefix
        client.subscribe(f"{args.mqtt_prefix}/#")
    else:
        print(f"Connection to MQTT broker failed with code {rc}")
        sys.exit(1)

def on_message(client, userdata, msg):
    """Callback when message is received"""
    global device_data, last_update
    
    try:
        # Parse the JSON payload
        payload = json.loads(msg.payload.decode())
        
        # Get node ID and address
        node_id = payload.get('NodeID')
        address = payload.get('Address')
        
        if node_id is not None:
            # Add timestamp for display purposes
            payload['LastUpdate'] = datetime.now().strftime('%H:%M:%S')
            
            # Store in our device data dictionary by node ID
            device_data[node_id] = payload
            last_update = time.time()
    except json.JSONDecodeError:
        pass  # Ignore badly formatted messages
    except Exception as e:
        print(f"Error processing message: {e}")

def clear_screen():
    """Clear the terminal screen"""
    os.system('cls' if os.name == 'nt' else 'clear')

def format_age(timestamp):
    """Format the age of data in a human-readable way"""
    if timestamp is None:
        return "N/A"
    
    age_secs = time.time() - timestamp
    if age_secs < 60:
        color = Colors.GREEN
        text = f"{int(age_secs)}s ago"
    elif age_secs < 300:  # 5 minutes
        color = Colors.YELLOW
        text = f"{int(age_secs/60)}m {int(age_secs%60)}s ago"
    else:
        color = Colors.RED
        text = f"{int(age_secs/60)}m ago"
    
    return f"{color}{text}{Colors.ENDC}"

def display_data():
    """Display device data in a table format"""
    clear_screen()
    
    if not device_data:
        print("Waiting for data from Tigo optimizers...")
        return
    
    # Sort devices by node ID and prepare table rows
    sorted_devices = []
    for node_id in sorted(device_data.keys()):
        device = device_data[node_id]
        power = device.get('POWER', 0) or 0
        
        # Colorize power values
        if power > 0:
            power_str = f"{Colors.GREEN}{power:.2f}W{Colors.ENDC}"
        else:
            power_str = f"{power:.2f}W"
        
        # Calculate temperature color
        temp = device.get('TEMP', 0) or 0
        if temp > 70:
            temp_str = f"{Colors.RED}{temp}°C{Colors.ENDC}"
        elif temp > 55:
            temp_str = f"{Colors.YELLOW}{temp}°C{Colors.ENDC}"
        else:
            temp_str = f"{temp}°C"
        
        # Row data
        row = [
            f"{Colors.BOLD}{node_id}{Colors.ENDC}",
            device.get('Address', 'Unknown'),
            f"{device.get('VIN', 0):.2f}V",
            f"{device.get('AMPSIN', 0):.3f}A",
            power_str,
            temp_str,
            device.get('RSSI', 'N/A'),
            device.get('LastUpdate', 'N/A')
        ]
        sorted_devices.append(row)
    
    # Table headers
    headers = ["Node ID", "Address", "Voltage", "Current", "Power", "Temp", "RSSI", "Last Update"]
    
    # Print the table
    print(f"\n{Colors.HEADER}Tigo Optimizers Monitor{Colors.ENDC} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Connected to MQTT broker: {args.mqtt_server}, Topic prefix: {args.mqtt_prefix}")
    print(tabulate(sorted_devices, headers=headers, tablefmt="fancy_grid"))
    print(f"\nDisplaying {len(device_data)} optimizers. Last update: {format_age(last_update)}")
    print(f"Press Ctrl+C to exit. Refresh interval: {refresh_interval}s\n")

def signal_handler(sig, frame):
    """Handle Ctrl+C"""
    global should_exit
    print("\nExiting...")
    should_exit = True

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Tigo Optimizer MQTT Monitor")
    
    parser.add_argument('-m', '--mqtt-server', default='localhost', 
                        help='MQTT server hostname (default: localhost)')
    parser.add_argument('-p', '--mqtt-port', type=int, default=1883, 
                        help='MQTT server port (default: 1883)')
    parser.add_argument('-u', '--mqtt-username', help='MQTT username')
    parser.add_argument('-w', '--mqtt-password', help='MQTT password')
    parser.add_argument('-t', '--mqtt-prefix', default='tigo', 
                        help='MQTT topic prefix (default: tigo)')
    parser.add_argument('-r', '--refresh', type=float, default=2.0,
                        help='Display refresh interval in seconds (default: 2.0)')
    parser.add_argument('-a', '--age', type=int, default=3600,
                        help='Maximum age of data to display in seconds (default: 3600)')
    
    return parser.parse_args()

if __name__ == "__main__":
    # Parse arguments
    args = parse_args()
    refresh_interval = args.refresh
    
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)

    # Initialize MQTT client and connect
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Set username/password if provided
    if args.mqtt_username and args.mqtt_password:
        client.username_pw_set(args.mqtt_username, args.mqtt_password)
    
    try:
        # Connect to broker
        client.connect(args.mqtt_server, args.mqtt_port, 60)
        
        # Start the client loop in separate thread
        client.loop_start()
        
        # Main display loop
        while not should_exit:
            display_data()
            time.sleep(refresh_interval)
            
    except KeyboardInterrupt:
        print("\nExiting...")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up resources
        client.loop_stop()
        client.disconnect()