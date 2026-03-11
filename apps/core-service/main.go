package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/cors"
	"github.com/gofiber/fiber/v2/middleware/logger"
)

// Environment variables
var (
	monolithURL          = getEnv("MONOLITH_URL", "http://app:8080")
	integrationServiceURL = getEnv("INTEGRATION_SERVICE_URL", "http://integration-service:8085")
	httpClient           = &http.Client{Timeout: 10 * time.Second}
)

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}

// Device represents a registered device
type Device struct {
	ID        string                 `json:"id"`
	Name      string                 `json:"name"`
	Type      string                 `json:"type"`
	Vendor    string                 `json:"vendor"`
	Status    string                 `json:"status"`
	Metadata  map[string]interface{} `json:"metadata,omitempty"`
	LastSeen  time.Time              `json:"last_seen"`
	CreatedAt time.Time              `json:"created_at"`
}

// DeviceCreate represents device creation request
type DeviceCreate struct {
	Name           string                 `json:"name"`
	Type           string                 `json:"type"`
	Vendor         string                 `json:"vendor"`
	Metadata       map[string]interface{} `json:"metadata,omitempty"`
	SyncToMonolith bool                   `json:"sync_to_monolith"`
}

// DeviceUpdate represents device update request
type DeviceUpdate struct {
	Name     string                 `json:"name,omitempty"`
	Type     string                 `json:"type,omitempty"`
	Vendor   string                 `json:"vendor,omitempty"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// DeviceStatus represents device status update
type DeviceStatus struct {
	Status   string                 `json:"status"`
	Metadata map[string]interface{} `json:"metadata,omitempty"`
}

// Command represents a device command
type Command struct {
	Command   string                 `json:"command"`
	Params    map[string]interface{} `json:"params,omitempty"`
	Timestamp time.Time              `json:"timestamp"`
}

// HealthResponse represents health check response
type HealthResponse struct {
	Status  string `json:"status"`
	Service string `json:"service"`
}

// MonitoringStats represents device monitoring statistics
type MonitoringStats struct {
	Total   int `json:"total"`
	Online  int `json:"online"`
	Offline int `json:"offline"`
	Error   int `json:"error"`
}

// Sensor represents a sensor from monolith
type Sensor struct {
	ID          int       `json:"id"`
	Name        string    `json:"name"`
	Type        string    `json:"type"`
	Location    string    `json:"location"`
	Value       float64   `json:"value"`
	Unit        string    `json:"unit"`
	Status      string    `json:"status"`
	LastUpdated time.Time `json:"last_updated"`
	CreatedAt   time.Time `json:"created_at"`
}

// DeviceRegistry manages device state
type DeviceRegistry struct {
	mu       sync.RWMutex
	devices  map[string]*Device
	commands map[string][]Command
}

func NewDeviceRegistry() *DeviceRegistry {
	return &DeviceRegistry{
		devices:  make(map[string]*Device),
		commands: make(map[string][]Command),
	}
}

func (r *DeviceRegistry) Create(device DeviceCreate) Device {
	r.mu.Lock()
	defer r.mu.Unlock()

	id := generateID()
	now := time.Now()

	deviceObj := Device{
		ID:        id,
		Name:      device.Name,
		Type:      device.Type,
		Vendor:    device.Vendor,
		Status:    "offline",
		LastSeen:  now,
		Metadata:  device.Metadata,
		CreatedAt: now,
	}

	r.devices[id] = &deviceObj
	return deviceObj
}

func (r *DeviceRegistry) GetAll() []Device {
	r.mu.RLock()
	defer r.mu.RUnlock()

	devices := make([]Device, 0, len(r.devices))
	for _, d := range r.devices {
		devices = append(devices, *d)
	}
	return devices
}

func (r *DeviceRegistry) GetByID(id string) (*Device, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()

	device, ok := r.devices[id]
	if !ok {
		return nil, false
	}
	return device, true
}

func (r *DeviceRegistry) Update(id string, update DeviceUpdate) (*Device, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()

	device, ok := r.devices[id]
	if !ok {
		return nil, false
	}

	if update.Name != "" {
		device.Name = update.Name
	}
	if update.Type != "" {
		device.Type = update.Type
	}
	if update.Vendor != "" {
		device.Vendor = update.Vendor
	}
	if update.Metadata != nil {
		device.Metadata = update.Metadata
	}

	return device, true
}

func (r *DeviceRegistry) UpdateStatus(id string, status DeviceStatus) (*Device, bool) {
	r.mu.Lock()
	defer r.mu.Unlock()

	device, ok := r.devices[id]
	if !ok {
		return nil, false
	}

	device.Status = status.Status
	device.LastSeen = time.Now()
	if status.Metadata != nil {
		device.Metadata = status.Metadata
	}

	return device, true
}

func (r *DeviceRegistry) Delete(id string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.devices[id]; !ok {
		return false
	}

	delete(r.devices, id)
	delete(r.commands, id)
	return true
}

func (r *DeviceRegistry) SendCommand(id string, cmd Command) bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	if _, ok := r.devices[id]; !ok {
		return false
	}

	r.commands[id] = append(r.commands[id], cmd)
	return true
}

func (r *DeviceRegistry) GetCommands(id string) []Command {
	r.mu.RLock()
	defer r.mu.RUnlock()

	return r.commands[id]
}

func (r *DeviceRegistry) GetStats() MonitoringStats {
	r.mu.RLock()
	defer r.mu.RUnlock()

	stats := MonitoringStats{
		Total: len(r.devices),
	}

	for _, d := range r.devices {
		switch d.Status {
		case "online":
			stats.Online++
		case "offline":
			stats.Offline++
		case "error":
			stats.Error++
		}
	}

	return stats
}

func generateID() string {
	return fmt.Sprintf("dev_%d", time.Now().UnixNano())
}

func main() {
	app := fiber.New(fiber.Config{
		AppName: "Core Service v1.0",
	})

	// Middleware
	app.Use(cors.New())
	app.Use(logger.New())

	// Initialize registry
	registry := NewDeviceRegistry()
	
	// Initialize Integration Service client
	integrationClient := NewIntegrationServiceClient(integrationServiceURL)
	log.Printf("Integration Service URL: %s", integrationServiceURL)

	// ===========================================
	// Documentation endpoints
	// ===========================================

	// OpenAPI JSON endpoint
	app.Get("/openapi.json", func(c *fiber.Ctx) error {
		return c.SendFile("openapi.json")
	})

	// Swagger UI - serve static files from docs directory
	app.Static("/swagger", "./docs")

	// ===========================================
	// Health check
	// ===========================================

	app.Get("/health", func(c *fiber.Ctx) error {
		return c.JSON(HealthResponse{
			Status:  "ok",
			Service: "core-service",
		})
	})

	// ===========================================
	// Device registry endpoints
	// ===========================================

	app.Post("/devices", func(c *fiber.Ctx) error {
		var device DeviceCreate
		if err := c.BodyParser(&device); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": err.Error()})
		}

		created := registry.Create(device)

		// Optionally sync to monolith
		if device.SyncToMonolith {
			go syncDeviceToMonolith(created)
		}

		return c.Status(201).JSON(created)
	})

	// Get all devices - proxy to monolith for backward compatibility
	app.Get("/devices", func(c *fiber.Ctx) error {
		// First try to get sensors from monolith
		resp, err := http.Get(fmt.Sprintf("%s/api/v1/sensors", monolithURL))
		if err == nil && resp.StatusCode == 200 {
			defer resp.Body.Close()
			body, err := io.ReadAll(resp.Body)
			if err == nil {
				var sensors []Sensor
				if err := json.Unmarshal(body, &sensors); err == nil {
					// Convert sensors to devices format
					devices := make([]Device, len(sensors))
					for i, s := range sensors {
						devices[i] = sensorToDevice(s)
					}
					return c.JSON(devices)
				}
			}
		}

		// Fallback to local registry if monolith unavailable
		devices := registry.GetAll()
		return c.JSON(devices)
	})

	app.Get("/devices/:id", func(c *fiber.Ctx) error {
		id := c.Params("id")
		device, ok := registry.GetByID(id)
		if !ok {
			return c.Status(404).JSON(fiber.Map{"error": "Device not found"})
		}
		return c.JSON(device)
	})

	app.Put("/devices/:id", func(c *fiber.Ctx) error {
		id := c.Params("id")
		var update DeviceUpdate
		if err := c.BodyParser(&update); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": err.Error()})
		}

		device, ok := registry.Update(id, update)
		if !ok {
			return c.Status(404).JSON(fiber.Map{"error": "Device not found"})
		}
		return c.JSON(device)
	})

	app.Delete("/devices/:id", func(c *fiber.Ctx) error {
		id := c.Params("id")
		if !registry.Delete(id) {
			return c.Status(404).JSON(fiber.Map{"error": "Device not found"})
		}
		return c.JSON(fiber.Map{"message": "Device deleted"})
	})

	app.Put("/devices/:id/status", func(c *fiber.Ctx) error {
		id := c.Params("id")
		var status DeviceStatus
		if err := c.BodyParser(&status); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": err.Error()})
		}

		device, ok := registry.UpdateStatus(id, status)
		if !ok {
			return c.Status(404).JSON(fiber.Map{"error": "Device not found"})
		}
		return c.JSON(device)
	})

	// ===========================================
	// Device command endpoints
	// ===========================================

	app.Post("/devices/:id/commands", func(c *fiber.Ctx) error {
		id := c.Params("id")
		var cmd Command
		if err := c.BodyParser(&cmd); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": err.Error()})
		}
		cmd.Timestamp = time.Now()

		if !registry.SendCommand(id, cmd) {
			return c.Status(404).JSON(fiber.Map{"error": "Device not found"})
		}
		return c.Status(201).JSON(cmd)
	})

	app.Get("/devices/:id/commands", func(c *fiber.Ctx) error {
		id := c.Params("id")
		commands := registry.GetCommands(id)
		return c.JSON(commands)
	})

	// ===========================================
	// Monitoring endpoints
	// ===========================================

	app.Get("/monitoring/devices", func(c *fiber.Ctx) error {
		stats := registry.GetStats()
		return c.JSON(stats)
	})

	// ===========================================
	// Integration Service endpoints (NEW)
	// ===========================================

	// Create integration in Integration Service
	app.Post("/integrations", func(c *fiber.Ctx) error {
		var integration IntegrationCreate
		if err := c.BodyParser(&integration); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": err.Error()})
		}

		result, err := integrationClient.CreateIntegration(integration)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Integration Service unavailable: %v", err),
			})
		}

		return c.Status(201).JSON(result)
	})

	// Get devices from Integration Service
	app.Get("/integrations/:id/devices", func(c *fiber.Ctx) error {
		integrationID := c.Params("id")
		
		devices, err := integrationClient.GetIntegrationDevices(integrationID)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Integration Service unavailable: %v", err),
			})
		}

		return c.JSON(devices)
	})

	// Get device status from Integration Service
	app.Get("/external-devices/:device_id/status", func(c *fiber.Ctx) error {
		deviceID := c.Params("device_id")
		
		status, err := integrationClient.GetDeviceStatus(deviceID)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Integration Service unavailable: %v", err),
			})
		}

		return c.JSON(status)
	})

	// Send command to device via Integration Service
	app.Post("/external-devices/:device_id/command", func(c *fiber.Ctx) error {
		deviceID := c.Params("device_id")
		
		var cmd IntegrationCommand
		if err := c.BodyParser(&cmd); err != nil {
			return c.Status(400).JSON(fiber.Map{"error": err.Error()})
		}

		result, err := integrationClient.SendCommand(deviceID, cmd)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Integration Service unavailable: %v", err),
			})
		}

		return c.JSON(result)
	})

	// ===========================================
	// Monolith integration (backward compatibility)
	// ===========================================

	// Get sensors from monolith
	app.Get("/monolith/sensors", func(c *fiber.Ctx) error {
		resp, err := http.Get(fmt.Sprintf("%s/api/v1/sensors", monolithURL))
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Monolith unavailable: %v", err),
			})
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Failed to read response: %v", err),
			})
		}

		var sensors []Sensor
		if err := json.Unmarshal(body, &sensors); err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Failed to parse response: %v", err),
			})
		}

		return c.JSON(sensors)
	})

	// Get specific sensor from monolith
	app.Get("/monolith/sensors/:id", func(c *fiber.Ctx) error {
		id := c.Params("id")
		resp, err := http.Get(fmt.Sprintf("%s/api/v1/sensors/%s", monolithURL, id))
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Monolith unavailable: %v", err),
			})
		}
		defer resp.Body.Close()

		if resp.StatusCode == 404 {
			return c.Status(404).JSON(fiber.Map{
				"error": "Sensor not found in monolith",
			})
		}

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Failed to read response: %v", err),
			})
		}

		var sensor Sensor
		if err := json.Unmarshal(body, &sensor); err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Failed to parse response: %v", err),
			})
		}

		return c.JSON(sensor)
	})

	// Get monolith health
	app.Get("/monolith/health", func(c *fiber.Ctx) error {
		resp, err := http.Get(fmt.Sprintf("%s/health", monolithURL))
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Monolith unavailable: %v", err),
			})
		}
		defer resp.Body.Close()

		body, err := io.ReadAll(resp.Body)
		if err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Failed to read response: %v", err),
			})
		}

		var health HealthResponse
		if err := json.Unmarshal(body, &health); err != nil {
			return c.Status(503).JSON(fiber.Map{
				"error": fmt.Sprintf("Failed to parse response: %v", err),
			})
		}

		return c.JSON(health)
	})

	log.Println("Starting Core Service on :8084")
	log.Printf("Monolith URL: %s", monolithURL)
	log.Fatal(app.Listen(":8084"))
}

// syncDeviceToMonolith creates a sensor in the monolith for backward compatibility
func syncDeviceToMonolith(device Device) {
	url := fmt.Sprintf("%s/api/v1/sensors", monolithURL)

	// Map device to sensor format
	sensorData := map[string]interface{}{
		"name":     device.Name,
		"type":     device.Type,
		"location": device.Vendor, // Using vendor as location for compatibility
		"unit":     "unknown",
	}

	jsonData, err := json.Marshal(sensorData)
	if err != nil {
		log.Printf("Failed to marshal device %s for monolith sync: %v", device.ID, err)
		return
	}

	resp, err := http.Post(url, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		log.Printf("Failed to sync device %s to monolith: %v", device.ID, err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		log.Printf("Device %s synced to monolith successfully", device.ID)
	} else {
		body, _ := io.ReadAll(resp.Body)
		log.Printf("Device %s sync to monolith returned status: %d, body: %s", device.ID, resp.StatusCode, string(body))
	}
}

// sensorToDevice converts a Sensor from monolith to Device format
func sensorToDevice(sensor Sensor) Device {
	return Device{
		ID:        fmt.Sprintf("sensor_%d", sensor.ID),
		Name:      sensor.Name,
		Type:      sensor.Type,
		Vendor:    sensor.Location, // Using location as vendor for compatibility
		Status:    mapSensorStatusToDeviceStatus(sensor.Status),
		Metadata:  map[string]interface{}{"value": sensor.Value, "unit": sensor.Unit},
		LastSeen:  sensor.LastUpdated,
		CreatedAt: sensor.CreatedAt,
	}
}

// mapSensorStatusToDeviceStatus converts sensor status to device status
func mapSensorStatusToDeviceStatus(status string) string {
	switch status {
	case "active":
		return "online"
	case "inactive":
		return "offline"
	default:
		return "offline"
	}
}

// ===========================================
// Integration Service Client
// ===========================================

// IntegrationServiceClient handles communication with Integration Service
type IntegrationServiceClient struct {
	baseURL string
	client  *http.Client
}

func NewIntegrationServiceClient(baseURL string) *IntegrationServiceClient {
	return &IntegrationServiceClient{
		baseURL: baseURL,
		client:  &http.Client{Timeout: 15 * time.Second},
	}
}

// IntegrationDevice represents a device from Integration Service
type IntegrationDevice struct {
	ID             string   `json:"id"`
	IntegrationID  string   `json:"integration_id"`
	Name           string   `json:"name"`
	Type           string   `json:"type"`
	Vendor         string   `json:"vendor"`
	Model          string   `json:"model,omitempty"`
	Capabilities   []string `json:"capabilities,omitempty"`
}

// IntegrationStatus represents device status from Integration Service
type IntegrationStatus struct {
	DeviceID string                 `json:"device_id"`
	Online   bool                   `json:"online"`
	State    map[string]interface{} `json:"state,omitempty"`
	LastSeen time.Time              `json:"last_seen,omitempty"`
}

// IntegrationCommand represents a command to send to Integration Service
type IntegrationCommand struct {
	Command string                 `json:"command"`
	Params  map[string]interface{} `json:"params,omitempty"`
}

// CommandResult represents result from Integration Service
type CommandResult struct {
	Success   bool      `json:"success"`
	DeviceID  string    `json:"device_id"`
	Command   string    `json:"command"`
	Message   string    `json:"message"`
	Timestamp time.Time `json:"timestamp"`
}

// GetIntegrationDevices gets devices from Integration Service
func (c *IntegrationServiceClient) GetIntegrationDevices(integrationID string) ([]IntegrationDevice, error) {
	url := fmt.Sprintf("%s/integrations/%s/devices", c.baseURL, integrationID)
	
	resp, err := c.client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to get integration devices: %w", err)
	}
	defer resp.Body.Close()
	
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("integration service returned status: %d", resp.StatusCode)
	}
	
	var devices []IntegrationDevice
	if err := json.NewDecoder(resp.Body).Decode(&devices); err != nil {
		return nil, fmt.Errorf("failed to decode devices: %w", err)
	}
	
	return devices, nil
}

// GetDeviceStatus gets device status from Integration Service
func (c *IntegrationServiceClient) GetDeviceStatus(deviceID string) (*IntegrationStatus, error) {
	url := fmt.Sprintf("%s/devices/%s/status", c.baseURL, deviceID)
	
	resp, err := c.client.Get(url)
	if err != nil {
		return nil, fmt.Errorf("failed to get device status: %w", err)
	}
	defer resp.Body.Close()
	
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("integration service returned status: %d", resp.StatusCode)
	}
	
	var status IntegrationStatus
	if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
		return nil, fmt.Errorf("failed to decode status: %w", err)
	}
	
	return &status, nil
}

// SendCommand sends command to device via Integration Service
func (c *IntegrationServiceClient) SendCommand(deviceID string, cmd IntegrationCommand) (*CommandResult, error) {
	url := fmt.Sprintf("%s/devices/%s/command", c.baseURL, deviceID)
	
	jsonData, err := json.Marshal(cmd)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal command: %w", err)
	}
	
	resp, err := c.client.Post(url, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to send command: %w", err)
	}
	defer resp.Body.Close()
	
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("integration service returned status: %d - %s", resp.StatusCode, string(body))
	}
	
	var result CommandResult
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode command result: %w", err)
	}
	
	return &result, nil
}

// CreateIntegration creates new integration in Integration Service
type IntegrationCreate struct {
	Name     string                 `json:"name"`
	Vendor   string                 `json:"vendor"`
	DeviceIP string                 `json:"device_ip,omitempty"`
	Config   map[string]interface{} `json:"config,omitempty"`
}

type Integration struct {
	ID        string                 `json:"id"`
	Name      string                 `json:"name"`
	Vendor    string                 `json:"vendor"`
	DeviceIP  string                 `json:"device_ip,omitempty"`
	Status    string                 `json:"status"`
	Config    map[string]interface{} `json:"config,omitempty"`
	CreatedAt string                 `json:"created_at"`
}

func (c *IntegrationServiceClient) CreateIntegration(integration IntegrationCreate) (*Integration, error) {
	url := fmt.Sprintf("%s/integrations", c.baseURL)
	
	jsonData, err := json.Marshal(integration)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal integration: %w", err)
	}
	
	resp, err := c.client.Post(url, "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to create integration: %w", err)
	}
	defer resp.Body.Close()
	
	if resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("integration service returned status: %d - %s", resp.StatusCode, string(body))
	}
	
	var result Integration
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return nil, fmt.Errorf("failed to decode integration: %w", err)
	}
	
	return &result, nil
}
