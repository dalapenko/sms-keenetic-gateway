# SMS Keenetic Gateway - Documentation

## 🚀 Quick Start

### Step 1: Prepare Router
- Ensure your Keenetic Router has a 4G/LTE modem and SIM card connected
- Verify Mobile connection is working in router web interface
- Find your modem interface name (System -> Internet -> Mobile connection details, e.g., `UsbLte0`)

### Step 2: Basic Configuration
```yaml
keenetic_host: "192.168.1.1"  # Router IP
keenetic_username: "admin"    # Router admin user
keenetic_password: "password" # Router admin password
keenetic_modem_interface: "UsbLte0" # Modem interface name
```

### Step 3: Enable MQTT (Recommended)
```yaml
mqtt_enabled: true
mqtt_host: "core-mosquitto"
```

### Step 4: Start the Add-on
- Click **START**
- Check the log for successful connection to router
- New device **SMS Gateway** will appear in HA

## 📱 How to Send SMS

### Method 1: UI Button (Easiest)
1. Go to **Devices** → **SMS Gateway**
2. Fill **Phone Number** (e.g., +420123456789)
3. Fill **Message Text**
4. Click **Send SMS**

### Method 2: Notify Service
```yaml
service: notify.sms_keenetic_gateway
data:
  message: "Test message"
  target: "+420123456789"
```

### Method 3: MQTT
```yaml
service: mqtt.publish
data:
  topic: "homeassistant/sensor/sms_keenetic_gateway/send"
  payload: '{"number": "+420123456789", "text": "Alert!"}'
```

### Method 4: REST API
```bash
curl -X POST http://192.168.1.x:5000/sms \
  -u admin:password \
  -d '{"text": "Test", "number": "+420123456789"}'
```

## 🔧 Configuration

### Router Connection Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `keenetic_host` | `192.168.1.1` | Router IP address |
| `keenetic_username` | `admin` | Router admin username |
| `keenetic_password` | `""` | Router admin password |
| `keenetic_modem_interface` | `UsbLte0` | Interface name (UsbLte0, UsbQmi0, etc.) |
| `keenetic_use_https` | `false` | Connect via HTTPS |

### Local API Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `port` | `5000` | Local API port |
| `username` | `admin` | Local API username |
| `password` | `password` | **⚠️ CHANGE THIS!** |

### MQTT Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `mqtt_enabled` | `true` | Enable MQTT integration |
| `mqtt_host` | `core-mosquitto` | MQTT broker hostname |
| `mqtt_port` | `1883` | MQTT broker port |
| `mqtt_username` | `""` | MQTT username |
| `mqtt_password` | `""` | MQTT password |
| `sms_monitoring_enabled` | `true` | Detect incoming SMS automatically |
| `sms_check_interval` | `60` | SMS check interval (seconds) |

### SMS Management Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `sms_cost_per_message` | `0.0` | Price per SMS (0 = disabled) |
| `auto_delete_read_sms` | `true` | Auto-delete SMS from router after reading |

## 📊 MQTT Sensors

After enabling MQTT, these entities are automatically created:

### Status Sensors
| Entity                                          | Type   | Description                             |
|-------------------------------------------------|--------|-----------------------------------------|
| `sensor.sms_keenetic_gateway_modem_status`      | Sensor | Connectivity to router (online/offline) |
| `sensor.sms_keenetic_gateway_signal_strength`   | Sensor | GSM signal strength in %                |
| `sensor.sms_keenetic_gateway_network`           | Sensor | Network operator name                   |
| `sensor.sms_keenetic_gateway_last_sms_received` | Sensor | Last received SMS message               |
| `sensor.sms_keenetic_gateway_sms_send_status`   | Sensor | SMS send operation status               |

### Modem Information Sensors
| Entity                                         | Type   | Description                  |
|------------------------------------------------|--------|------------------------------|
| `sensor.sms_keenetic_gateway_modem_imei`       | Sensor | Modem IMEI number            |
| `sensor.sms_keenetic_gateway_modem_model`      | Sensor | Modem manufacturer and model |
| `sensor.sms_keenetic_gateway_sim_imsi`         | Sensor | SIM card IMSI number         |
| `sensor.sms_keenetic_gateway_sms_storage_used` | Sensor | Number of SMS on SIM card    |

### SMS Counter & Cost Tracking
| Entity                                       | Type   | Description                  |
|----------------------------------------------|--------|------------------------------|
| `sensor.sms_keenetic_gateway_sms_sent_count` | Sensor | Total SMS sent through addon |
| `sensor.sms_keenetic_gateway_total_cost`     | Sensor | Total cost of sent SMS       |

### Controls
| Entity                                       | Type       | Description                  |
|----------------------------------------------|------------|------------------------------|
| `text.sms_keenetic_gateway_phone_number`     | Text input | Phone number input field     |
| `text.sms_keenetic_gateway_message_text`     | Text input | Message text input field     |
| `button.sms_keenetic_gateway_send_button`    | Button     | Send SMS button              |
| `button.sms_keenetic_gateway_reset_counter`  | Button     | Reset SMS counter and costs  |
| `button.sms_keenetic_gateway_delete_all_sms` | Button     | Delete all SMS from SIM card |

## 🎯 Automation Examples

### SMS on Door Open
```yaml
automation:
  - alias: "Security - Door Opened"
    trigger:
      platform: state
      entity_id: binary_sensor.front_door
      to: "on"
    action:
      service: notify.sms_keenetic_gateway
      data:
        message: "ALERT: Front door opened!"
        target: "+420123456789"
```

## 📡 REST API

### Swagger Documentation
Full API documentation: `http://your-ha-ip:5000/docs/`

### Main Endpoints

#### SMS Operations
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/sms` | Send SMS message |
| GET | `/sms` | Get all SMS messages |
| GET | `/sms/{id}` | Get specific SMS by ID |
| DELETE | `/sms/{id}` | Delete specific SMS |
| DELETE | `/sms/deleteall` | Delete all SMS from router |

#### Status & Information
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status/signal` | GSM signal strength |
| GET | `/status/network` | Network operator info |
| GET | `/status/modem` | Modem hardware info |
| GET | `/status/sim` | SIM card information |
| GET | `/status/sms_capacity` | SMS storage capacity |
| GET | `/status/reset` | Check connection |

## 🔴 Troubleshooting

### Authentication Failed
- Check router log for login attempts
- Verify IP address and credentials

### Modem Not Found
- Verify `keenetic_modem_interface` matches the interface name in router settings (e.g. `UsbLte0`)
- Check if modem is initialized in router web UI

### SMS Not Sending
- Check signal strength
- Verify SIM card status in router web UI

### MQTT Not Working
- Verify MQTT broker is running
- Check credentials and topic prefix

## 📝 Version History

See [CHANGELOG.md](./CHANGELOG.md) for detailed version history.
