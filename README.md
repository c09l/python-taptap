Tigo MQTT Bridge
A Python-based bridge between Tigo TAP (Tigo Access Point) solar monitoring hardware and MQTT. This tool allows you to receive real-time data from Tigo optimizers and publish it to an MQTT broker for integration with home automation systems, data logging, or custom monitoring solutions.

Features
Connect to Tigo TAP devices via serial port or TCP
Parse Tigo's proprietary protocol
Extract power metrics from optimizers (voltage, current, temperature, etc.)
Publish data to MQTT broker
Support for node address persistence
Deduplication of similar power reports
Configurable logging levels
Requirements
Python 3.x
paho-mqtt (pip install paho-mqtt)
pyserial (pip install pyserial) - for serial connections only
Installation
Clone this repository:

Create and activate a virtual environment (recommended):

Install dependencies:

Alternatively, if a requirements.txt file is provided:

Make the script executable:

When you're done using the application, you can deactivate the virtual environment:

Usage
Command Line Options
Connection Options
-s, --serial: Serial port device (e.g., /dev/ttyUSB0)
--tcp: TCP hostname for serial-over-TCP
-b, --baud-rate: Serial baud rate (default: 38400)
--port: TCP port for serial-over-TCP (default: 7160)
MQTT Options
-m, --mqtt-server: MQTT server hostname (required)
-p, --mqtt-port: MQTT server port (default: 1883)
-u, --mqtt-username: MQTT username
-w, --mqtt-password: MQTT password
-t, --mqtt-prefix: MQTT topic prefix (default: 'tigo')
Other Options
-n, --node-table: Node table storage path (default: './nodeTable.pickle')
-l, --log-level: Set logging level (choices: DEBUG, INFO, WARNING, ERROR, CRITICAL; default: INFO)
--dedup-window: Time window (in seconds) to deduplicate similar power reports (default: 5.0, 0 to disable)
Examples
Connect to a Tigo TAP via USB serial port:

Connect to a Tigo TAP via TCP (useful for ESP8266/ESP32 serial bridges):

Enable verbose logging:

How It Works
The bridge connects to the Tigo TAP hardware via serial port or TCP connection
It listens for data frames in Tigo's proprietary protocol
When power reports are received, they're parsed to extract voltage, current, temperature, etc.
This data is published to the MQTT broker with topics in the format: {prefix}/{device_address}
The bridge maintains a mapping between node IDs and MAC addresses in a persistent store
MQTT Data Format
Data is published as JSON with the following structure:

Credits and Acknowledgments
This project was created with the assistance of GitHub Copilot and draws heavily from the following sources:

kicomoco/tappipe - For initial protocol understanding and implementation ideas
willglynn/taptap - For the excellent protocol documentation, which provides an exceptional level of detail about the Tigo TAP protocol
License
This project is licensed under the MIT License - see the LICENSE file for details.