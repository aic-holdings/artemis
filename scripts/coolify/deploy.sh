#!/bin/bash
# Artemis Coolify Deployment Script
# Deploys Artemis to Coolify with proper database linking
#
# Prerequisites:
#   - COOLIFY_TOKEN: API token with read/write permissions
#   - COOLIFY_URL: Base URL of Coolify instance (default: http://80.209.241.157:8000)
#
# Usage:
#   COOLIFY_TOKEN=xxx ./scripts/coolify/deploy.sh
#
# This script will:
#   1. Check if artemis-db PostgreSQL exists, create if not
#   2. Create or update the Artemis application
#   3. Link app to database via environment variables
#   4. Trigger deployment

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Configuration - These match hostkey-server's Coolify setup
# See: hostkey-server/docs/COOLIFY_OPERATIONS.md for details
COOLIFY_URL="${COOLIFY_URL:-http://80.209.241.157:8000}"
PROJECT_UUID="jokw0ssk0kckok4c8o0ko0gs"      # AIC Apps project
ENVIRONMENT_NAME="production"
SERVER_UUID="pwkck048sooogwk804c04cko"       # localhost server
GITHUB_APP_UUID="ow0gw0840008okgo44cwsk4w"   # aic-holdings GitHub App

# Artemis-specific config
APP_NAME="artemis"
APP_DOMAIN="artemis.jettaintelligence.com"
GIT_REPO="aic-holdings/artemis"
GIT_BRANCH="main"
DB_NAME="artemis-db"

# Check prerequisites
check_prereqs() {
    if [ -z "$COOLIFY_TOKEN" ]; then
        log_error "COOLIFY_TOKEN not set"
        echo ""
        echo "Get a token from Coolify: Settings → API Tokens"
        echo "Then run: COOLIFY_TOKEN=xxx $0"
        exit 1
    fi

    if ! command -v curl &> /dev/null || ! command -v jq &> /dev/null; then
        log_error "curl and jq are required"
        exit 1
    fi
}

# API helper
api() {
    local method=$1
    local endpoint=$2
    local data=$3

    if [ -n "$data" ]; then
        curl -s -X "$method" \
            -H "Authorization: Bearer $COOLIFY_TOKEN" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "${COOLIFY_URL}/api/v1${endpoint}"
    else
        curl -s -X "$method" \
            -H "Authorization: Bearer $COOLIFY_TOKEN" \
            "${COOLIFY_URL}/api/v1${endpoint}"
    fi
}

# Check if database exists
check_database() {
    log_info "Checking for artemis-db..."

    local dbs=$(api GET "/databases")
    local db_uuid=$(echo "$dbs" | jq -r '.[] | select(.name=="artemis-db") | .uuid' 2>/dev/null)

    if [ -n "$db_uuid" ] && [ "$db_uuid" != "null" ]; then
        log_info "Database found: $db_uuid"
        echo "$db_uuid"
    else
        echo ""
    fi
}

# Create database if not exists
ensure_database() {
    local db_uuid=$(check_database)

    if [ -z "$db_uuid" ]; then
        log_info "Creating artemis-db..."

        local result=$(api POST "/databases/postgresql" '{
            "project_uuid": "'"$PROJECT_UUID"'",
            "environment_name": "'"$ENVIRONMENT_NAME"'",
            "server_uuid": "'"$SERVER_UUID"'",
            "name": "artemis-db",
            "description": "PostgreSQL database for Artemis AI Management Platform",
            "postgres_user": "artemis",
            "postgres_password": "artemis_prod_2024",
            "postgres_db": "artemis",
            "instant_deploy": true
        }')

        db_uuid=$(echo "$result" | jq -r '.uuid')

        if [ -z "$db_uuid" ] || [ "$db_uuid" == "null" ]; then
            log_error "Failed to create database: $result"
            exit 1
        fi

        log_info "Database created: $db_uuid"
        log_info "Waiting for database to start..."
        sleep 30
    fi

    echo "$db_uuid"
}

# Check if application exists
check_application() {
    log_info "Checking for artemis application..."

    local apps=$(api GET "/applications")
    local app_uuid=$(echo "$apps" | jq -r '.[] | select(.name=="artemis") | .uuid' 2>/dev/null)

    if [ -n "$app_uuid" ] && [ "$app_uuid" != "null" ]; then
        log_info "Application found: $app_uuid"
        echo "$app_uuid"
    else
        echo ""
    fi
}

# Create application
create_application() {
    local db_uuid=$1

    log_info "Creating artemis application..."

    # Internal database URL for container networking
    local db_url="postgresql+asyncpg://artemis:artemis_prod_2024@${db_uuid}:5432/artemis"

    local result=$(api POST "/applications/private-github-app" '{
        "project_uuid": "'"$PROJECT_UUID"'",
        "environment_name": "'"$ENVIRONMENT_NAME"'",
        "server_uuid": "'"$SERVER_UUID"'",
        "github_app_uuid": "'"$GITHUB_APP_UUID"'",
        "git_repository": "'"$GIT_REPO"'",
        "git_branch": "'"$GIT_BRANCH"'",
        "build_pack": "dockerfile",
        "ports_exposes": "8000",
        "name": "'"$APP_NAME"'",
        "description": "Artemis AI Management Platform - LLM Proxy with Usage Tracking",
        "domains": "https://'"$APP_DOMAIN"'",
        "instant_deploy": false
    }')

    local app_uuid=$(echo "$result" | jq -r '.uuid')

    if [ -z "$app_uuid" ] || [ "$app_uuid" == "null" ]; then
        log_error "Failed to create application: $result"
        exit 1
    fi

    log_info "Application created: $app_uuid"
    echo "$app_uuid"
}

# Set environment variables
set_env_vars() {
    local app_uuid=$1
    local db_uuid=$2

    log_info "Setting environment variables..."

    # Database URL using internal Docker networking
    local db_url="postgresql+asyncpg://artemis:artemis_prod_2024@${db_uuid}:5432/artemis"

    # Note: SECRET_KEY and ENCRYPTION_KEY should be set manually in Coolify UI
    # for security. These are placeholders that MUST be changed.

    api PATCH "/applications/$app_uuid/envs" '{
        "key": "DATABASE_URL",
        "value": "'"$db_url"'",
        "is_preview": false
    }' > /dev/null

    api PATCH "/applications/$app_uuid/envs" '{
        "key": "JWT_ALGORITHM",
        "value": "HS256",
        "is_preview": false
    }' > /dev/null

    api PATCH "/applications/$app_uuid/envs" '{
        "key": "JWT_EXPIRATION_HOURS",
        "value": "24",
        "is_preview": false
    }' > /dev/null

    log_warn "IMPORTANT: Set SECRET_KEY and ENCRYPTION_KEY manually in Coolify UI!"
    log_warn "These are sensitive and should not be in scripts."
}

# Deploy application
deploy_application() {
    local app_uuid=$1

    log_info "Triggering deployment..."

    local result=$(api GET "/applications/$app_uuid/restart")
    local deploy_uuid=$(echo "$result" | jq -r '.deployment_uuid')

    if [ -n "$deploy_uuid" ] && [ "$deploy_uuid" != "null" ]; then
        log_info "Deployment queued: $deploy_uuid"
        log_info "Monitor at: ${COOLIFY_URL}/project/${PROJECT_UUID}/environment/${ENVIRONMENT_NAME}/application/${app_uuid}"
    else
        log_error "Failed to trigger deployment: $result"
    fi
}

# Main
main() {
    log_info "Artemis Coolify Deployment"
    echo "================================"
    echo ""

    check_prereqs

    # Ensure database exists
    local db_uuid=$(ensure_database)

    # Check or create application
    local app_uuid=$(check_application)

    if [ -z "$app_uuid" ]; then
        app_uuid=$(create_application "$db_uuid")
        set_env_vars "$app_uuid" "$db_uuid"
    fi

    # Deploy
    deploy_application "$app_uuid"

    echo ""
    log_info "Deployment complete!"
    echo ""
    echo "Application URL: https://${APP_DOMAIN}"
    echo "Database UUID:   ${db_uuid}"
    echo "Application UUID: ${app_uuid}"
    echo ""
    echo "Next steps:"
    echo "  1. Set SECRET_KEY in Coolify UI (Settings → Environment Variables)"
    echo "  2. Set ENCRYPTION_KEY in Coolify UI"
    echo "  3. Add DNS record: ${APP_DOMAIN} → 80.209.241.157"
}

main "$@"
