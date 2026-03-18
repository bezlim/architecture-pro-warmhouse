"""
Integration Service - Device Integration Layer
Handles communication with smart devices with OPEN LOCAL APIs
(Shelly, Tasmota, ESPHome, Sonoff LAN, TP-Link Kasa)
"""
import os
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4
import httpx

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Integration Service",
    description="Device integration service - handles communication with smart devices with open local APIs",
    version="1.0.0",
    openapi_url="/openapi.json"
)

# Environment variables
CORE_SERVICE_URL = os.getenv("CORE_SERVICE_URL", "http://core-service:8084")

# In-memory storage
integrations_db: Dict[str, dict] = {}
devices_db: Dict[str, dict] = {}

# ===========================================
# Models
# ===========================================

class HealthResponse(BaseModel):
    status: str
    service: str

class IntegrationCreate(BaseModel):
    name: str
    vendor: str
    device_ip: Optional[str] = None  # Local IP for open API devices
    config: Optional[Dict[str, Any]] = None

class Integration(BaseModel):
    id: str
    name: str
    vendor: str
    device_ip: Optional[str] = None
    status: str = "active"
    config: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.now)

class ExternalDevice(BaseModel):
    id: str
    integration_id: str
    name: str
    type: str
    vendor: str
    model: Optional[str] = None
    capabilities: List[str] = []

class DeviceStatus(BaseModel):
    device_id: str
    online: bool
    state: Dict[str, Any] = {}
    last_seen: datetime = Field(default_factory=datetime.now)

class DeviceCommand(BaseModel):
    command: str
    params: Optional[Dict[str, Any]] = None

class CommandResult(BaseModel):
    success: bool
    device_id: str
    command: str
    message: str
    timestamp: datetime = Field(default_factory=datetime.now)

class VendorInfo(BaseModel):
    name: str
    display_name: str
    description: str
    supported: bool

class VendorCapabilities(BaseModel):
    vendor: str
    device_types: List[str]
    commands: List[str]

# ===========================================
# Vendor stub implementations (OPEN LOCAL APIs)
# ===========================================

class VendorAdapter:
    """Base class for vendor adapters with open local APIs"""
    
    def __init__(self, device_ip: str, config: Dict[str, Any]):
        self.device_ip = device_ip
        self.config = config
        self.base_url = f"http://{device_ip}"
    
    async def discover_devices(self) -> List[ExternalDevice]:
        raise NotImplementedError
    
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        raise NotImplementedError
    
    async def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        raise NotImplementedError

class ShellyVendorAdapter(VendorAdapter):
    """Shelly devices adapter - uses local REST API"""
    
    async def discover_devices(self) -> List[ExternalDevice]:
        """Shelly devices are added individually by IP"""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/shelly/")
                response.raise_for_status()
                device_info = response.json()
                
                return [ExternalDevice(
                    id=f"shelly_{device_info.get('mac', 'unknown')}",
                    integration_id="shelly_integration",
                    name=device_info.get('name', 'Shelly Device'),
                    type=self._map_device_type(device_info.get('type', '')),
                    vendor="shelly",
                    model=device_info.get('type', 'unknown'),
                    capabilities=self._get_shelly_capabilities(device_info.get('type', ''))
                )]
        except Exception as e:
            logger.error(f"Error discovering Shelly device: {e}")
            return []
    
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/status")
                response.raise_for_status()
                status_data = response.json()
                
                return DeviceStatus(
                    device_id=device_id,
                    online=status_data.get('mqtt_connected', True),
                    state={
                        "power": status_data.get('relays', [{}])[0].get('ison', False),
                        "brightness": status_data.get('lights', [{}])[0].get('brightness', 100) if status_data.get('lights') else 100
                    }
                )
        except Exception as e:
            logger.error(f"Error getting Shelly status: {e}")
            return DeviceStatus(device_id=device_id, online=False)
    
    async def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if command.command == "turn_on":
                    response = await client.get(f"{self.base_url}/relay/0?turn=on")
                elif command.command == "turn_off":
                    response = await client.get(f"{self.base_url}/relay/0?turn=off")
                elif command.command == "toggle":
                    response = await client.get(f"{self.base_url}/relay/0?turn=toggle")
                else:
                    return CommandResult(
                        success=False,
                        device_id=device_id,
                        command=command.command,
                        message=f"Unknown command: {command.command}"
                    )
                
                response.raise_for_status()
                
                return CommandResult(
                    success=True,
                    device_id=device_id,
                    command=command.command,
                    message="Shelly command executed successfully"
                )
        except Exception as e:
            logger.error(f"Error sending Shelly command: {e}")
            return CommandResult(
                success=False,
                device_id=device_id,
                command=command.command,
                message=str(e)
            )
    
    def _map_device_type(self, shelly_type: str) -> str:
        type_mapping = {
            "SHSW-1": "smart_relay",
            "SHSW-21": "smart_relay",
            "SHSW-25": "smart_relay",
            "SHSW-L": "smart_switch",
            "SHBLB-1": "smart_bulb",
            "SHCL-255": "smart_bulb",
            "SHSEN-1": "sensor_hub",
        }
        return type_mapping.get(shelly_type, "smart_device")
    
    def _get_shelly_capabilities(self, shelly_type: str) -> List[str]:
        if "BLB" in shelly_type or "CL" in shelly_type:
            return ["on_off", "brightness", "color", "color_temperature"]
        elif "SW" in shelly_type:
            return ["on_off", "power_meter"]
        return ["on_off"]

class TasmotaVendorAdapter(VendorAdapter):
    """Tasmota firmware adapter - uses local HTTP/MQTT API"""
    
    async def discover_devices(self) -> List[ExternalDevice]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/cm?cmnd=Status%200")
                response.raise_for_status()
                device_info = response.json()
                status = device_info.get('Status', {})
                
                return [ExternalDevice(
                    id=f"tasmota_{status.get('MAC', 'unknown').replace(':', '')}",
                    integration_id="tasmota_integration",
                    name=status.get('DeviceName', 'Tasmota Device'),
                    type=self._map_device_type(status),
                    vendor="tasmota",
                    model=status.get('Module', 'unknown'),
                    capabilities=["on_off", "brightness"]  # Basic capabilities
                )]
        except Exception as e:
            logger.error(f"Error discovering Tasmota device: {e}")
            return []
    
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/cm?cmnd=Status%2011")
                response.raise_for_status()
                status_data = response.json()
                
                return DeviceStatus(
                    device_id=device_id,
                    online=True,
                    state=status_data.get('StatusSTS', {})
                )
        except Exception as e:
            logger.error(f"Error getting Tasmota status: {e}")
            return DeviceStatus(device_id=device_id, online=False)
    
    async def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                if command.command == "turn_on":
                    cmd = "Power%20ON"
                elif command.command == "turn_off":
                    cmd = "Power%20OFF"
                elif command.command == "toggle":
                    cmd = "Power%20TOGGLE"
                elif command.command == "set_brightness" and command.params:
                    brightness = command.params.get('brightness', 50)
                    cmd = f"Dimmer%20{brightness}"
                else:
                    return CommandResult(
                        success=False,
                        device_id=device_id,
                        command=command.command,
                        message=f"Unknown command: {command.command}"
                    )
                
                response = await client.get(f"{self.base_url}/cm?cmnd={cmd}")
                response.raise_for_status()
                
                return CommandResult(
                    success=True,
                    device_id=device_id,
                    command=command.command,
                    message="Tasmota command executed successfully"
                )
        except Exception as e:
            logger.error(f"Error sending Tasmota command: {e}")
            return CommandResult(
                success=False,
                device_id=device_id,
                command=command.command,
                message=str(e)
            )
    
    def _map_device_type(self, status: Dict[str, Any]) -> str:
        module = str(status.get('Module', ''))
        if "Light" in module:
            return "smart_bulb"
        elif "Relay" in module:
            return "smart_relay"
        return "smart_device"

class ESPHomeVendorAdapter(VendorAdapter):
    """ESPHome adapter - uses native API or REST"""
    
    async def discover_devices(self) -> List[ExternalDevice]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/")
                response.raise_for_status()
                
                # ESPHome doesn't have a standard discovery API
                # Device info should be configured manually
                return [ExternalDevice(
                    id=f"esphome_{self.device_ip.replace('.', '_')}",
                    integration_id="esphome_integration",
                    name=f"ESPHome Device {self.device_ip}",
                    type="smart_device",
                    vendor="esphome",
                    model="ESP32/ESP8266",
                    capabilities=["on_off"]  # Basic capabilities
                )]
        except Exception as e:
            logger.error(f"Error discovering ESPHome device: {e}")
            return []
    
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/")
                response.raise_for_status()
                
                return DeviceStatus(
                    device_id=device_id,
                    online=True,
                    state={"uptime": "unknown"}  # Parse from HTML if needed
                )
        except Exception as e:
            logger.error(f"Error getting ESPHome status: {e}")
            return DeviceStatus(device_id=device_id, online=False)
    
    async def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # ESPHome uses POST requests for commands
                response = await client.post(
                    f"{self.base_url}/switch/{command.command}/toggle",
                    json=command.params or {}
                )
                response.raise_for_status()
                
                return CommandResult(
                    success=True,
                    device_id=device_id,
                    command=command.command,
                    message="ESPHome command executed successfully"
                )
        except Exception as e:
            logger.error(f"Error sending ESPHome command: {e}")
            return CommandResult(
                success=False,
                device_id=device_id,
                command=command.command,
                message=str(e)
            )

class MockVendorAdapter(VendorAdapter):
    """Mock vendor adapter for testing"""
    
    async def discover_devices(self) -> List[ExternalDevice]:
        return [
            ExternalDevice(
                id=f"mock_dev_{uuid4().hex[:8]}",
                integration_id="mock_integration",
                name="Mock Light",
                type="smart_bulb",
                vendor="mock",
                model="ML01",
                capabilities=["on_off", "brightness", "color"]
            )
        ]
    
    async def get_device_status(self, device_id: str) -> DeviceStatus:
        return DeviceStatus(
            device_id=device_id,
            online=True,
            state={"power": True, "brightness": 80}
        )
    
    async def send_command(self, device_id: str, command: DeviceCommand) -> CommandResult:
        return CommandResult(
            success=True,
            device_id=device_id,
            command=command.command,
            message="Mock command executed successfully"
        )

# Vendor adapter factory
VENDOR_ADAPTERS = {
    "mock": MockVendorAdapter,
    "shelly": ShellyVendorAdapter,
    "tasmota": TasmotaVendorAdapter,
    "esphome": ESPHomeVendorAdapter,
}

def get_vendor_adapter(vendor: str, device_ip: str, config: Dict[str, Any]) -> VendorAdapter:
    """Get vendor adapter instance"""
    adapter_class = VENDOR_ADAPTERS.get(vendor, MockVendorAdapter)
    return adapter_class(device_ip, config)

# ===========================================
# Health check
# ===========================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check if the integration service is running"""
    return HealthResponse(status="ok", service="integration-service")

# ===========================================
# Integration endpoints
# ===========================================

@app.post("/integrations", response_model=Integration, status_code=201)
async def create_integration(integration: IntegrationCreate):
    """Create a new vendor integration"""
    integration_id = f"int_{integration.vendor}_{uuid4().hex[:8]}"
    
    new_integration = Integration(
        id=integration_id,
        name=integration.name,
        vendor=integration.vendor,
        device_ip=integration.device_ip,
        config=integration.config
    )
    
    integrations_db[integration_id] = new_integration.dict()
    logger.info(f"Created integration: {integration_id} for vendor: {integration.vendor}")
    
    return new_integration

@app.get("/integrations", response_model=List[Integration])
async def get_integrations():
    """Get all configured integrations"""
    return list(integrations_db.values())

@app.get("/integrations/{integration_id}", response_model=Integration)
async def get_integration(integration_id: str):
    """Get integration by ID"""
    if integration_id not in integrations_db:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integrations_db[integration_id]

@app.delete("/integrations/{integration_id}")
async def delete_integration(integration_id: str):
    """Delete integration"""
    if integration_id not in integrations_db:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    del integrations_db[integration_id]
    return {"message": "Integration deleted successfully"}

@app.get("/integrations/{integration_id}/devices", response_model=List[ExternalDevice])
async def get_integration_devices(integration_id: str):
    """Discover devices from a specific integration"""
    if integration_id not in integrations_db:
        raise HTTPException(status_code=404, detail="Integration not found")
    
    integration = integrations_db[integration_id]
    adapter = get_vendor_adapter(integration["vendor"], integration.get("config", {}))
    
    devices = await adapter.discover_devices()
    
    # Update devices with integration_id
    for device in devices:
        device.integration_id = integration_id
    
    return devices

# ===========================================
# Device status endpoints
# ===========================================

@app.get("/devices/{device_id}/status", response_model=DeviceStatus)
async def get_device_status(device_id: str):
    """Get current status of an external device"""
    # Find device integration
    integration = None
    for int_id, int_data in integrations_db.items():
        if device_id.startswith(f"{int_data['vendor']}_"):
            integration = int_data
            break
    
    if not integration:
        raise HTTPException(status_code=404, detail="Device integration not found")
    
    adapter = get_vendor_adapter(integration["vendor"], integration.get("config", {}))
    return await adapter.get_device_status(device_id)

# ===========================================
# Device command endpoints
# ===========================================

@app.post("/devices/{device_id}/command", response_model=CommandResult)
async def send_device_command(device_id: str, command: DeviceCommand):
    """Execute a command on an external device"""
    # Find device integration
    integration = None
    for int_id, int_data in integrations_db.items():
        if device_id.startswith(f"{int_data['vendor']}_"):
            integration = int_data
            break
    
    if not integration:
        raise HTTPException(status_code=404, detail="Device integration not found")
    
    adapter = get_vendor_adapter(integration["vendor"], integration.get("config", {}))
    result = await adapter.send_command(device_id, command)
    
    return result

# ===========================================
# Vendor endpoints
# ===========================================

SUPPORTED_VENDORS = [
    VendorInfo(
        name="mock",
        display_name="Mock Vendor",
        description="Mock vendor for testing",
        supported=True
    ),
    VendorInfo(
        name="shelly",
        display_name="Shelly",
        description="Shelly Smart Home Devices (Open API)",
        supported=True
    ),
    VendorInfo(
        name="tasmota",
        display_name="Tasmota",
        description="Tasmota Open Firmware",
        supported=True
    ),
    VendorInfo(
        name="esphome",
        display_name="ESPHome",
        description="ESPHome Open Firmware",
        supported=True
    ),
]

VENDOR_CAPABILITIES = {
    "mock": VendorCapabilities(
        vendor="mock",
        device_types=["smart_bulb", "smart_plug"],
        commands=["turn_on", "turn_off", "set_brightness", "set_color"]
    ),
    "shelly": VendorCapabilities(
        vendor="shelly",
        device_types=["smart_relay", "smart_switch", "smart_bulb", "sensor_hub", "power_meter"],
        commands=["turn_on", "turn_off", "toggle", "get_status"]
    ),
    "tasmota": VendorCapabilities(
        vendor="tasmota",
        device_types=["smart_relay", "smart_bulb", "smart_plug", "sensor"],
        commands=["turn_on", "turn_off", "toggle", "set_brightness", "get_status"]
    ),
    "esphome": VendorCapabilities(
        vendor="esphome",
        device_types=["smart_relay", "smart_bulb", "sensor", "switch"],
        commands=["turn_on", "turn_off", "toggle"]
    ),
}

@app.get("/vendors", response_model=List[VendorInfo])
async def get_supported_vendors():
    """List all supported vendor types"""
    return SUPPORTED_VENDORS

@app.get("/vendors/{vendor}/capabilities", response_model=VendorCapabilities)
async def get_vendor_capabilities(vendor: str):
    """Get supported device types and commands for a vendor"""
    if vendor not in VENDOR_CAPABILITIES:
        raise HTTPException(status_code=404, detail=f"Vendor {vendor} not found")
    return VENDOR_CAPABILITIES[vendor]

# ===========================================
# OpenAPI and Swagger
# ===========================================

@app.get("/swagger/", include_in_schema=False)
async def get_swagger():
    """Serve Swagger UI"""
    from fastapi.responses import FileResponse
    return FileResponse("docs/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)
