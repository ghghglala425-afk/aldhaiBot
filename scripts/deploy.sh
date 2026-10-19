#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Deploy/Update Script for Cyber Academy Bot on Oracle Cloud
# Run this to deploy or update the application
# =============================================================================

PROJECT_DIR="$HOME/bot-project"
COMPOSE_FILE="docker-compose.prod.yml"

echo "=========================================="
echo "Deploying Cyber Academy Bot"
echo "=========================================="

cd "$PROJECT_DIR"

# Pull latest images
echo "Pulling latest base images..."
docker compose -f "$COMPOSE_FILE" pull

# Build and start
echo "Building and starting services..."
docker compose -f "$COMPOSE_FILE" up -d --build --remove-orphans

# Wait for services to be healthy
echo "Waiting for services to be healthy..."
sleep 10

# Check status
echo "Service status:"
docker compose -f "$COMPOSE_FILE" ps

# Show logs
echo ""
echo "Recent logs:"
docker compose -f "$COMPOSE_FILE" logs --tail=20

echo ""
echo "Deployment complete!"
echo "Check logs: docker compose -f $COMPOSE_FILE logs -f"