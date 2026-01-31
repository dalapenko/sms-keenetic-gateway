"""
Keenetic Router API Client for SMS Gateway
Handles authentication and communication with Keenetic router RCI API
"""

import requests
import hashlib
import json
import logging
from typing import Optional, Dict, Any, List, Union

logger = logging.getLogger(__name__)

class KeeneticAuthError(Exception):
    """Authentication with Keenetic router failed"""
    pass

class KeeneticConnectionError(Exception):
    """Cannot connect to Keenetic router"""
    pass

class KeeneticSMSError(Exception):
    """SMS operation failed"""
    pass

class KeeneticClient:
    def __init__(self, host: str, username: str, password: str, 
                 modem_interface: str = 'UsbLte0', use_https: bool = False):
        self.host = host
        self.username = username
        self.password = password
        self.modem_interface = modem_interface
        self.protocol = 'https' if use_https else 'http'
        self.base_url = f"{self.protocol}://{host}"
        self.session = requests.Session()
        self.authenticated = False
        self.auth_cookies = None
        
        # Configure session with retries
        try:
            adapter = requests.adapters.HTTPAdapter(max_retries=3)
            self.session.mount('http://', adapter)
            self.session.mount('https://', adapter)
        except AttributeError:
            pass
    
    def authenticate(self) -> bool:
        """Perform challenge-response authentication"""
        try:
            # Step 1: Get challenge (401 Unauthorized expected)
            auth_url = f"{self.base_url}/auth"
            try:
                # Use a new session for fresh authentication flow
                temp_session = requests.Session()
                response = temp_session.get(auth_url, timeout=10)
            except requests.RequestException as e:
                logger.error(f"Connection error during auth step 1: {e}")
                raise KeeneticConnectionError(f"Could not connect to {self.base_url}")

            if response.status_code != 401:
                # If we get 200, we might be already authenticated or no auth required
                if response.status_code == 200:
                    logger.info("Authentication endpoint returned 200, assuming no auth or already logged in")
                    self.session = temp_session
                    self.authenticated = True
                    return True
                logger.error(f"Unexpected status code from auth endpoint: {response.status_code}")
                return False
                
            challenge = response.headers.get('X-KNDS-Challenge') or response.headers.get('X-Keenetic-Challenge')
            
            if not challenge:
                logger.error("No challenge header found in 401 response")
                return False
                
            # Step 2: Calculate hash
            # According to common Keenetic API docs:
            # hash = SHA256(challenge + SHA256(password))
            
            password_hash = hashlib.sha256(self.password.encode('utf-8')).hexdigest()
            auth_string = f"{challenge}{password_hash}"
            response_hash = hashlib.sha256(auth_string.encode('utf-8')).hexdigest()
            
            # Step 3: POST login
            login_data = {
                "login": self.username,
                "password": response_hash
            }
            
            response = temp_session.post(auth_url, json=login_data, timeout=10)
            
            if response.status_code == 200:
                self.session = temp_session
                self.authenticated = True
                self.auth_cookies = self.session.cookies
                logger.info("Successfully authenticated with Keenetic router")
                return True
            else:
                logger.error(f"Authentication failed with status {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            self.authenticated = False
            raise KeeneticConnectionError(f"Authentication process failed: {e}")

    def _ensure_authenticated(self):
        """Ensure we have a valid session, re-authenticating if necessary"""
        if not self.authenticated:
            if not self.authenticate():
                raise KeeneticAuthError("Could not authenticate with router")
                
    def _rci_request(self, path: str, method: str = 'GET', 
                     data: Optional[Dict] = None, retry_auth: bool = True) -> Dict:
        """Make authenticated RCI API request via URL path"""
        self._ensure_authenticated()
        
        url = f"{self.base_url}/rci{path}"
        try:
            if method.upper() == 'GET':
                response = self.session.get(url, timeout=15)
            else:
                response = self.session.post(url, json=data, timeout=15)
                
            # Handle 401 Unauthorized - Session expired
            if response.status_code == 401 and retry_auth:
                logger.info("Session expired (401), re-authenticating...")
                self.authenticated = False
                if self.authenticate():
                    return self._rci_request(path, method, data, retry_auth=False)
                else:
                    raise KeeneticAuthError("Re-authentication failed")
            
            if response.status_code != 200:
                logger.error(f"API Request failed: {url} -> {response.status_code} {response.text}")
                try:
                    error_json = response.json()
                    error_msg = json.dumps(error_json)
                except:
                    error_msg = response.text
                raise KeeneticConnectionError(f"API Error {response.status_code}: {error_msg}")
                
            try:
                return response.json()
            except json.JSONDecodeError:
                return {}
                
        except requests.RequestException as e:
            logger.error(f"Request error: {e}")
            raise KeeneticConnectionError(f"Connection failed: {e}")

    def send_command(self, payload: Union[List, Dict], retry_auth: bool = True) -> Any:
        """Send a JSON-RPC style command to the RCI endpoint"""
        self._ensure_authenticated()
        
        url = f"{self.base_url}/rci/"
        
        # Ensure payload is a list as Keenetic expects a list of commands
        if isinstance(payload, dict):
            payload = [payload]
            
        try:
            response = self.session.post(url, json=payload, timeout=15)
            
            # Handle 401 Unauthorized
            if response.status_code == 401 and retry_auth:
                logger.info("Session expired (401), re-authenticating...")
                self.authenticated = False
                if self.authenticate():
                    return self.send_command(payload, retry_auth=False)
                else:
                    raise KeeneticAuthError("Re-authentication failed")
            
            if response.status_code != 200:
                logger.error(f"Command failed: {response.status_code} {response.text}")
                raise KeeneticConnectionError(f"Command Error {response.status_code}")
                
            try:
                result = response.json()
                # If we sent a single command wrapped in a list, verify the result structure
                # Result is typically a list of responses
                return result
            except json.JSONDecodeError:
                return {}
                
        except requests.RequestException as e:
            logger.error(f"Request error: {e}")
            raise KeeneticConnectionError(f"Connection failed: {e}")

    # SMS Operations
    def send_sms(self, number: str, message: str) -> bool:
        """Send SMS via Keenetic modem using command structure"""
        # Command: interface <modem> sms send <number> <text>
        # JSON: [{"sms":{"send":{"interface":"UsbLte0","to":"+79207775544","message":"Привет. Как дела?"}}}]
        
        command = {
            "sms": {
                "send": {
                    "interface": self.modem_interface,
                    "to": number,
                    "message": message
                }
            }
        }
        
        try:
            # Send command and check result
            self.send_command([command])
            return True
        except KeeneticConnectionError as e:
            raise KeeneticSMSError(f"Failed to send SMS: {e}")

    def get_all_sms(self) -> List[Dict]:
        """Retrieve all SMS from modem using command structure"""
        # Command: sms list interface <modem>? OR show interface <modem> sms-list?
        # User observed: [{"sms":{"list":{"interface":"UsbLte0"}}}]
        
        command = {
            "sms": {
                "list": {
                    "interface": self.modem_interface
                }
            }
        }
        
        try:
            result = self.send_command([command])
            
            # Expected result format:
            # [{"sms": {"list": {"interface": "...", "messages": [...]}}}]
            # OR direct list of messages?
            
            if result and isinstance(result, list) and len(result) > 0:
                response_data = result[0]
                
                # Check directly for list of messages if structure is flat
                if isinstance(response_data, list):
                    return response_data
                
                # Check nested structure
                if "sms" in response_data and "list" in response_data["sms"]:
                    sms_data = response_data["sms"]["list"]
                    # If sms_data is the list itself
                    if isinstance(sms_data, list):
                        return sms_data
                    # If it's a dict with messages key
                    if isinstance(sms_data, dict) and "messages" in sms_data:
                        return sms_data["messages"]
                        
                # Fallback
                if "messages" in response_data:
                    return response_data["messages"]
            
            return []
            
        except Exception as e:
            logger.error(f"Failed to get SMS list: {e}")
            return []

    def delete_sms(self, sms_id: str) -> bool:
        """Delete SMS by ID using command structure"""
        # Command: [{"sms":{"delete":[{"interface":"UsbLte0","id":"nv-28"}]}}]
        
        command = {
            "sms": {
                "delete": [
                    {
                        "interface": self.modem_interface,
                        "id": sms_id
                    }
                ]
            }
        }
        
        try:
            self.send_command([command])
            return True
        except Exception as e:
            logger.error(f"Failed to delete SMS {sms_id}: {e}")
            raise KeeneticSMSError(f"Failed to delete SMS: {e}")

    def delete_all_sms(self) -> int:
        """Delete all SMS using bulk command"""
        all_sms = self.get_all_sms()
        if not all_sms:
            return 0
            
        delete_list = []
        for sms in all_sms:
            # Check 'id' first as per new structure, fallback to 'index'
            idx = sms.get('id') or sms.get('index')
            if idx is not None:
                delete_list.append({
                    "interface": self.modem_interface,
                    "id": str(idx)
                })
        
        if not delete_list:
            return 0
            
        # Command structure:
        # [{"sms":{"delete":[{"interface":"UsbLte0","id":"nv-0"}, ...]}}]
        command = {
            "sms": {
                "delete": delete_list
            }
        }
        
        try:
            self.send_command([command])
            return len(delete_list)
        except Exception as e:
            logger.error(f"Failed to delete all SMS: {e}")
            raise KeeneticSMSError(f"Failed to delete all SMS: {e}")

    # Modem Status
    def get_modem_info(self) -> Dict[str, Any]:
        """Get modem hardware info (IMEI, model, etc)"""
        # Using URL path is simple and usually works for 'show' commands
        # Command: show interface <modem>
        try:
            path = f"/show/interface/{self.modem_interface}"
            data = self._rci_request(path)
            
            return {
                "Manufacturer": data.get("manufacturer", "Unknown"),
                "Model": data.get("model", "Unknown"),
                "IMEI": data.get("imei", "Unknown"),
                "Firmware": data.get("firmware", "Unknown")
            }
        except Exception as e:
            logger.warning(f"Failed to get modem info: {e}")
            return {"Manufacturer": "Unknown", "Model": "Unknown", "IMEI": "Unknown", "Firmware": "Unknown"}

    def get_signal_quality(self) -> Dict[str, Any]:
        """Get signal strength info"""
        try:
            path = f"/show/interface/{self.modem_interface}"
            data = self._rci_request(path)
            
            rssi = data.get("signal-strength") or data.get("rssi", 0)
            
            percent = 0
            if rssi:
                try:
                    rssi_val = int(rssi)
                    if rssi_val >= -51: percent = 100
                    elif rssi_val <= -113: percent = 0
                    else: percent = int((rssi_val + 113) * 100 / 62)
                except:
                    pass
            
            return {
                "SignalStrength": rssi if rssi else -1,
                "SignalPercent": percent,
                "BitErrorRate": 0
            }
        except Exception as e:
            logger.warning(f"Failed to get signal quality: {e}")
            return {"SignalStrength": 0, "SignalPercent": 0, "BitErrorRate": 0}

    def get_network_info(self) -> Dict[str, Any]:
        """Get network/operator info"""
        try:
            path = f"/show/interface/{self.modem_interface}"
            data = self._rci_request(path)
            
            return {
                "NetworkName": data.get("operator", "Unknown"),
                "State": data.get("state", "Unknown"),
                "NetworkCode": f"{data.get('mcc','')}{data.get('mnc','')}",
                "CID": data.get("cell-id", ""),
                "LAC": data.get("lac", "")
            }
        except Exception as e:
            logger.warning(f"Failed to get network info: {e}")
            return {"NetworkName": "Unknown", "State": "Unknown"}

    def get_sms_capacity(self) -> Dict[str, Any]:
        """Get SMS storage capacity"""
        return {
            "SIMUsed": 0,
            "SIMSize": 0,
            "PhoneUsed": 0,
            "PhoneSize": 0,
            "TemplatesUsed": 0
        }
        
    def get_sim_imsi(self) -> str:
        """Get SIM IMSI"""
        try:
            path = f"/show/interface/{self.modem_interface}"
            data = self._rci_request(path)
            return data.get("imsi", "N/A")
        except:
            return "N/A"

    def check_connection(self) -> bool:
        """Check if modem is connected and responsive"""
        try:
            path = f"/show/interface/{self.modem_interface}"
            self._rci_request(path)
            return True
        except:
            return False
