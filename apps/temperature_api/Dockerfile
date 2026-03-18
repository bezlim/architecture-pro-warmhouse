# Build stage
FROM golang:1.22-alpine AS builder

# Install git for fetching dependencies (if needed)
RUN apk add --no-cache git

# Set working directory
WORKDIR /app

# Copy go.mod and go.sum files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy the source code
COPY . .

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -o temperature-api

# Runtime stage
FROM alpine:latest

# Install necessary runtime dependencies
RUN apk --no-cache add ca-certificates tzdata

# Set working directory
WORKDIR /app

# Copy the binary and docs from builder stage
COPY --from=builder /app/temperature-api .
COPY --from=builder /app/docs ./docs
COPY --from=builder /app/openapi.json ./openapi.json

# Expose the port the app runs on
EXPOSE 8081

# Command to run the application
CMD ["./temperature-api"]
