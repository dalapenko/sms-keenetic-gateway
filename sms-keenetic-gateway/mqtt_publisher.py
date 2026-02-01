"""
MQTT Publisher for SMS Keenetic Gateway
Publishes SMS and device status to MQTT broker with Home Assistant auto-discovery
"""

import json
import time
import logging
import threading
import os
from typing import Optional, Dict, Any
import paho.mqtt.client as mqtt
import concurrent.futures

logger = logging.getLogger(__name__)

# SMS counter persistence file
SMS_COUNTER_FILE = '/data/sms_counter.json'

class SMSCounter:
    """Tracks sent SMS count with persistent storage"""

    def __init__(self, counter_file: str = SMS_COUNTER_FILE):
        self.counter_file = counter_file
        self.sent_count = 0
        self._load()

    def _load(self):
        """Load counter from JSON file"""
        try:
            if os.path.exists(self.counter_file):
                with open(self.counter_file, 'r') as f:
                    data = json.load(f)
                    self.sent_count = data.get('sent_count', 0)
                    logger.info(f"📊 Loaded SMS counter from file: {self.sent_count}")
            else:
                logger.info("📊 SMS counter file not found, starting from 0")
        except Exception as e:
            logger.error(f"Error loading SMS counter: {e}")
            self.sent_count = 0

    def _save(self):
        """Save counter to JSON file"""
        try:
            # Ensure /data directory exists
            os.makedirs(os.path.dirname(self.counter_file), exist_ok=True)

            data = {'sent_count': self.sent_count}
            with open(self.counter_file, 'w') as f:
                json.dump(data, f)
            logger.debug(f"📊 Saved SMS counter to file: {self.sent_count}")
        except Exception as e:
            logger.error(f"Error saving SMS counter: {e}")

    def increment(self):
        """Increment counter and save"""
        self.sent_count += 1
        self._save()
        return self.sent_count

    def reset(self):
        """Reset counter to 0"""
        self.sent_count = 0
        self._save()
        logger.info("📊 SMS counter reset to 0")
        return self.sent_count

    def get_count(self):
        """Get current count"""
        return self.sent_count

class DeviceConnectivityTracker:
    """Tracks Router connectivity status based on API communication"""

    def __init__(self, offline_timeout_seconds=900):  # 15 minutes default
        self.last_success_time = None
        self.consecutive_failures = 0
        self.last_error = None
        self.offline_timeout = offline_timeout_seconds
        self.total_operations = 0
        self.successful_operations = 0
        self.initial_check_done = False
        
    def record_success(self):
        """Record successful operation"""
        self.last_success_time = time.time()

        if self.consecutive_failures > 0:
            logger.info(f"✅ Device recovery: resetting consecutive_failures from {self.consecutive_failures} to 0")
            self.consecutive_failures = 0

        self.last_error = None
        self.total_operations += 1
        self.successful_operations += 1
        self.initial_check_done = True
        
    def record_failure(self, error_message=None):
        """Record failed operation"""
        self.consecutive_failures += 1
        self.last_error = str(error_message) if error_message else "Communication failed"
        self.total_operations += 1
        
    def get_status(self):
        """Get current device connectivity status"""
        if not self.initial_check_done:
            return "offline"

        if self.last_success_time is None:
            return "offline"

        if self.consecutive_failures >= 3: # Increased tolerance slightly for network
            return "offline"

        time_since_last_success = time.time() - self.last_success_time
        if time_since_last_success > self.offline_timeout:
            return "offline"

        return "online"
            
    def get_status_data(self):
        """Get detailed status information"""
        status = self.get_status()
        
        data = {
            "status": status,
            "consecutive_failures": self.consecutive_failures,
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "last_error": self.last_error
        }
        
        if self.last_success_time:
            data["last_seen"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.last_success_time))
            data["seconds_since_last_success"] = int(time.time() - self.last_success_time)
        else:
            data["last_seen"] = None
            data["seconds_since_last_success"] = None
            
        return data

class MQTTPublisher:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client: Optional[mqtt.Client] = None
        self.connected = False
        self.disconnecting = False
        self.topic_prefix = config.get('mqtt_topic_prefix', 'homeassistant/sensor/sms_keenetic_gateway')
        self.availability_topic = f"{self.topic_prefix}/availability"
        self.keenetic_client = None
        self.client_lock = threading.Lock() # Serialize access
        self.current_phone_number = ""
        self.current_message_text = ""
        self.device_tracker = DeviceConnectivityTracker()
        self.sms_counter = SMSCounter()

        if config.get('mqtt_enabled', False):
            self._setup_client()
    
    def set_keenetic_client(self, client):
        """Set Keenetic client for SMS sending"""
        self.keenetic_client = client
        logger.info("Keenetic client set for MQTT SMS sending")
    
    def _setup_client(self):
        """Setup MQTT client"""
        try:
            import socket
            client_id = f"sms_keenetic_gateway_{socket.gethostname()}"
            self.client = mqtt.Client(client_id=client_id, clean_session=True)

            username = self.config.get('mqtt_username', '')
            password = self.config.get('mqtt_password', '')

            if username is None:
                username = ''
            username = str(username).strip()

            if username and username != '':
                self.client.username_pw_set(username, password)
                logger.info(f"MQTT: Using authentication with username: '{username}'")
            else:
                logger.info(f"MQTT: Connecting without authentication")
            
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_publish = self._on_publish
            self.client.on_message = self._on_message

            self.client.will_set(self.availability_topic, "offline", qos=1, retain=True)

            host = self.config.get('mqtt_host', 'core-mosquitto')
            port = self.config.get('mqtt_port', 1883)

            logger.info(f"Connecting to MQTT broker: {host}:{port}")
            self.client.connect(host, port, 60)
            self.client.loop_start()
            
        except Exception as e:
            logger.error(f"Failed to setup MQTT client: {e}")
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback for MQTT connection"""
        if rc == 0:
            self.connected = True
            logger.info("Connected to MQTT broker")

            self.client.publish(self.availability_topic, "online", qos=1, retain=True)

            self._publish_discovery_configs()
            
            # Subscribe to topics
            for topic in [
                f"{self.topic_prefix}/send",
                f"{self.topic_prefix}/send_button",
                f"{self.topic_prefix}/reset_counter_button",
                f"{self.topic_prefix}/delete_all_sms_button",
                f"{self.topic_prefix}/phone_number/set",
                f"{self.topic_prefix}/message_text/set",
                f"{self.topic_prefix}/phone_number/state",
                f"{self.topic_prefix}/message_text/state"
            ]:
                client.subscribe(topic)
                logger.info(f"Subscribed to: {topic}")
        else:
            logger.error(f"Failed to connect to MQTT broker: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback for MQTT disconnection"""
        self.connected = False
        logger.warning("Disconnected from MQTT broker")
    
    def _on_publish(self, client, userdata, mid):
        pass
    
    def _on_message(self, client, userdata, msg):
        """Callback for received MQTT messages"""
        try:
            topic = msg.topic
            payload = msg.payload.decode('utf-8')
            logger.info(f"Received MQTT message on topic {topic}: {payload}")

            send_topic = f"{self.topic_prefix}/send"
            button_topic = f"{self.topic_prefix}/send_button"
            reset_counter_topic = f"{self.topic_prefix}/reset_counter_button"
            delete_all_sms_topic = f"{self.topic_prefix}/delete_all_sms_button"
            phone_topic = f"{self.topic_prefix}/phone_number/set"
            message_topic = f"{self.topic_prefix}/message_text/set"
            phone_state_topic = f"{self.topic_prefix}/phone_number/state"
            message_state_topic = f"{self.topic_prefix}/message_text/state"

            if topic == send_topic:
                self._handle_sms_send_command(payload)
            elif topic == button_topic and payload == "PRESS":
                self._handle_button_sms_send()
            elif topic == reset_counter_topic and payload == "PRESS":
                self._handle_reset_counter()
            elif topic == delete_all_sms_topic and payload == "PRESS":
                self._handle_delete_all_sms()
            elif topic == phone_topic:
                self.current_phone_number = payload
                self._publish_phone_state(payload)
            elif topic == message_topic:
                self.current_message_text = payload
                self._publish_message_state(payload)
            elif topic == phone_state_topic:
                self.current_phone_number = payload
            elif topic == message_state_topic:
                self.current_message_text = payload

        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
            self._publish_error_status(msg.topic, str(e))
    
    def _handle_sms_send_command(self, payload):
        """Handle SMS send command from MQTT"""
        try:
            data = json.loads(payload)
            number = data.get('number')
            text = data.get('text')
            
            if not number or not text:
                logger.error("SMS send command missing required fields")
                return

            logger.info(f"Processing SMS send command: {number} -> {text}")

            if self.keenetic_client:
                self._send_sms_via_keenetic(number, text)
            else:
                logger.error("Keenetic client not available for SMS sending")
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in SMS send command: {e}")
        except Exception as e:
            logger.error(f"Error handling SMS send command: {e}")
    
    def _send_sms_via_keenetic(self, number, text):
        """Send SMS using Keenetic client"""
        try:
            # Support multiple recipients
            recipients = [n.strip() for n in number.split(',') if n.strip()]
            
            for recipient in recipients:
                self.track_client_operation("SendSMS", self.keenetic_client.send_sms, recipient, text)
                logger.info(f"SMS sent successfully to {recipient}")
                self.sms_counter.increment()
                
            self.publish_sms_counter()
            logger.info(f"📊 SMS counter: {self.sms_counter.get_count()}")

            # Publish confirmation
            if self.connected:
                status_topic = f"{self.topic_prefix}/send_status"
                status_data = {
                    "status": "success",
                    "number": number,
                    "text": text,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                self.client.publish(status_topic, json.dumps(status_data), retain=False)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to send SMS: {error_msg}")
            
            if self.connected:
                status_topic = f"{self.topic_prefix}/send_status"
                status_data = {
                    "status": "error",
                    "error": error_msg,
                    "number": number,
                    "text": text,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                self.client.publish(status_topic, json.dumps(status_data), retain=False)
    
    def _handle_button_sms_send(self):
        """Handle SMS send when button is pressed"""
        if not self.current_phone_number.strip() or not self.current_message_text.strip():
            logger.warning("Button pressed but fields empty")
            if self.connected:
                status_topic = f"{self.topic_prefix}/send_status"
                status_data = {
                    "status": "missing_fields",
                    "message": "Please fill in phone number and message text first",
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                self.client.publish(status_topic, json.dumps(status_data), retain=False)
            return

        if self.keenetic_client:
            self._send_sms_via_keenetic(self.current_phone_number, self.current_message_text)
            self._clear_text_fields()
        else:
            logger.error("Keenetic client not available")
            self._clear_text_fields()
    
    def _handle_reset_counter(self):
        """Handle reset counter button"""
        logger.info("🔄 Reset counter button pressed")
        self.sms_counter.reset()
        self.publish_sms_counter()

    def _handle_delete_all_sms(self):
        """Handle delete all SMS button"""
        logger.info("🗑️ Delete all SMS button pressed")
        try:
            if self.keenetic_client:
                count = self.track_client_operation("deleteAllSms", self.keenetic_client.delete_all_sms)
                
                if self.connected:
                    status_topic = f"{self.topic_prefix}/delete_sms_status"
                    status_data = {
                        "status": "success",
                        "deleted_count": count,
                        "message": f"Deleted {count} SMS messages",
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    self.client.publish(status_topic, json.dumps(status_data), retain=False)
            else:
                logger.error("Keenetic client not available")
        except Exception as e:
            logger.error(f"Error deleting all SMS: {e}")
            if self.connected:
                status_topic = f"{self.topic_prefix}/delete_sms_status"
                status_data = {
                    "status": "error",
                    "error": str(e),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                self.client.publish(status_topic, json.dumps(status_data), retain=False)

    def _clear_text_fields(self):
        """Clear text fields"""
        self.current_phone_number = ""
        self.current_message_text = ""
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/phone_number/state", "", retain=True, qos=1)
            self.client.publish(f"{self.topic_prefix}/message_text/state", "", retain=True, qos=1)
    
    def _publish_phone_state(self, value):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/phone_number/state", value, retain=True, qos=1)

    def _publish_message_state(self, value):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/message_text/state", value, retain=True, qos=1)
            
    def _publish_error_status(self, source, error):
        if self.connected:
            status_topic = f"{self.topic_prefix}/send_status"
            status_data = {
                "status": "error",
                "message": f"Command processing failed: {error}",
                "topic": source,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
            self.client.publish(status_topic, json.dumps(status_data), retain=False)
    
    def _publish_discovery_configs(self):
        """Publish Home Assistant auto-discovery configurations"""
        if not self.connected:
            return

        device_config = {
            "identifiers": ["sms_keenetic_gateway"],
            "name": "SMS Gateway",
            "model": "Keenetic Router",
            "manufacturer": "Keenetic Gateway"
        }

        availability_config = {
            "availability_topic": self.availability_topic,
            "payload_available": "online",
            "payload_not_available": "offline"
        }

        # Define all sensors and buttons (excluding Flash SMS)
        discoveries = [
            ("sensor/sms_keenetic_gateway_signal/config", {
                "name": "GSM Signal Strength", "unique_id": "sms_keenetic_gateway_signal",
                "state_topic": f"{self.topic_prefix}/signal/state",
                "value_template": "{{ value_json.SignalPercent }}", "unit_of_measurement": "%",
                "icon": "mdi:signal-cellular-3", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_network/config", {
                "name": "GSM Network", "unique_id": "sms_keenetic_gateway_network",
                "state_topic": f"{self.topic_prefix}/network/state",
                "value_template": "{{ value_json.NetworkName }}",
                "icon": "mdi:network", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_last_sms/config", {
                "name": "Last SMS Received", "unique_id": "sms_keenetic_gateway_last_sms",
                "state_topic": f"{self.topic_prefix}/sms/state",
                "value_template": "{{ value_json.Text }}",
                "json_attributes_topic": f"{self.topic_prefix}/sms/state",
                "icon": "mdi:message-text", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_send_status/config", {
                "name": "SMS Send Status", "unique_id": "sms_keenetic_gateway_send_status",
                "state_topic": f"{self.topic_prefix}/send_status",
                "value_template": "{{ value_json.status }}",
                "json_attributes_topic": f"{self.topic_prefix}/send_status",
                "icon": "mdi:send", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_delete_status/config", {
                "name": "SMS Delete Status", "unique_id": "sms_keenetic_gateway_delete_status",
                "state_topic": f"{self.topic_prefix}/delete_sms_status",
                "value_template": "{{ value_json.status }}",
                "json_attributes_topic": f"{self.topic_prefix}/delete_sms_status",
                "icon": "mdi:delete-sweep", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_modem_status/config", {
                "name": "Modem Status", "unique_id": "sms_keenetic_gateway_modem_status",
                "state_topic": f"{self.topic_prefix}/device_status/state",
                "value_template": "{{ value_json.status }}",
                "json_attributes_topic": f"{self.topic_prefix}/device_status/state",
                "icon": "mdi:connection", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_sent_count/config", {
                "name": "SMS Sent Count", "unique_id": "sms_keenetic_gateway_sent_count",
                "state_topic": f"{self.topic_prefix}/sms_counter/state",
                "value_template": "{{ value_json.count }}",
                "icon": "mdi:counter", "state_class": "total_increasing", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_modem_imei/config", {
                "name": "Modem IMEI", "unique_id": "sms_keenetic_gateway_modem_imei",
                "state_topic": f"{self.topic_prefix}/modem_info/state",
                "value_template": "{{ value_json.IMEI }}",
                "icon": "mdi:identifier", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_modem_model/config", {
                "name": "Modem Model", "unique_id": "sms_keenetic_gateway_modem_model",
                "state_topic": f"{self.topic_prefix}/modem_info/state",
                "value_template": "{{ value_json.Manufacturer }} {{ value_json.Model }}",
                "icon": "mdi:cellphone", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_sim_imsi/config", {
                "name": "SIM IMSI", "unique_id": "sms_keenetic_gateway_sim_imsi",
                "state_topic": f"{self.topic_prefix}/sim_info/state",
                "value_template": "{{ value_json.IMSI }}",
                "icon": "mdi:sim", "device": device_config, **availability_config
            }),
            ("sensor/sms_keenetic_gateway_sms_capacity/config", {
                "name": "SMS Storage Used", "unique_id": "sms_keenetic_gateway_sms_capacity",
                "state_topic": f"{self.topic_prefix}/sms_capacity/state",
                "value_template": "{{ value_json.SIMUsed }}",
                "unit_of_measurement": "messages",
                "icon": "mdi:email-multiple", "device": device_config, **availability_config
            }),
            ("button/sms_keenetic_gateway_send_button/config", {
                "name": "Send SMS", "unique_id": "sms_keenetic_gateway_send_button",
                "command_topic": f"{self.topic_prefix}/send_button",
                "payload_press": "PRESS",
                "icon": "mdi:message-plus", "device": device_config, **availability_config
            }),
            ("button/sms_keenetic_gateway_reset_counter/config", {
                "name": "Reset SMS Counter", "unique_id": "sms_keenetic_gateway_reset_counter",
                "command_topic": f"{self.topic_prefix}/reset_counter_button",
                "payload_press": "PRESS",
                "icon": "mdi:restart", "device": device_config, **availability_config
            }),
            ("button/sms_keenetic_gateway_delete_all_sms/config", {
                "name": "Delete All SMS", "unique_id": "sms_keenetic_gateway_delete_all_sms",
                "command_topic": f"{self.topic_prefix}/delete_all_sms_button",
                "payload_press": "PRESS",
                "icon": "mdi:delete-sweep", "device": device_config, **availability_config
            }),
            ("text/sms_keenetic_gateway_phone_number/config", {
                "name": "Phone Number", "unique_id": "sms_keenetic_gateway_phone_number",
                "command_topic": f"{self.topic_prefix}/phone_number/set",
                "state_topic": f"{self.topic_prefix}/phone_number/state",
                "icon": "mdi:phone", "mode": "text", "pattern": r"^\+?[\d\s\-\(\),]*$",
                "device": device_config, **availability_config
            }),
            ("text/sms_keenetic_gateway_message_text/config", {
                "name": "Message Text", "unique_id": "sms_keenetic_gateway_message_text",
                "command_topic": f"{self.topic_prefix}/message_text/set",
                "state_topic": f"{self.topic_prefix}/message_text/state",
                "icon": "mdi:message-text", "mode": "text", "max": 255,
                "device": device_config, **availability_config
            })
        ]

        # Add cost sensor if needed
        sms_cost_per_message = self.config.get('sms_cost_per_message', 0.0)
        if sms_cost_per_message > 0:
            sms_cost_currency = self.config.get('sms_cost_currency', 'USD')
            discoveries.append(("sensor/sms_keenetic_gateway_total_cost/config", {
                "name": "SMS Total Cost", "unique_id": "sms_keenetic_gateway_total_cost",
                "state_topic": f"{self.topic_prefix}/sms_counter/state",
                "value_template": "{{ value_json.cost }}",
                "icon": "mdi:cash", "unit_of_measurement": sms_cost_currency,
                "state_class": "total", "device": device_config, **availability_config
            }))
        
        for suffix, config in discoveries:
            topic = f"homeassistant/{suffix}"
            self.client.publish(topic, json.dumps(config), retain=True, qos=1)
        
        logger.info("Published MQTT discovery configurations")
        self._publish_initial_states()

    def publish_signal_strength(self, signal_data):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/signal/state", json.dumps(signal_data), retain=True)

    def publish_network_info(self, network_data):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/network/state", json.dumps(network_data), retain=True)

    def publish_sms_received(self, sms_data):
        if self.connected:
            sms_data['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S')
            self.client.publish(f"{self.topic_prefix}/sms/state", json.dumps(sms_data), qos=1)

    def publish_device_status(self):
        status_data = self.device_tracker.get_status_data()
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/device_status/state", json.dumps(status_data), retain=True, qos=1)

    def publish_sms_counter(self):
        if self.connected:
            count = self.sms_counter.get_count()
            cost = count * self.config.get('sms_cost_per_message', 0.0)
            data = {"count": count, "cost": round(cost, 2)}
            self.client.publish(f"{self.topic_prefix}/sms_counter/state", json.dumps(data), retain=True)

    def publish_modem_info(self, modem_data):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/modem_info/state", json.dumps(modem_data), retain=True)

    def publish_sim_info(self, sim_data):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/sim_info/state", json.dumps(sim_data), retain=True)

    def publish_sms_capacity(self, capacity_data):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/sms_capacity/state", json.dumps(capacity_data), retain=True)

    def track_client_operation(self, operation_name, client_function, *args, **kwargs):
        """Execute client operation with connectivity tracking and timeout"""
        with self.client_lock:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(client_function, *args, **kwargs)
                try:
                    # Python timeout as safety net
                    result = future.result(timeout=60)
                    self.device_tracker.record_success()
                    self.publish_device_status()
                    return result
                except concurrent.futures.TimeoutError:
                    self.device_tracker.record_failure(f"{operation_name}: Timeout")
                    self.publish_device_status()
                    raise TimeoutError(f"{operation_name} timed out")
                except Exception as e:
                    self.device_tracker.record_failure(f"{operation_name}: {str(e)}")
                    self.publish_device_status()
                    raise

    def _publish_initial_states(self):
        if self.connected:
            self.client.publish(f"{self.topic_prefix}/phone_number/state", "", retain=True, qos=1)
            self.client.publish(f"{self.topic_prefix}/message_text/state", "", retain=True, qos=1)
            self.client.publish(f"{self.topic_prefix}/send_status", json.dumps({"status": "ready"}), retain=False)
            self.client.publish(f"{self.topic_prefix}/delete_sms_status", json.dumps({"status": "idle"}), retain=True)

    def publish_initial_states_with_client(self, client):
        if not self.connected: return
        try:
            self.publish_device_status()
            
            signal = self.track_client_operation("GetSignal", client.get_signal_quality)
            self.publish_signal_strength(signal)

            network = self.track_client_operation("GetNetwork", client.get_network_info)
            self.publish_network_info(network)

            self.publish_sms_counter()
            
            modem_info = self.track_client_operation("GetModemInfo", client.get_modem_info)
            self.publish_modem_info(modem_info)
            
            sim_info = {"IMSI": self.track_client_operation("GetIMSI", client.get_sim_imsi)}
            self.publish_sim_info(sim_info)
            
            # Skip empty capacity update if failed
            try:
                capacity = self.track_client_operation("GetCapacity", client.get_sms_capacity)
                self.publish_sms_capacity(capacity)
            except:
                pass

        except Exception as e:
            logger.error(f"Error publishing initial states: {e}")

    def start_sms_monitoring(self, client, check_interval=10):
        if not self.connected: return
        
        def _sms_monitor_loop():
            logger.info(f"📱 Started SMS monitoring (check every {check_interval}s)")
            
            last_processed_sms_time = ""

            while self.connected and not self.disconnecting:
                from support import retrieve_all_sms, delete_sms
                try:
                    all_sms = self.track_client_operation("retrieveAllSms", retrieve_all_sms, client)
                    
                    if all_sms:
                        # Filter valid SMS and sort by date descending (newest first)
                        valid_sms = [s for s in all_sms if isinstance(s, dict) and s.get('Date')]
                        valid_sms.sort(key=lambda x: x.get('Date', ''), reverse=True)
                        
                        if valid_sms:
                            newest_sms = valid_sms[0]
                            # Publish the most recent SMS (retain=True so it sticks)
                            # Only publish if it's different/newer than what we last saw to reduce traffic
                            if newest_sms.get('Date') != last_processed_sms_time:
                                self.publish_sms_received(newest_sms)
                                last_processed_sms_time = newest_sms.get('Date')
                                logger.info(f"Updated Last SMS sensor: {newest_sms.get('Date')} from {newest_sms.get('Number')}")

                            # Process Read messages for auto-delete
                            for sms in valid_sms:
                                if sms.get('State') == 'Read' and self.config.get('auto_delete_read_sms', False):
                                    self.track_client_operation("deleteSms", delete_sms, client, sms)
                                    logger.info(f"Auto-deleted SMS from {sms.get('Number')}")
                    
                except Exception as e:
                    logger.warning(f"SMS monitoring error: {e}")
                
                time.sleep(check_interval)

        thread = threading.Thread(target=_sms_monitor_loop, daemon=True)
        thread.start()

    def publish_status_periodic(self, client, interval=60):
        if not self.connected: return
        
        def _publish_loop():
            while self.connected and not self.disconnecting:
                try:
                    signal = self.track_client_operation("GetSignal", client.get_signal_quality)
                    self.publish_signal_strength(signal)
                    
                    network = self.track_client_operation("GetNetwork", client.get_network_info)
                    self.publish_network_info(network)
                except:
                    pass
                time.sleep(interval)
        
        if self.config.get('mqtt_enabled', False):
            thread = threading.Thread(target=_publish_loop, daemon=True)
            thread.start()

    def disconnect(self):
        if self.disconnecting: return
        self.disconnecting = True
        if self.client and self.connected:
            self.client.publish(self.availability_topic, "offline", qos=1, retain=True)
            self.client.loop_stop()
            self.client.disconnect()
            self.connected = False
            logger.info("Disconnected from MQTT broker")
