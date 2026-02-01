#!/usr/bin/env python3
"""
SMS Keenetic Gateway - Home Assistant Add-on
REST API SMS Gateway using Keenetic Router API
"""

import os
import json
import logging
import signal
import sys
from flask import Flask
from flask_httpauth import HTTPBasicAuth
from flask_restx import Api, Resource, fields, reqparse

# Import Keenetic support functions
from support import init_keenetic_client, retrieve_all_sms, delete_sms
from keenetic_client import KeeneticConnectionError, KeeneticSMSError
from mqtt_publisher import MQTTPublisher

# Configure logging with timestamp
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)

# Suppress Flask development server warnings
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

# Monkey-patch click.echo to suppress Flask CLI startup messages
import click
_original_echo = click.echo
def _silent_echo(message=None, **kwargs):
    # Only suppress Flask's "Debug mode:" and "Serving Flask app" messages
    if message and isinstance(message, str):
        if 'Debug mode:' in message or 'Serving Flask app' in message:
            return
    _original_echo(message, **kwargs)
click.echo = _silent_echo

def load_version():
    """Load version from config.json"""
    try:
        # Try multiple possible locations
        possible_paths = [
            '/data/options.json',
            os.path.join(os.path.dirname(__file__), 'config.json'),
            '/config.json',
        ]

        # Try to read from addon info API first (most reliable in HA)
        try:
            import requests
            response = requests.get('http://supervisor/addons/self/info',
                                   headers={'Authorization': f'Bearer {os.environ.get("SUPERVISOR_TOKEN", "")}'},
                                   timeout=1)
            if response.status_code == 200:
                return response.json().get('data', {}).get('version', 'unknown')
        except:
            pass

        # Fallback: try to find config.json
        for config_path in possible_paths:
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    config_json = json.load(f)
                    version = config_json.get('version')
                    if version:
                        return version

        return "unknown"
    except Exception as e:
        logging.warning(f"Could not read version: {e}")
        return "unknown"

def load_ha_config():
    """Load Home Assistant add-on configuration"""
    config_path = '/data/options.json'
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return json.load(f)
    else:
        # Default values for testing outside HA
        return {
            'keenetic_host': '192.168.1.1',
            'keenetic_username': 'admin',
            'keenetic_password': '',
            'keenetic_modem_interface': 'UsbLte0',
            'keenetic_use_https': False,
            'port': 5000,
            'ssl': False,
            'username': 'admin',
            'password': 'password',
            'mqtt_enabled': True,
            'mqtt_host': 'core-mosquitto',
            'mqtt_port': 1883,
            'mqtt_username': '',
            'mqtt_password': '',
            'mqtt_topic_prefix': 'homeassistant/sensor/sms_keenetic_gateway',
            'sms_monitoring_enabled': True,
            'sms_check_interval': 60,
            'sms_cost_per_message': 0.0,
            'sms_cost_currency': 'USD',
            'auto_delete_read_sms': False
        }

# Load version and configuration
VERSION = load_version()
config = load_ha_config()

# Keenetic Config
keenetic_host = config.get('keenetic_host', '192.168.1.1')
keenetic_username = config.get('keenetic_username', 'admin')
keenetic_password = config.get('keenetic_password', '')
keenetic_interface = config.get('keenetic_modem_interface', 'UsbLte0')
keenetic_use_https = config.get('keenetic_use_https', False)

ssl = config.get('ssl', False)
port = config.get('port', 5000)
username = config.get('username', 'admin')
password = config.get('password', 'password')

# Initialize MQTT publisher FIRST
mqtt_publisher = MQTTPublisher(config)

# Publish OFFLINE status immediately on startup
if mqtt_publisher.connected:
    mqtt_publisher.device_tracker.initial_check_done = False  # Force offline
    mqtt_publisher.publish_device_status()
    logging.info("📡 Published initial OFFLINE status on startup")

# Initialize Keenetic Client
try:
    keenetic_client = init_keenetic_client(
        keenetic_host, keenetic_username, keenetic_password, 
        keenetic_interface, keenetic_use_https
    )
except Exception as e:
    logging.error(f"Failed to initialize Keenetic client: {e}")
    # We continue running so the API is available (maybe config is wrong and user will fix it)
    keenetic_client = None

# Set client for MQTT SMS sending
if keenetic_client:
    mqtt_publisher.set_keenetic_client(keenetic_client)

# Setup signal handlers for graceful shutdown
def signal_handler(signum, frame):
    """Handle shutdown signals (SIGTERM, SIGINT)"""
    logging.info(f"🛑 Received shutdown signal {signum}, publishing offline status...")
    try:
        mqtt_publisher.disconnect()
        logging.info("✅ MQTT disconnected successfully")
    except Exception as e:
        logging.error(f"❌ Error during MQTT disconnect: {e}")
    finally:
        sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)

# Register atexit handler as backup
import atexit
def cleanup():
    """Cleanup function called on normal exit"""
    logging.info("🧹 Cleanup: Publishing offline status...")
    try:
        mqtt_publisher.disconnect()
    except Exception as e:
        logging.error(f"Error during cleanup: {e}")

atexit.register(cleanup)

app = Flask(__name__)

# Create simple HTML page for Ingress
@app.route('/')
def home():
    """Simple status page for Home Assistant Ingress"""
    from flask import Response, request
    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>SMS Keenetic Gateway</title>
        <meta charset="utf-8">
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                margin: 0;
                padding: 40px 20px;
                background: #f5f5f5;
                text-align: center;
            }
            .container {
                max-width: 600px;
                margin: 0 auto;
                background: white;
                padding: 40px;
                border-radius: 15px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                margin-bottom: 20px;
                font-size: 2.2em;
            }
            .status {
                background: #e8f5e9;
                border: 2px solid #4caf50;
                padding: 20px;
                margin: 30px 0;
                border-radius: 10px;
                font-size: 1.2em;
            }
            .swagger-link {
                display: inline-block;
                padding: 15px 30px;
                background: #2196F3;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                margin: 20px 0;
                font-size: 1.1em;
                font-weight: bold;
            }
            .swagger-link:hover {
                background: #1976D2;
            }
            .info {
                background: #f0f8ff;
                border-left: 4px solid #2196F3;
                padding: 15px;
                margin: 20px 0;
                text-align: left;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📱 SMS Keenetic Gateway</h1>
            
            <div class="status">
                <strong>✅ Gateway is running properly</strong><br>
                Version: {VERSION}
            </div>
            
            <a href="http://''' + request.host.split(':')[0] + ''':5000/docs/" 
               class="swagger-link" target="_blank">
                📋 Open Swagger API Documentation
            </a>
            
            <div class="info">
                <strong>REST API Endpoints:</strong><br>
                • GET /status/signal - Signal strength<br>
                • GET /status/network - Network information<br>
                • POST /sms - Send SMS (requires authentication)<br>
                • GET /sms - Get all SMS (requires authentication)<br>
                <br>
                <strong>Authentication in Swagger UI:</strong><br>
                1. Click the "Authorize" button 🔒 in the top right corner<br>
                2. Enter Username and Password from add-on configuration<br>
                3. Click "Authorize" - now you can test protected endpoints
            </div>
        </div>
    </body>
    </html>
    '''
    return Response(html.replace('{VERSION}', VERSION), mimetype='text/html')

# Swagger UI Configuration
api = Api(
    app,
    version=VERSION,
    title='SMS Keenetic Gateway API',
    description='REST API for sending and receiving SMS messages via Keenetic Router.',
    doc='/docs/',  # Swagger UI on /docs/ path
    prefix='',
    authorizations={
        'basicAuth': {
            'type': 'basic',
            'in': 'header',
            'name': 'Authorization'
        }
    },
    security='basicAuth'
)

auth = HTTPBasicAuth()

@auth.verify_password
def verify(user, pwd):
    if not (user and pwd):
        return False
    return user == username and pwd == password

# API Models
sms_model = api.model('SMS', {
    'text': fields.String(required=True, description='SMS message text', example='Hello, how are you?'),
    'number': fields.String(required=True, description='Phone number (international format)', example='+420123456789'),
})

sms_response = api.model('SMS Response', {
    'Date': fields.String(description='Date and time received', example='2025-01-19 14:30:00'),
    'Number': fields.String(description='Sender phone number', example='+420123456789'),
    'State': fields.String(description='SMS state', example='UnRead'),
    'Text': fields.String(description='SMS message text', example='Hello World!')
})

signal_response = api.model('Signal Quality', {
    'SignalStrength': fields.Integer(description='Signal strength in dBm', example=-75),
    'SignalPercent': fields.Integer(description='Signal strength percentage', example=65),
    'BitErrorRate': fields.Integer(description='Bit error rate', example=0)
})

network_response = api.model('Network Info', {
    'NetworkName': fields.String(description='Network operator name', example='T-Mobile'),
    'State': fields.String(description='Network registration state', example='registered'),
    'NetworkCode': fields.String(description='Network operator code', example='23001'),
    'CID': fields.String(description='Cell ID', example='0A1B2C3D'),
    'LAC': fields.String(description='Location Area Code', example='1234')
})

send_response = api.model('Send Response', {
    'status': fields.Integer(description='HTTP status code', example=200),
    'message': fields.String(description='Response message', example='Sent')
})

reset_response = api.model('Reset Response', {
    'status': fields.Integer(description='HTTP status code', example=200),
    'message': fields.String(description='Reset message', example='Connection check done')
})

modem_info_response = api.model('Modem Info', {
    'IMEI': fields.String(description='Modem IMEI number', example='123456789012345'),
    'Manufacturer': fields.String(description='Modem manufacturer', example='Huawei'),
    'Model': fields.String(description='Modem model', example='E3372'),
    'Firmware': fields.String(description='Firmware version', example='22.323.62.00.143')
})

sim_info_response = api.model('SIM Info', {
    'IMSI': fields.String(description='SIM IMSI number', example='230011234567890')
})

sms_capacity_response = api.model('SMS Capacity', {
    'SIMUsed': fields.Integer(description='SMS count in SIM memory', example=5),
    'SIMSize': fields.Integer(description='SIM total capacity', example=50),
    'PhoneUsed': fields.Integer(description='SMS count in phone memory', example=0),
    'PhoneSize': fields.Integer(description='Phone memory capacity', example=0),
    'TemplatesUsed': fields.Integer(description='SMS templates used', example=0)
})

# API Namespaces
ns_sms = api.namespace('sms', description='SMS operations (requires authentication)')
ns_status = api.namespace('status', description='Device status and information (public)')

def check_client():
    """Ensure client is initialized"""
    if not keenetic_client:
        api.abort(503, "Keenetic client not initialized - check configuration")

@ns_sms.route('')
@ns_sms.doc('sms_operations')
class SmsCollection(Resource):
    @ns_sms.doc('get_all_sms')
    @ns_sms.marshal_list_with(sms_response, code=200)
    @ns_sms.doc(security='basicAuth')
    @auth.login_required
    def get(self):
        """Get all SMS messages from SIM/device memory"""
        check_client()
        try:
            # We track "retrieveAllSms" which maps to client.get_all_sms()
            all_sms = mqtt_publisher.track_client_operation("retrieveAllSms", retrieve_all_sms, keenetic_client)
            # Remove internal fields before returning
            list(map(lambda sms: sms.pop("Locations", None), all_sms))
            list(map(lambda sms: sms.pop("index", None), all_sms))
            list(map(lambda sms: sms.pop("original_index", None), all_sms))
            return all_sms
        except Exception as e:
            api.abort(500, str(e))

    @ns_sms.doc('send_sms')
    @ns_sms.expect(sms_model)
    @ns_sms.marshal_with(send_response, code=200)
    @ns_sms.doc(security='basicAuth')
    @auth.login_required
    def post(self):
        """Send SMS message(s)"""
        check_client()
        parser = reqparse.RequestParser()
        parser.add_argument('text', required=False, help='SMS message text')
        parser.add_argument('message', required=False, help='SMS message text (alias for text)')
        parser.add_argument('number', required=False, help='Phone number(s), comma separated')
        parser.add_argument('target', required=False, help='Phone number (alias for number)')
        
        args = parser.parse_args()
        
        sms_text = args.get('text') or args.get('message')
        if not sms_text:
            return {"status": 400, "message": "Missing required field: text or message"}, 400
        
        sms_number = args.get('number') or args.get('target')
        if not sms_number:
            return {"status": 400, "message": "Missing required field: number or target"}, 400

        # Send to multiple recipients
        numbers = [n.strip() for n in sms_number.split(',') if n.strip()]
        
        try:
            for num in numbers:
                # Use track_client_operation to handle errors and stats
                mqtt_publisher.track_client_operation("SendSMS", keenetic_client.send_sms, num, sms_text)
                
                # Increment counter
                mqtt_publisher.sms_counter.increment()
            
            mqtt_publisher.publish_sms_counter()
            return {"status": 200, "message": f"Sent to {len(numbers)} recipients"}, 200

        except KeeneticConnectionError as e:
            api.abort(503, f"Connection to router failed: {str(e)}")
        except KeeneticSMSError as e:
            api.abort(500, f"SMS Send failed: {str(e)}")
        except Exception as e:
            api.abort(500, f"Error: {str(e)}")

@ns_sms.route('/<int:id>')
@ns_sms.doc('sms_by_id')
class SmsItem(Resource):
    @ns_sms.doc('get_sms_by_id')
    @ns_sms.marshal_with(sms_response, code=200)
    @ns_sms.doc(security='basicAuth')
    @auth.login_required
    def get(self, id):
        """Get specific SMS by ID (index in list)"""
        check_client()
        allSms = mqtt_publisher.track_client_operation("retrieveAllSms", retrieve_all_sms, keenetic_client)
        if id < 0 or id >= len(allSms):
            api.abort(404, f"SMS with id '{id}' not found")
        sms = allSms[id]
        sms.pop("Locations", None)
        return sms

    @ns_sms.doc('delete_sms_by_id')
    @ns_sms.doc(security='basicAuth')
    @auth.login_required
    def delete(self, id):
        """Delete SMS by ID (index in list)"""
        check_client()
        allSms = mqtt_publisher.track_client_operation("retrieveAllSms", retrieve_all_sms, keenetic_client)
        if id < 0 or id >= len(allSms):
            api.abort(404, f"SMS with id '{id}' not found")
        mqtt_publisher.track_client_operation("deleteSms", delete_sms, keenetic_client, allSms[id])
        return '', 204

@ns_sms.route('/getsms')
@ns_sms.doc('get_and_delete_first_sms')
class GetSms(Resource):
    @ns_sms.doc('pop_first_sms')
    @ns_sms.marshal_with(sms_response, code=200)
    @ns_sms.doc(security='basicAuth')
    @auth.login_required
    def get(self):
        """Get first SMS and delete it from memory"""
        check_client()
        allSms = mqtt_publisher.track_client_operation("retrieveAllSms", retrieve_all_sms, keenetic_client)
        sms = {"Date": "", "Number": "", "State": "", "Text": ""}
        if len(allSms) > 0:
            sms = allSms[0]
            mqtt_publisher.track_client_operation("deleteSms", delete_sms, keenetic_client, sms)
            sms.pop("Locations", None)
            if sms.get("Text"):
                mqtt_publisher.publish_sms_received(sms)
        return sms

@ns_sms.route('/deleteall')
@ns_sms.doc('delete_all_sms')
class DeleteAllSms(Resource):
    @ns_sms.doc('delete_all_messages')
    @ns_sms.doc(security='basicAuth')
    @auth.login_required
    def delete(self):
        """Delete all SMS messages"""
        check_client()
        count = mqtt_publisher.track_client_operation("deleteAllSms", keenetic_client.delete_all_sms)
        return {"status": 200, "message": f"Deleted {count} SMS messages"}, 200

@ns_status.route('/signal')
@ns_status.doc('get_signal_quality')
class Signal(Resource):
    @ns_status.doc('signal_strength')
    @ns_status.marshal_with(signal_response)
    def get(self):
        """Get GSM signal strength"""
        check_client()
        signal_data = mqtt_publisher.track_client_operation("GetSignalQuality", keenetic_client.get_signal_quality)
        mqtt_publisher.publish_signal_strength(signal_data)
        return signal_data

@ns_status.route('/network')
@ns_status.doc('get_network_info')
class Network(Resource):
    @ns_status.doc('network_information')
    @ns_status.marshal_with(network_response)
    def get(self):
        """Get network info"""
        check_client()
        network = mqtt_publisher.track_client_operation("GetNetworkInfo", keenetic_client.get_network_info)
        mqtt_publisher.publish_network_info(network)
        return network

@ns_status.route('/modem')
@ns_status.doc('get_modem_info')
class ModemInfo(Resource):
    @ns_status.doc('modem_information')
    @ns_status.marshal_with(modem_info_response)
    def get(self):
        """Get modem info"""
        check_client()
        modem_info = mqtt_publisher.track_client_operation("GetModemInfo", keenetic_client.get_modem_info)
        mqtt_publisher.publish_modem_info(modem_info)
        return modem_info

@ns_status.route('/sim')
@ns_status.doc('get_sim_info')
class SimInfo(Resource):
    @ns_status.doc('sim_information')
    @ns_status.marshal_with(sim_info_response)
    def get(self):
        """Get SIM info (IMSI)"""
        check_client()
        sim_info = {"IMSI": mqtt_publisher.track_client_operation("GetIMSI", keenetic_client.get_sim_imsi)}
        mqtt_publisher.publish_sim_info(sim_info)
        return sim_info

@ns_status.route('/sms_capacity')
@ns_status.doc('get_sms_capacity')
class SmsCapacity(Resource):
    @ns_status.doc('sms_storage_capacity')
    @ns_status.marshal_with(sms_capacity_response)
    def get(self):
        """Get SMS capacity"""
        check_client()
        capacity = mqtt_publisher.track_client_operation("GetSMSCapacity", keenetic_client.get_sms_capacity)
        mqtt_publisher.publish_sms_capacity(capacity)
        return capacity

@ns_status.route('/reset')
@ns_status.doc('reset_modem')
class Reset(Resource):
    @ns_status.doc('modem_reset')
    @ns_status.marshal_with(reset_response)
    def get(self):
        """Check connection / Refresh session"""
        check_client()
        # Just check connection
        status = mqtt_publisher.track_client_operation("CheckConnection", keenetic_client.check_connection)
        return {"status": 200, "message": f"Connection active: {status}"}, 200

if __name__ == '__main__':
    print(f"🚀 SMS Keenetic Gateway v{VERSION} started successfully!")
    print(f"🌐 API available on port {port}")
    print(f"🏠 Web UI: http://localhost:{port}/")
    print(f"📡 Keenetic Host: {keenetic_host}")
    
    # MQTT info
    if config.get('mqtt_enabled', False):
        print(f"📡 MQTT: Enabled -> {config.get('mqtt_host')}:{config.get('mqtt_port')}")
        
        # Wait a moment for MQTT connection
        import time
        time.sleep(2)
        
        if keenetic_client:
            mqtt_publisher.publish_initial_states_with_client(keenetic_client)
            
            # Start periodic MQTT publishing
            mqtt_publisher.publish_status_periodic(keenetic_client, interval=300)
            
            # Start SMS monitoring if enabled
            if config.get('sms_monitoring_enabled', True):
                check_interval = config.get('sms_check_interval', 60)
                mqtt_publisher.start_sms_monitoring(keenetic_client, check_interval=check_interval)
                print(f"📱 SMS Monitoring: Enabled (check every {check_interval}s)")
            else:
                print(f"📱 SMS Monitoring: Disabled")
    else:
        print(f"📡 MQTT: Disabled")
    
    try:
        if ssl:
            app.run(port=port, host="0.0.0.0", ssl_context=('/ssl/cert.pem', '/ssl/key.pem'),
                    debug=False, use_reloader=False)
        else:
            app.run(port=port, host="0.0.0.0", debug=False, use_reloader=False)
    finally:
        mqtt_publisher.disconnect()
