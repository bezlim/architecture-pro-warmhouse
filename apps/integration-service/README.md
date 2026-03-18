# Integration Service

Device integration service for smart home devices with **OPEN LOCAL APIs**.

## Supported Vendors

| Vendor | Type | API | Status |
|--------|------|-----|--------|
| **Shelly** | Smart Relay, Switch, Bulb | REST API | ✅ Implemented |
| **Tasmota** | Smart Relay, Bulb, Plug | HTTP/MQTT | ✅ Implemented |
| **ESPHome** | Custom ESP32/ESP8266 | REST API | ✅ Implemented |
| **Mock** | Testing | Mock | ✅ Implemented |

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Core      │────▶│  Integration     │────▶│  Shelly Devices  │
│   Service   │     │  Service (:8085) │     │  (Local API)     │
└─────────────┘     └──────────────────┘     └──────────────────┘
                           │
                           ├─────────────────────────┐
                           │                         │
                    ┌──────▼──────┐           ┌──────▼──────┐
                    │   Tasmota   │           │   ESPHome   │
                    │  Devices    │           │   Devices   │
                    └─────────────┘           └─────────────┘
```

## API Endpoints

### Integrations

```bash
# Create integration
POST /integrations
{
  "name": "Living Room Shelly",
  "vendor": "shelly",
  "device_ip": "192.168.1.100"
}

# Get all integrations
GET /integrations

# Get integration by ID
GET /integrations/{id}

# Delete integration
DELETE /integrations/{id}
```

### Devices

```bash
# Discover devices for integration
GET /integrations/{id}/devices

# Get device status
GET /devices/{device_id}/status

# Send command to device
POST /devices/{device_id}/command
{
  "command": "turn_on",
  "params": {"brightness": 80}
}
```

### Vendors

```bash
# Get supported vendors
GET /vendors

# Get vendor capabilities
GET /vendors/{vendor}/capabilities
```

## Running

```bash
cd apps
docker-compose up -d integration-service
```

Swagger UI: http://localhost:8085/swagger/

## Adding New Vendor

1. Create new adapter class extending `VendorAdapter`
2. Implement `discover_devices()`, `get_device_status()`, `send_command()`
3. Add to `VENDOR_ADAPTERS` factory
4. Add to `SUPPORTED_VENDORS` and `VENDOR_CAPABILITIES`

Example:
```python
class MyVendorAdapter(VendorAdapter):
    async def discover_devices(self) -> List[ExternalDevice]:
        # Implement device discovery
        pass
    
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        # Implement status query
        pass
    
    async def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        # Implement command execution
        pass
```
