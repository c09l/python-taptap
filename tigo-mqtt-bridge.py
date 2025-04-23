#!/usr/bin/env python3
# filepath: /home/c09l/tigo-mqtt-bridge.py

import argparse
import logging
import socket
import sys
import time
import json
import os
import pickle
import signal
from collections import defaultdict
from enum import Enum
from typing import Dict, List, Optional, BinaryIO

# Try importing required modules
try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Error: paho-mqtt module not installed. Run: pip install paho-mqtt")
    sys.exit(1)

try:
    import serial
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False
    print("Warning: Serial port support not available. Run: pip install pyserial")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Helper functions
def stringhex(bytes_data, delimiter=' '):
    """Convert bytes to hex string with specified delimiter"""
    return delimiter.join("{0:02x}".format(x) for x in bytes_data)

class PacketType(Enum):
    STRING_RESPONSE = 0x07
    POWER_REPORT = 0x31
    TOPOLOGY_REPORT = 0x09
    STRING_REQUEST = 0x06
    NODE_TABLE_REQUEST = 0x26
    NODE_TABLE_RESPONSE = 0x27
    PV_CONFIG_REQUEST = 0x13
    PV_CONFIG_RESPONSE = 0x18
    BROADCAST = 0x22
    BROADCAST_ACK = 0x23
    GATEWAY_RADIO_CONFIG_REQUEST = 0x0D
    GATEWAY_RADIO_CONFIG_RESPONSE = 0x0E
    NETWORK_STATUS_REQUEST = 0x2E
    LONG_NETWORK_STATUS_REQUEST = 0x2D
    NETWORK_STATUS_RESPONSE = 0x2F
    UNKNOWN_0x41 = 0x41

class GatewayFrameType:
    # Receive related
    RECEIVE_REQUEST = bytes([0x01, 0x48])
    RECEIVE_RESPONSE = bytes([0x01, 0x49])
    
    # Command related
    COMMAND_REQUEST = bytes([0x0B, 0x0F])
    COMMAND_RESPONSE = bytes([0x0B, 0x10])
    
    # Ping related
    PING_REQUEST = bytes([0x0B, 0x00])
    PING_RESPONSE = bytes([0x0B, 0x01])
    
    # Enumeration related
    ENUMERATION_START_REQUEST = bytes([0x00, 0x14])
    ENUMERATION_START_RESPONSE = bytes([0x00, 0x15])
    ENUMERATION_REQUEST = bytes([0x00, 0x38])
    ENUMERATION_RESPONSE = bytes([0x00, 0x39])
    ASSIGN_GATEWAY_ID_REQUEST = bytes([0x00, 0x3C])
    ASSIGN_GATEWAY_ID_RESPONSE = bytes([0x00, 0x3D])
    IDENTIFY_REQUEST = bytes([0x00, 0x3A])
    IDENTIFY_RESPONSE = bytes([0x00, 0x3B])
    
    # Version related
    VERSION_REQUEST = bytes([0x00, 0x0A])
    VERSION_RESPONSE = bytes([0x00, 0x0B])
    
    # Enumeration end
    ENUMERATION_END_REQUEST = bytes([0x0E, 0x02])
    ENUMERATION_END_RESPONSE = bytes([0x00, 0x06])

class Connection:
    """Base class for physical connections"""
    def read(self, buffer_size: int) -> bytes:
        raise NotImplementedError

class SerialConnection(Connection):
    def __init__(self, port_name, baudrate=38400):
        if not SERIAL_AVAILABLE:
            raise Exception("Serial port support not available")
        self.port = serial.Serial(port_name, baudrate=baudrate, timeout=1)
    
    def read(self, buffer_size):
        return self.port.read(buffer_size)
    
    def close(self):
        if hasattr(self, 'port') and self.port and self.port.is_open:
            self.port.close()

class TcpConnection(Connection):
    def __init__(self, hostname, port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((hostname, port))
        self.sock.settimeout(1)
    
    def read(self, buffer_size):
        return self.sock.recv(buffer_size)
    
    def close(self):
        if hasattr(self, 'sock'):
            self.sock.close()

class Frame:
    def __init__(self, data):
        self.data = data
        self.address = int.from_bytes(data[0:2], byteorder='big')
        self.is_from_gateway = (self.address & 0x8000) != 0
        self.gateway_id = self.address & 0x7FFF
        self.type = data[2:4] if len(data) >= 4 else None
        self.payload = data[4:-2] if len(data) >= 6 else None
        self.checksum = data[-2:] if len(data) >= 2 else None
    
    def __repr__(self):
        direction = "from" if self.is_from_gateway else "to"
        return f"Frame({direction} gateway {self.gateway_id:04x}, type={self.type.hex() if self.type else 'None'}, payload={len(self.payload) if self.payload else 0} bytes)"
    
    def getType(self):
        return self.type

class FrameReceiver:
    def __init__(self, sink):
        self.sink = sink
        self.buffer = bytearray()
        self.in_frame = False
        self.escape_next = False
        self.current_frame = bytearray()
        self.FRAME_START = bytes([0x7E, 0x07])
        self.FRAME_END = bytes([0x7E, 0x08])
        # Escape sequences mapping
        self.ESCAPE_MAP = {
            bytes([0x7E, 0x00]): bytes([0x7E]),
            bytes([0x7E, 0x01]): bytes([0x24]),
            bytes([0x7E, 0x02]): bytes([0x23]),
            bytes([0x7E, 0x03]): bytes([0x25]),
            bytes([0x7E, 0x04]): bytes([0xA4]),
            bytes([0x7E, 0x05]): bytes([0xA3]),
            bytes([0x7E, 0x06]): bytes([0xA5]),
        }
    
    def extend_from_slice(self, data):
        """Process incoming data and extract frames"""
        self.buffer.extend(data)
        
        # Process buffer until no more complete frames
        while True:
            # Look for frame start
            start_idx = -1
            for i in range(len(self.buffer) - 1):
                if self.buffer[i:i+2] == self.FRAME_START:
                    start_idx = i
                    break
            
            if start_idx == -1:
                # No start marker found, keep bytes and wait for more
                return
            
            # Found start, look for end marker
            end_idx = -1
            for i in range(start_idx + 2, len(self.buffer) - 1):
                if self.buffer[i:i+2] == self.FRAME_END:
                    end_idx = i
                    break
            
            if end_idx == -1:
                # Start found but no end, wait for more data
                return
            
            # Extract frame data and unescape it
            frame_data = self.buffer[start_idx+2:end_idx]
            unescaped_data = self.unescape_frame(frame_data)
            
            # Process the frame if it's valid
            if len(unescaped_data) >= 4:  # At minimum: address(2) + type(2)
                # Verify checksum (last 2 bytes)
                frame_body = unescaped_data[:-2]
                checksum = unescaped_data[-2:]
                if self.verify_checksum(frame_body, checksum):
                    self.sink.frame(Frame(unescaped_data))
                else:
                    logger.warning(f"Invalid checksum: {frame_body.hex()} | {checksum.hex()}")
            
            # Remove processed frame from buffer
            self.buffer = self.buffer[end_idx+2:]
    
    def unescape_frame(self, data):
        """Unescape frame data according to protocol rules"""
        result = bytearray()
        i = 0
        while i < len(data):
            # Check for escape sequences
            if i < len(data) - 1 and data[i] == 0x7E:
                escape_seq = bytes([data[i], data[i+1]])
                if escape_seq in self.ESCAPE_MAP:
                    result.extend(self.ESCAPE_MAP[escape_seq])
                    i += 2
                    continue
            
            # Regular byte
            result.append(data[i])
            i += 1
        
        return result
    
    def verify_checksum(self, data, checksum):
        """Verify CRC-16/CCITT checksum with initial value 0x8408"""
        calculated = self.calculate_crc(data)
        expected = int.from_bytes(checksum, byteorder='little')
        return calculated == expected
    
    def calculate_crc(self, data):
        """Calculate CRC-16/CCITT with initial value 0x8408"""
        crc = 0x8408  # Initial value
        
        # CRC-16/CCITT-FALSE algorithm 
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0x8408
                else:
                    crc >>= 1
        
        return crc

class LongAddress:
    def __init__(self, bytes_data):
        self.bytes = bytes_data
    
    def __repr__(self):
        return f"LongAddress({self.bytes.hex()})"

class NodeID:
    def __init__(self, id_value):
        self.value = id_value
    
    def __repr__(self):
        return f"NodeID({self.value})"

class PowerReport:
    def __init__(self, node_id=None, voltage_in=None, voltage_out=None, 
                 current=None, duty_cycle=None, temperature=None, 
                 rssi=None, slot=None):
        self.node_id = node_id
        self.voltage_in = voltage_in
        self.voltage_out = voltage_out
        self.current = current
        self.duty_cycle = duty_cycle
        self.temperature = temperature
        self.rssi = rssi
        self.slot = slot
    
    def __repr__(self):
        return f"PowerReport(V={self.voltage_in:.1f}V, I={self.current:.3f}A, P={self.voltage_in * self.current:.2f}W, T={self.temperature:.1f}°C)"
    
    def to_dict(self):
        """Convert to dictionary for MQTT publishing"""
        return {
            "NodeID": self.node_id.value if self.node_id else None,
            "VIN": round(self.voltage_in, 2) if self.voltage_in is not None else None,
            "VOUT": round(self.voltage_out, 2) if self.voltage_out is not None else None,
            "DUTY": round(self.duty_cycle, 2) if self.duty_cycle is not None else None,
            "AMPSIN": round(self.current, 3) if self.current is not None else None,
            "TEMP": round(self.temperature, 1) if self.temperature is not None else None,
            "RSSI": self.rssi,
            "SLOT": self.slot,
            "POWER": round(self.voltage_in * self.current, 2) if self.voltage_in is not None and self.current is not None else None
        }

class MQTTBridge:
    """Bridge between Tigo TAP and MQTT"""
    
    def __init__(self, args):
        self.args = args
        self.mqtt_client = None
        self.connection = None
        self.node_table = {}
        self.running = True
        self.receiver = None
        self.MAX_BUFFER_SIZE = 1024 * 1024  # 1MB max buffer
        
        # Add deduplication tracking
        self.last_reports = {}  # For tracking recent reports by node
        self.dedup_window = args.dedup_window  # Time window (seconds) to deduplicate reports
        
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Ensure node_table directory exists
        os.makedirs(os.path.dirname(os.path.abspath(self.args.node_table)), exist_ok=True)
    
    def signal_handler(self, sig, frame):
        """Handle shutdown signals"""
        logger.info("Shutdown signal received, exiting gracefully...")
        self.running = False
    
    def load_node_table(self):
        """Load node table from pickle file"""
        try:
            with open(self.args.node_table, 'rb') as handle:
                node_table = pickle.load(handle)
            logger.info("Loaded Node Table")
            return node_table
        except FileNotFoundError:
            logger.warning(f"Node table file {self.args.node_table} not found, creating new table")
            return {}
        except Exception as e:
            logger.error(f"Failed to load node table: {e}")
            return {}
    
    def save_node_table(self):
        """Save node table to pickle file"""
        try:
            with open(self.args.node_table, 'wb') as handle:
                pickle.dump(self.node_table, handle, protocol=pickle.HIGHEST_PROTOCOL)
            logger.info(f"Node table saved to {self.args.node_table}")
        except Exception as e:
            logger.error(f"Failed to save node table: {e}")
    
    def node_table_ascii(self):
        """Format node table for display"""
        result = "----------------------------------\n"
        result += "| NODE | ADDRESS                 |\n"
        for node_id, address in self.node_table.items():
            result += f"| {node_id:04} | {stringhex(address, ':')} |\n"
        result += "----------------------------------\n"
        return result
    
    def setup(self):
        """Set up connections and resources"""
        # Load node table
        self.node_table = self.load_node_table()
        
        # Setup connections
        if not self.setup_connection():
            logger.error("Failed to set up connection")
            return False
        
        if not self.setup_mqtt():
            logger.error("Failed to set up MQTT")
            return False
        
        # Create receiver
        self.receiver = MQTTBridgeSink(self)
        
        return True
    
    def setup_connection(self):
        """Set up physical connection (serial or TCP)"""
        try:
            if hasattr(self.args, 'serial') and self.args.serial:
                self.connection = SerialConnection(self.args.serial, self.args.baud_rate)
                logger.info(f"Connected to serial port {self.args.serial}")
                return True
            elif hasattr(self.args, 'tcp') and self.args.tcp:
                self.connection = TcpConnection(self.args.tcp, self.args.port)
                logger.info(f"Connected to TCP {self.args.tcp}:{self.args.port}")
                return True
            else:
                logger.error("No connection source specified")
                return False
        except Exception as e:
            logger.error(f"Failed to set up connection: {e}")
            return False
    
    def setup_mqtt(self):
        """Set up MQTT connection with retry"""
        max_retries = 5
        retry_count = 0
        
        while retry_count < max_retries and self.running:
            try:
                # Use the constructor without specifying protocol version
                self.mqtt_client = mqtt.Client(client_id="tigo-bridge")  # Remove protocol parameter
                
                # Set callbacks
                self.mqtt_client.on_connect = self.on_mqtt_connect
                self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
                
                # Set credentials if provided
                if self.args.mqtt_username and self.args.mqtt_password:
                    self.mqtt_client.username_pw_set(self.args.mqtt_username, self.args.mqtt_password)
                
                # Connect with shorter keepalive
                self.mqtt_client.connect(self.args.mqtt_server, self.args.mqtt_port, keepalive=30)
                self.mqtt_client.loop_start()
                return True
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"Failed to connect to MQTT broker: {e}")
                    return False
                logger.warning(f"MQTT connection attempt {retry_count} failed, retrying in 5 seconds...")
                time.sleep(5)
        
        return False
    
    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Callback for MQTT connection"""
        rc_codes = {
            0: "Connection successful",
            1: "Connection refused - incorrect protocol version",
            2: "Connection refused - invalid client identifier",
            3: "Connection refused - server unavailable",
            4: "Connection refused - bad username or password",
            5: "Connection refused - not authorized"
        }
        
        if rc == 0:
            logger.info(f"Connected to MQTT broker at {self.args.mqtt_server}:{self.args.mqtt_port}")
        else:
            error_msg = rc_codes.get(rc, f"Unknown error code: {rc}")
            logger.error(f"Failed to connect to MQTT broker: {error_msg}")
    
    def on_mqtt_disconnect(self, client, userdata, rc):
        """Callback for MQTT disconnection"""
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection (code {rc}), will auto-reconnect")
        else:
            logger.info("Clean MQTT disconnect")
    
    def publish_power_report(self, gateway_id, node_id, report):
        """Publish power report to MQTT with modified deduplication"""
        if not self.mqtt_client:
            return
        
        # Create a unique key for this node
        node_key = f"{gateway_id}-{node_id.value}"
        current_time = time.time()
        
        # Skip deduplication if disabled
        if self.dedup_window <= 0:
            # Existing code for no deduplication...
            return
        
        # Modified deduplication logic:
        # 1. Always allow updates with a new slot number
        # 2. Only deduplicate within the same slot
        
        should_publish = True
        
        if node_key in self.last_reports:
            last_time, last_slot, last_values = self.last_reports[node_key]
            
            # If within deduplication window AND same slot number
            if (current_time - last_time < self.dedup_window and 
                report.slot == last_slot):
                
                # Only deduplicate if values are very similar
                if (abs(report.voltage_in - last_values['vin']) < 0.2 and
                    abs(report.current - last_values['current']) < 0.05 and
                    abs(report.temperature - last_values['temp']) < 0.5):
                    
                    logger.debug(f"Skipping duplicate report for node {node_id.value} (same slot: {report.slot})")
                    should_publish = False
        
        # Store this report's data
        self.last_reports[node_key] = (
            current_time,
            report.slot,  # Save the slot number
            {'vin': report.voltage_in, 'current': report.current, 'temp': report.temperature}
        )
        
        if should_publish:
            # Format address for topic
            if node_id.value in self.node_table:
                address = self.node_table[node_id.value]
                address_str = stringhex(address, ':')
            else:
                address_str = f"unknown-{node_id.value}"
            
            # Create payload with all available data
            payload = report.to_dict()
            payload["Address"] = address_str
            
            # Handle gateway_id correctly
            if hasattr(gateway_id, 'gateway_id'):
                payload["GatewayID"] = gateway_id.gateway_id
            else:
                payload["GatewayID"] = gateway_id
                
            payload["Timestamp"] = current_time
            
            # Publish to MQTT
            topic = f"{self.args.mqtt_prefix}/{address_str}"
            self.mqtt_client.publish(topic, json.dumps(payload), qos=0, retain=True)
            logger.info(f"Published power report for node {node_id.value}: {report}")
    
    def process_topology_report(self, gateway_id, node_id, address):
        """Process topology report to update node table"""
        # Debug logging
        logger.debug(f"Processing topology report: gateway_id={gateway_id}, node_id={node_id}, address_type={type(address)}")
        
        if not isinstance(address, bytes):
            # Convert LongAddress to bytes if needed
            if hasattr(address, 'bytes'):
                address = address.bytes
            else:
                logger.warning(f"Couldn't process topology report: invalid address format")
                return
                
        self.node_table[node_id.value] = address
        logger.info(f"Node Table Updated: Node {node_id.value} -> {stringhex(address, ':')}")
        self.save_node_table()
    
    def run(self):
        """Main execution loop"""
        if not self.connection:
            logger.error("No connection available")
            return False
            
        frame_receiver = FrameReceiver(self.receiver)
        
        logger.info("Starting main processing loop")
        
        while self.running:
            try:
                # Read from connection
                data = self.connection.read(1024)
                if data:
                    frame_receiver.extend_from_slice(data)
                else:
                    # Small sleep when no data to avoid CPU spinning
                    time.sleep(0.01)
                
                # Small yield to allow MQTT processing
                time.sleep(0.001)
                    
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(1)
        
        # Clean up resources
        self.cleanup()
        return True
    
    def cleanup(self):
        """Clean up resources before exit"""
        logger.info("Cleaning up resources")
        
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except:
                pass
                
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
                
        logger.info("Cleanup complete")

class MQTTBridgeSink:
    """Sink that processes frames and publishes to MQTT"""
    def __init__(self, bridge):
        self.bridge = bridge
    
    def frame(self, frame):
        """Process a complete frame"""
        try:
            gateway_id = frame.gateway_id
            
            # Only process frames from gateway
            if not frame.is_from_gateway:
                return
                
            # Handle frame based on type
            if frame.type == GatewayFrameType.RECEIVE_RESPONSE:
                self._handle_receive_response(frame, gateway_id)
            
        except Exception as e:
            logger.error(f"Error processing frame: {e}")
    
    def _handle_receive_response(self, frame, gateway_id):
        """Process a receive response frame"""
        if not frame.payload or len(frame.payload) < 3:
            return
            
        # Log the entire payload for debugging
        logger.debug(f"Receive response payload: {frame.payload.hex()}")
        
        payload = frame.payload
        status_type = payload[0:2]
        offset = 2
        
        # Skip status fields based on status type
        if status_type == bytes([0x00, 0xE0]):
            offset += 7  # Full status
        elif status_type == bytes([0x00, 0xFE]):
            offset += 1  # Minimal with Rx buffers
        elif status_type == bytes([0x00, 0xEE]):
            offset += 2  # Includes packet high
        elif status_type == bytes([0x00, 0xFF]):
            pass  # Most minimal status
        else:
            return
        
        # Skip slot counter
        offset += 3
        
        # Process received packets if any
        while offset + 6 <= len(payload):
            # Parse packet header
            packet_type = payload[offset]
            offset += 1
            
            if offset + 2 > len(payload):
                break
            
            node_id_value = int.from_bytes(payload[offset:offset+2], byteorder='big')
            node_id = NodeID(node_id_value)
            offset += 2
            
            # Skip short address and DSN
            offset += 3
            
            # Get data length
            data_length = payload[offset]
            offset += 1
            
            if offset + data_length > len(payload):
                break
                
            packet_data = payload[offset:offset+data_length]
            offset += data_length
            
            # Process packet by type
            try:
                if packet_type == PacketType.POWER_REPORT.value:
                    self._handle_power_report(node_id, packet_data, gateway_id)
                elif packet_type == PacketType.TOPOLOGY_REPORT.value:
                    self._handle_topology_report(node_id, packet_data, gateway_id)
            except Exception as e:
                logger.error(f"Error processing packet type {packet_type}: {e}")
    
    def _handle_power_report(self, node_id, data, gateway_id):
        """Process a power report packet using bit-level parsing based on protocol spec"""
        # Debug raw data
        logger.debug(f"Raw power report data ({len(data)} bytes): {data.hex()}")
        
        # Check minimum length needed for basic parsing
        if len(data) < 12:  # Minimum size for essential fields
            logger.warning(f"Power report too short: {len(data)} bytes")
            return
            
        try:
            # Bit-packed fields parsing according to protocol specification
            # Voltage in (first 1.5 bytes): 12 bits * 0.05V
            vin_raw = ((data[0] << 4) | ((data[1] & 0xF0) >> 4))
            vin = vin_raw * 0.05
            
            # Voltage out (next 1.5 bytes): 12 bits * 0.10V
            vout_raw = (((data[1] & 0x0F) << 8) | data[2])
            vout = vout_raw * 0.10
            
            # DC-DC duty cycle (next byte): 8 bits, raw percentage 
            duty_cycle = data[3] / 255.0 * 100.0
            
            # Current in (next 1.5 bytes): 12 bits * 0.005A
            current_raw = ((data[4] << 4) | ((data[5] & 0xF0) >> 4))
            current = current_raw * 0.005
            
            # Temperature (next 1.5 bytes): 12 bits * 0.1°C
            temp_raw = (((data[5] & 0x0F) << 8) | data[6])
            temperature = temp_raw * 0.1
            
            # Skip 3 unknown bytes
            
            # Slot counter (next 2 bytes)
            slot_counter_value = int.from_bytes(data[10:12], byteorder='big') if len(data) >= 12 else None
            
            # RSSI (last byte)
            rssi = data[12] if len(data) >= 13 else None
            
            # Log the parsed values
            logger.info(f"Parsed power report: NodeID={node_id.value}, " +
                        f"VIN={vin:.2f}V, VOUT={vout:.2f}V, " + 
                        f"I={current:.3f}A, T={temperature:.1f}°C, RSSI={rssi}")
            
            # Create power report
            report = PowerReport(
                node_id=node_id,
                voltage_in=vin,
                voltage_out=vout,
                current=current,
                duty_cycle=duty_cycle,
                temperature=temperature,
                rssi=rssi,
                slot=slot_counter_value
            )
            
            # Publish to MQTT
            self.bridge.publish_power_report(gateway_id, node_id, report)
            
        except Exception as e:
            logger.error(f"Error parsing power report: {e}", exc_info=True)
    
    def _handle_topology_report(self, node_id, data, gateway_id):
        """Process a topology report packet"""
        if len(data) < 16:
            return
            
        try:
            # Extract long address (MAC)
            long_address = data[8:16]
            
            # Update node table - FIX: Pass gateway_id directly, not frame
            self.bridge.process_topology_report(gateway_id, node_id, long_address)
            
        except Exception as e:
            logger.error(f"Error parsing topology report: {e}")

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Tigo TAP to MQTT Bridge",
    )
    
    connection_group = parser.add_mutually_exclusive_group(required=True)
    if SERIAL_AVAILABLE:
        connection_group.add_argument('-s', '--serial', help='Serial port device')
    connection_group.add_argument('--tcp', help='TCP hostname for serial-over-TCP')
    
    parser.add_argument('-b', '--baud-rate', type=int, default=38400, help='Serial baud rate')
    parser.add_argument('--port', type=int, default=7160, help='TCP port for serial-over-TCP')
    
    # MQTT parameters
    parser.add_argument('-m', '--mqtt-server', required=True, help='MQTT server hostname')
    parser.add_argument('-p', '--mqtt-port', type=int, default=1883, help='MQTT server port')
    parser.add_argument('-u', '--mqtt-username', help='MQTT username')
    parser.add_argument('-w', '--mqtt-password', help='MQTT password')
    parser.add_argument('-t', '--mqtt-prefix', default='tigo', help='MQTT topic prefix')
    
    # Other parameters
    parser.add_argument('-n', '--node-table', default='./nodeTable.pickle', help='Node table storage path')
    parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        default='INFO', help='Set logging level')
    parser.add_argument('--dedup-window', type=float, default=5.0,
                        help='Time window (in seconds) to deduplicate similar power reports (0 to disable)')
    
    return parser.parse_args()

def main():
    """Main entry point"""
    args = parse_args()
    
    # Configure logging level
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    # Create and run the bridge
    bridge = MQTTBridge(args)
    if bridge.setup():
        bridge.run()
    else:
        logger.error("Failed to set up the bridge")
        sys.exit(1)

if __name__ == "__main__":
    main()