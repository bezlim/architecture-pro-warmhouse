package main

import (
	"log"
	"math/rand"
	"time"

	"github.com/gofiber/fiber/v2"
	"github.com/gofiber/fiber/v2/middleware/cors"
	"github.com/gofiber/fiber/v2/middleware/logger"
)

// TemperatureResponse represents the temperature data response
type TemperatureResponse struct {
	Value       float64   `json:"value"`
	Unit        string    `json:"unit"`
	Timestamp   time.Time `json:"timestamp"`
	Location    string    `json:"location"`
	Status      string    `json:"status"`
	SensorID    string    `json:"sensor_id"`
	SensorType  string    `json:"sensor_type"`
	Description string    `json:"description"`
}

// HealthResponse represents the health check response
type HealthResponse struct {
	Status string `json:"status"`
}

// Location to Sensor ID mapping
var locationToSensorID = map[string]string{
	"Living Room": "1",
	"Bedroom":     "2",
	"Kitchen":     "3",
}

// Sensor ID to Location mapping
var sensorIDToLocation = map[string]string{
	"1": "Living Room",
	"2": "Bedroom",
	"3": "Kitchen",
}

func main() {
	// Seed random generator
	rand.Seed(time.Now().UnixNano())

	app := fiber.New(fiber.Config{
		AppName: "Temperature API v1.0",
	})

	// Middleware
	app.Use(cors.New())
	app.Use(logger.New())

	// OpenAPI JSON endpoint
	app.Get("/openapi.json", func(c *fiber.Ctx) error {
		return c.SendFile("openapi.json")
	})

	// Swagger UI - serves index.html which loads Swagger UI from CDN
	app.Get("/swagger", func(c *fiber.Ctx) error {
		return c.SendFile("docs/index.html")
	})
	app.Get("/swagger/", func(c *fiber.Ctx) error {
		return c.SendFile("docs/index.html")
	})

	// Health check endpoint
	app.Get("/health", func(c *fiber.Ctx) error {
		return c.JSON(HealthResponse{Status: "ok"})
	})

	// Get temperature endpoint with query parameters
	app.Get("/temperature", getTemperature)

	// Get temperature by ID endpoint (path parameter)
	app.Get("/temperature/:id", getTemperatureByID)

	log.Println("Starting Temperature API on :8081")
	log.Fatal(app.Listen(":8081"))
}

// getTemperatureByID returns random temperature data based on sensor ID from path
func getTemperatureByID(c *fiber.Ctx) error {
	sensorID := c.Params("id")
	location := ""

	// Get location based on sensor ID
	switch sensorID {
	case "1":
		location = "Living Room"
	case "2":
		location = "Bedroom"
	case "3":
		location = "Kitchen"
	default:
		location = "Unknown"
	}

	return c.JSON(getTemperatureResponse(location, sensorID))
}

// getTemperature returns random temperature data based on location or sensor ID query params
func getTemperature(c *fiber.Ctx) error {
	location := c.Query("location", "")
	sensorID := c.Query("sensorId", "")

	// If no location is provided, use a default based on sensor ID
	if location == "" {
		switch sensorID {
		case "1":
			location = "Living Room"
		case "2":
			location = "Bedroom"
		case "3":
			location = "Kitchen"
		default:
			location = "Unknown"
		}
	}

	// If no sensor ID is provided, generate one based on location
	if sensorID == "" {
		switch location {
		case "Living Room":
			sensorID = "1"
		case "Bedroom":
			sensorID = "2"
		case "Kitchen":
			sensorID = "3"
		default:
			sensorID = "0"
		}
	}

	return c.JSON(getTemperatureResponse(location, sensorID))
}

// getTemperatureResponse creates a temperature response with random value
func getTemperatureResponse(location, sensorID string) TemperatureResponse {
	// Generate random temperature between 18.0 and 28.0
	temperature := 18.0 + rand.Float64()*(28.0-18.0)

	return TemperatureResponse{
		Value:       temperature,
		Unit:        "celsius",
		Timestamp:   time.Now(),
		Location:    location,
		Status:      "active",
		SensorID:    sensorID,
		SensorType:  "temperature",
		Description: "Temperature reading from " + location,
	}
}
