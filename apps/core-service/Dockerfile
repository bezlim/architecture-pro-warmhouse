# Build stage
FROM golang:1.22-alpine AS builder

RUN apk add --no-cache git

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o core-service

# Runtime stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

COPY --from=builder /app/core-service .
COPY --from=builder /app/openapi.json ./openapi.json
COPY --from=builder /app/docs ./docs

EXPOSE 8084

CMD ["./core-service"]
