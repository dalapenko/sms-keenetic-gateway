# SMS Keenetic Gateway Add-on

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]
![Supports armhf Architecture][armhf-shield]
![Supports armv7 Architecture][armv7-shield]
![Supports i386 Architecture][i386-shield]

REST API SMS Gateway using Keenetic Router API (RCI) for SMS operations.

## About

This add-on provides a complete SMS gateway solution for Home Assistant using a Keenetic Router with a 4G/LTE modem. It replaces the need for a directly connected USB modem by communicating with the router over the network. It offers both REST API and MQTT interfaces for sending and receiving SMS messages.

**Modern replacement for:**
- Direct USB GSM modem integrations
- Gammu-based gateways

## 🌟 Key Features

### 📱 SMS Management
- **Send SMS** via REST API, MQTT, or Home Assistant UI
- **Receive SMS** with automatic MQTT notifications
- **Text Input Fields** directly in Home Assistant device
- **Smart Buttons** for easy SMS sending from UI
- **Phone Number Persistence** - keeps number for multiple messages
- **Delete All SMS Button** - Clear SIM card storage with one click
- **Auto-delete SMS** - Optional automatic deletion after reading
- **Reset Counter Button** - Reset SMS statistics
- **Message Length Limit** - 255 characters max (limit of Home Assistant text sensor)

### 📊 Device Monitoring
- **Signal Strength** sensor with percentage display
- **Network Info** showing operator name and status
- **Last SMS Received** sensor with full message details
- **SMS Send Status** tracking success/error states
- **SMS Counter** with persistent storage (survives restarts)
- **SMS Cost Tracking** (optional, configurable price per SMS)
- **Modem Info** sensors (IMEI, Model, Manufacturer)
- **SIM Card Info** (IMSI identification)
- **SMS Storage Capacity** monitoring (used/total on SIM)
- **Modem Status** tracking connectivity to router
- **Real-time Updates** via MQTT with auto-discovery

### 🔧 Integration Options
- **REST API** with Swagger documentation at `/docs/`
- **MQTT Integration** with Home Assistant auto-discovery
- **Native HA Service** `send_sms` for automations
- **Notify Platform** support for alerts
- **Web UI** accessible through Ingress

## Prerequisites

- Keenetic Router with 4G/LTE modem (built-in or USB)
- Router must be accessible via network from Home Assistant
- Admin credentials for the router
- SIM card with SMS capability
- Optional: MQTT broker for full integration

## Installation

1. Add repository to your Home Assistant:
   ```
   https://github.com/dalapenko/sms-keenetic-gateway
   ```
2. Find **SMS Keenetic Gateway** in add-on store
3. Click Install
4. Configure the add-on (see below)
5. Start the add-on

## Configuration

### Router Connection Settings

| Option                     | Default       | Description                                          |
|----------------------------|---------------|------------------------------------------------------|
| `keenetic_host`            | `192.168.1.1` | IP address or hostname of your Keenetic router       |
| `keenetic_username`        | `admin`       | Router admin username                                |
| `keenetic_password`        | `""`          | Router admin password                                |
| `keenetic_modem_interface` | `UsbLte0`     | Interface name of the modem (e.g., UsbLte0, UsbQmi0) |
| `keenetic_use_https`       | `false`       | Use HTTPS for connection (recommended if configured) |

### API Settings

| Option     | Default    | Description                       |
|------------|------------|-----------------------------------|
| `port`     | `5000`     | Local API port                    |
| `ssl`      | `false`    | Enable HTTPS for local API        |
| `username` | `admin`    | Local API username                |
| `password` | `password` | Local API password (change this!) |

### MQTT Settings (Optional)

| Option                   | Default                                     | Description                  |
|--------------------------|---------------------------------------------|------------------------------|
| `mqtt_enabled`           | `false`                                     | Enable MQTT integration      |
| `mqtt_host`              | `core-mosquitto`                            | MQTT broker hostname         |
| `mqtt_port`              | `1883`                                      | MQTT broker port             |
| `mqtt_username`          | `""`                                        | MQTT username                |
| `mqtt_password`          | `""`                                        | MQTT password                |
| `mqtt_topic_prefix`      | `homeassistant/sensor/sms_keenetic_gateway` | Topic prefix                 |
| `sms_monitoring_enabled` | `true`                                      | Auto-detect incoming SMS     |
| `sms_check_interval`     | `60`                                        | SMS check interval (seconds) |

### Advanced Settings

| Option                 | Default | Description                                             |
|------------------------|---------|---------------------------------------------------------|
| `sms_cost_per_message` | `0.0`   | Cost per SMS (set to 0 to disable cost tracking sensor) |
| `auto_delete_read_sms` | `true`  | Automatically delete SMS from router after reading      |

### Finding Modem Interface Name

To find the correct interface name (`keenetic_modem_interface`):
1. Log in to your Keenetic router web interface
2. Go to **System Dashboard** -> **Internet**
3. Click on your Mobile connection
4. Look for the interface identifier (usually visible in the URL or status page, e.g., `UsbLte0`)
5. Alternatively, use the CLI command: `show interface`

## 🏠 Home Assistant Integration

### Method 1: MQTT with Auto-Discovery (Recommended)

Enable MQTT in configuration and the add-on will automatically create:
- 📊 **GSM Signal Strength** sensor
- 🌐 **GSM Network** sensor
- 💬 **Last SMS Received** sensor
- ✅ **SMS Send Status** sensor
- 📱 **Phone Number** text input
- 💬 **Message Text** text input
- 🔘 **Send SMS** button

All entities appear under device **"SMS Gateway"** in Home Assistant.

![MQTT Device Overview](https://raw.githubusercontent.com/dalapenko/sms-keenetic-gateway/main/images/mqtt-device.png)

### Method 2: RESTful Notify

Add to your `configuration.yaml`:

```yaml
notify:
  - name: SMS Gateway
    platform: rest
    resource: http://192.168.1.x:5000/sms
    method: POST_JSON
    authentication: basic
    username: admin
    password: your_password
    target_param_name: number
    message_param_name: message
```

![Actions Notify Example](https://raw.githubusercontent.com/dalapenko/sms-keenetic-gateway/main/images/actions-notify.png)

### Method 3: Direct Service Calls

Use in automations:

```yaml
service: mqtt.publish
data:
  topic: "homeassistant/sensor/sms_keenetic_gateway/send"
  payload: '{"number": "+420123456789", "text": "Alert!"}'
```

## 📝 Usage Examples

### Send SMS via Button
1. Go to **SMS Gateway** device in Home Assistant
2. Fill **Phone Number** field (e.g., +420123456789)
3. Fill **Message Text** field (max 255 characters)
4. Click **Send SMS** button
5. Message field auto-clears, number stays for next message

**Note:** Messages are limited to 255 characters due to MQTT message size constraints.

### Automation Example

```yaml
automation:
  - alias: Door Alert SMS
    trigger:
      platform: state
      entity_id: binary_sensor.door
      to: 'on'
    action:
      service: notify.sms_keenetic_gateway
      data:
        message: 'Door opened!'
        target: '+420123456789'
```

### REST API Examples

```bash
curl -X POST http://192.168.1.x:5000/sms \
  -H "Content-Type: application/json" \
  -u admin:password \
  -d '{"text": "Test SMS", "number": "+420123456789"}'
```

## 🔧 API Documentation

### Swagger UI
Access full API documentation at: `http://your-ha-ip:5000/docs/`

![Swagger UI Documentation](https://raw.githubusercontent.com/dalapenko/sms-keenetic-gateway/main/images/swagger-ui.png)

### Main Endpoints

| Method | Endpoint          | Description      | Auth |
|--------|-------------------|------------------|------|
| POST   | `/sms`            | Send SMS         | Yes  |
| GET    | `/sms`            | Get all SMS      | Yes  |
| GET    | `/sms/{id}`       | Get specific SMS | Yes  |
| DELETE | `/sms/{id}`       | Delete SMS       | Yes  |
| GET    | `/status/signal`  | Signal strength  | No   |
| GET    | `/status/network` | Network info     | No   |
| GET    | `/status/reset`   | Check connection | No   |

## 🚨 Troubleshooting

### Authentication Errors
- Verify router username and password
- Check if you can log in to the router web interface
- Ensure `keenetic_host` is correct and reachable

### Connection Refused
- Check network connectivity between HA and Router
- Verify router firewall settings (RCI API access allowed)

### SMS Not Sending
- Check signal strength (should be > 20%)
- Verify SIM card has credit
- Check network registration status in router interface

### MQTT Not Working
- Verify MQTT broker is running
- Check MQTT credentials
- Look for connection errors in add-on logs
- Ensure topic prefix doesn't conflict

## 📋 Version History

See [CHANGELOG.md](./CHANGELOG.md) for detailed version history.

## 🤝 Support

- **Issues**: [GitHub Issues](https://github.com/dalapenko/sms-keenetic-gateway/issues)
- **Documentation**: This page and Swagger UI at `/docs/`

## 📜 License

Licensed under Apache License 2.0.

---

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[armhf-shield]: https://img.shields.io/badge/armhf-yes-green.svg
[armv7-shield]: https://img.shields.io/badge/armv7-yes-green.svg
[i386-shield]: https://img.shields.io/badge/i386-yes-green.svg
