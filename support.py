"""
SMS Keenetic Gateway - Support functions
Keenetic integration functions for SMS operations
"""

import logging
from keenetic_client import KeeneticClient

logger = logging.getLogger(__name__)

def init_keenetic_client(host, username, password, modem_interface='UsbLte0', use_https=False):
    """Initialize Keenetic client connection"""
    client = KeeneticClient(host, username, password, modem_interface, use_https)
    
    try:
        # Attempt initial authentication
        if client.authenticate():
            logger.info(f"Successfully connected to Keenetic router at {host}")
            
            # Check modem availability
            try:
                modem_info = client.get_modem_info()
                logger.info(f"Modem detected: {modem_info.get('Manufacturer')} {modem_info.get('Model')}")
            except:
                logger.warning("Authentication successful but could not get modem info")
                
            return client
        else:
            logger.error("Authentication failed during initialization")
            raise Exception("Authentication failed")
            
    except Exception as e:
        logger.error(f"Error initializing Keenetic client: {e}")
        # Re-raise so main app knows initialization failed
        raise

def retrieveAllSms(client):
    """Retrieve all SMS messages from Keenetic modem"""
    try:
        raw_sms_list = client.get_all_sms()
        results = []
        
        for sms in raw_sms_list:
            # Handle state mapping
            # Keenetic typically uses lowercase 'read'/'unread'
            state = sms.get('status', 'read')
            if state == 'unread':
                state = 'UnRead'
            elif state == 'read':
                state = 'Read'
            else:
                state = state.capitalize()
                
            result = {
                "Date": sms.get('timestamp', ''),
                "Number": sms.get('number', 'Unknown'),
                "State": state,
                "Text": sms.get('text', ''),
                # Compatibility with existing format: Locations is a list of IDs
                "Locations": [sms.get('index')],
                # Additional fields preserved if needed
                "original_index": sms.get('index')
            }
            results.append(result)
            
        return results

    except Exception as e:
        logger.error(f"Error retrieving SMS: {e}")
        raise

def delete_sms(client, sms):
    """Delete SMS by object"""
    try:
        locations = sms.get("Locations", [])
        for loc in locations:
            client.delete_sms(loc)
    except Exception as e:
        logger.error(f"Error deleting SMS: {e}")

# Note: encodeSms is removed as Keenetic API handles encoding
