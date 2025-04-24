# Tigo MQTT Bridge

A Python-based bridge between Tigo TAP (Tigo Access Point) solar monitoring hardware and MQTT. This tool allows you to receive real-time data from Tigo optimizers and publish it to an MQTT broker for integration with home automation systems, data logging, or custom monitoring solutions.

## Features

- Connect to Tigo TAP devices via serial port or TCP
- Parse Tigo's proprietary protocol
- Extract power metrics from optimizers (voltage, current, temperature, etc.)
- Publish data to MQTT broker
- Support for node address persistence
- Deduplication of similar power reports
- Configurable logging levels
- Real-time monitoring with CLI tool

## Requirements

- Python 3.x
- paho-mqtt (`pip install paho-mqtt`)
- pyserial (`pip install pyserial`) - for serial connections only
- tabulate (`pip install tabulate`) - for monitor CLI

## Installation

1. Clone this repository:
   ```
   git clone <repository-url>
   ```

2. Create and activate a virtual environment (recommended):
   ```bash
   # Create virtual environment
   python -m venv venv
   
   # Activate virtual environment
   # On Linux/macOS:
   source venv/bin/activate
   
   # On Windows:
   venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install paho-mqtt pyserial tabulate
   ```
   
   Alternatively, if a requirements.txt file is provided:
   ```
   pip install -r requirements.txt
   ```

4. Make the script executable:
   ```
   chmod +x tigo-mqtt-bridge.py
   chmod +x tigo-monitor.py
   ```

5. When you're done using the application, you can deactivate the virtual environment:
   ```
   deactivate
   ```

## Usage

### Command Line Options

```
usage: tigo-mqtt-bridge.py [-h] (-s SERIAL | --tcp TCP) [-b BAUD_RATE] [--port PORT]
                          -m MQTT_SERVER [-p MQTT_PORT] [-u MQTT_USERNAME]
                          [-w MQTT_PASSWORD] [-t MQTT_PREFIX] [-n NODE_TABLE]
                          [-l {DEBUG,INFO,WARNING,ERROR,CRITICAL}]
                          [--dedup-window DEDUP_WINDOW]

Tigo TAP to MQTT Bridge
```

#### Connection Options
- `-s, --serial`: Serial port device (e.g., `/dev/ttyUSB0`)
- `--tcp`: TCP hostname for serial-over-TCP
- `-b, --baud-rate`: Serial baud rate (default: 38400)
- `--port`: TCP port for serial-over-TCP (default: 7160)

#### MQTT Options
- `-m, --mqtt-server`: MQTT server hostname (required)
- `-p, --mqtt-port`: MQTT server port (default: 1883)
- `-u, --mqtt-username`: MQTT username
- `-w, --mqtt-password`: MQTT password
- `-t, --mqtt-prefix`: MQTT topic prefix (default: 'tigo')

#### Other Options
- `-n, --node-table`: Node table storage path (default: './nodeTable.pickle')
- `-l, --log-level`: Set logging level (choices: DEBUG, INFO, WARNING, ERROR, CRITICAL; default: INFO)
- `--dedup-window`: Time window (in seconds) to deduplicate similar power reports (default: 5.0, 0 to disable)

### Examples

Connect to a Tigo TAP via USB serial port:
```
./tigo-mqtt-bridge.py -s /dev/ttyUSB0 -m mqtt.local
```

Connect to a Tigo TAP via TCP (useful for ESP8266/ESP32 serial bridges):
```
./tigo-mqtt-bridge.py --tcp 192.168.1.100 --port 7160 -m mqtt.local
```

Enable verbose logging:
```
./tigo-mqtt-bridge.py -s /dev/ttyUSB0 -m mqtt.local -l DEBUG
```

## Running as a Service

To run the Tigo MQTT Bridge as a system service that starts automatically on boot:

1. Create a systemd service file:

```bash
sudo nano /etc/systemd/system/tigo-mqtt-bridge.service
```

2. Add the following content (adjusting paths and options as needed):

```ini
[Unit]
Description=Tigo TAP to MQTT Bridge
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/installation/directory
ExecStart=/path/to/installation/directory/venv/bin/python /path/to/installation/directory/tigo-mqtt-bridge.py -s /dev/ttyUSB0 -m mqtt.local
Restart=on-failure
RestartSec=5
StandardOutput=journal

[Install]
WantedBy=multi-user.target
```

3. Reload systemd, enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable tigo-mqtt-bridge.service
sudo systemctl start tigo-mqtt-bridge.service
```

4. Check the status of the service:

```bash
sudo systemctl status tigo-mqtt-bridge.service
```

5. View logs:

```bash
sudo journalctl -u tigo-mqtt-bridge.service -f
```

6. To stop or restart the service:

```bash
sudo systemctl stop tigo-mqtt-bridge.service
sudo systemctl restart tigo-mqtt-bridge.service
```

## How It Works

1. The bridge connects to the Tigo TAP hardware via serial port or TCP connection
2. It listens for data frames in Tigo's proprietary protocol
3. When power reports are received, they're parsed to extract voltage, current, temperature, etc.
4. This data is published to the MQTT broker with topics in the format: `{prefix}/{device_address}`
5. The bridge maintains a mapping between node IDs and MAC addresses in a persistent store

## MQTT Data Format

Data is published as JSON with the following structure:

```json
{
  "NodeID": 1234,
  "VIN": 30.5,
  "VOUT": 36.0,
  "DUTY": 80.0,
  "AMPSIN": 0.875,
  "TEMP": 42.5,
  "RSSI": 78,
  "SLOT": 1234,
  "POWER": 26.69,
  "Address": "00:11:22:33:44:55:66:77",
  "GatewayID": 1,
  "Timestamp": 1634567890.123
}
```

## Tigo Monitor CLI

A companion utility is included to visualize Tigo optimizer data in real time from the terminal.

### Features

- Real-time monitoring of all Tigo optimizers
- Color-coded output for temperature and power values
- Automatic sorting by Node ID
- Display of last update time for each optimizer
- Customizable refresh interval
- Clean exit with Ctrl+C

### Usage

```
usage: tigo-monitor.py [-h] [-m MQTT_SERVER] [-p MQTT_PORT] [-u MQTT_USERNAME]
                       [-w MQTT_PASSWORD] [-t MQTT_PREFIX] [-r REFRESH] [-a AGE]

Tigo Optimizer MQTT Monitor
```

### Command Line Options

- `-m, --mqtt-server`: MQTT server hostname (default: localhost)
- `-p, --mqtt-port`: MQTT server port (default: 1883)
- `-u, --mqtt-username`: MQTT username
- `-w, --mqtt-password`: MQTT password
- `-t, --mqtt-prefix`: MQTT topic prefix (default: tigo)
- `-r, --refresh`: Display refresh interval in seconds (default: 2.0)
- `-a, --age`: Maximum age of data to display in seconds (default: 3600)

### Examples

Basic usage:
```
./tigo-monitor.py -m mqtt.local
```

With authentication and 5-second refresh:
```
./tigo-monitor.py -m mqtt.local -u your_username -w your_password -r 5
```

## Changelog

### Version 1.0.0 (April 24, 2025)
- Initial release

### Version 1.1.0 (April 24, 2025)
- **Fixed**: Topology report processing now correctly handles both `bytes` and `bytearray` types
- **Added**: Enhanced logging for topology reports to assist with troubleshooting
- **Added**: Detailed INFO level logging for raw data packets
- **Fixed**: Invalid address format warnings by properly handling bytearray objects

### Version 1.2.0 (April 24, 2025)
- **Added**: Tigo Monitor CLI for real-time visualization of optimizer data
- **Added**: Color-coded output in monitor for better readability
- **Added**: Systemd service configuration for running as a background service

## Credits and Acknowledgments

This project was created with the assistance of GitHub Copilot and draws heavily from the following sources:

- [kicomoco/tappipe](https://github.com/kicomoco/tappipe/tree/main) - For initial protocol understanding and implementation ideas
- [willglynn/taptap](https://github.com/willglynn/taptap) - For the excellent [protocol documentation](https://github.com/willglynn/taptap/blob/main/docs/protocol.md), which provides an exceptional level of detail about the Tigo TAP protocol

## License

This project is licensed under the MIT License - see the LICENSE file for details.