#!/bin/bash

# ==============================================================================
# Manual cURL Test Script for AI/ML SOC Dashboard
# ==============================================================================
# This script provides a set of functions to manually test the API endpoints.
#
# Usage:
#   ./test/curl_tests.sh [command] [argument]
#
# Examples:
#   ./test/curl_tests.sh log_anomaly
#   ./test/curl_tests.sh brute_force
#   ./test/curl_tests.sh block_ip 1.2.3.4
#   ./test/curl_tests.sh help
# ==============================================================================

# --- Configuration ---
API_BASE_URL="http://localhost:8000"

# --- Colors for output ---
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# --- Helper Functions ---
function print_info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

function print_success() {
    echo -e "${GREEN}✔ $1${NC}"
}

function print_fail() {
    echo -e "${RED}✖ $1${NC}"
}

function print_header() {
    echo -e "\n${PURPLE}--- $1 ---${NC}"
}

# --- Test Functions ---

log_success() {
    print_header "Submitting a successful log"
    curl -s -X POST "${API_BASE_URL}/logs" \
        -H "Content-Type: application/json" \
        -d '{"message": "user guest successfully logged in from 10.0.0.5"}' | jq .
    print_success "Sent."
}

log_anomaly() {
    print_header "Submitting an anomalous log (unauthorized access)"
    curl -s -X POST "${API_BASE_URL}/logs" \
        -H "Content-Type: application/json" \
        -d '{"message": "unauthorized root access attempt from 192.168.1.105"}' | jq .
    print_success "Sent."
}

brute_force() {
    IP_TO_TEST=${1:-"198.51.100.21"}
    print_header "Simulating brute-force attack from IP: $IP_TO_TEST"
    for i in {1..5}; do
        print_info "Sending failed login attempt #$i..."
        curl -s -X POST "${API_BASE_URL}/logs" \
            -H "Content-Type: application/json" \
            -d "{\"message\": \"failed login for user admin from ${IP_TO_TEST}\"}" > /dev/null
        sleep 0.2
    done
    print_success "Brute-force simulation complete. Check the dashboard for a new alert."
}

get_alerts() {
    print_header "Fetching active alerts (anomalies)"
    curl -s "${API_BASE_URL}/alerts?is_anomaly=true" | jq .
}

get_logs() {
    print_header "Fetching successful logs"
    curl -s "${API_BASE_URL}/alerts?is_anomaly=false" | jq .
}

resolve_latest_alert() {
    print_header "Resolving the latest 'new' alert"
    ALERT_ID=$(curl -s "${API_BASE_URL}/alerts?is_anomaly=true" | jq -r '.[] | select(.status=="new") | .id' | head -n 1)

    if [ -z "$ALERT_ID" ]; then
        print_fail "No 'new' alerts found to resolve."
        return
    fi

    print_info "Found alert ID: $ALERT_ID. Resolving..."
    curl -s -X PATCH "${API_BASE_URL}/alerts/${ALERT_ID}" \
        -H "Content-Type: application/json" \
        -d '{"status": "resolved"}' | jq .
    print_success "Alert resolved."
}

block_ip() {
    if [ -z "$1" ]; then print_fail "Usage: $0 block_ip <ip_address>"; return; fi
    print_header "Adding IP $1 to blocklist"
    curl -s -X POST "${API_BASE_URL}/blocklist" -H "Content-Type: application/json" -d "{\"ip\": \"$1\"}" | jq .
}

unblock_ip() {
    if [ -z "$1" ]; then print_fail "Usage: $0 unblock_ip <ip_address>"; return; fi
    print_header "Removing IP $1 from blocklist"
    curl -s -X DELETE "${API_BASE_URL}/blocklist/$1" | jq .
}

get_blocklist() {
    print_header "Fetching current blocklist"
    curl -s "${API_BASE_URL}/blocklist" | jq .
}

whitelist_ip() {
    if [ -z "$1" ]; then print_fail "Usage: $0 whitelist_ip <ip_address>"; return; fi
    print_header "Adding IP $1 to whitelist"
    curl -s -X POST "${API_BASE_URL}/whitelist" -H "Content-Type: application/json" -d "{\"ip\": \"$1\"}" | jq .
}

unwhitelist_ip() {
    if [ -z "$1" ]; then print_fail "Usage: $0 unwhitelist_ip <ip_address>"; return; fi
    print_header "Removing IP $1 from whitelist"
    curl -s -X DELETE "${API_BASE_URL}/whitelist/$1" | jq .
}

get_whitelist() {
    print_header "Fetching current whitelist"
    curl -s "${API_BASE_URL}/whitelist" | jq .
}

update_webhook() {
    if [ -z "$2" ]; then print_fail "Usage: $0 update_webhook <slack|discord> <webhook_url>"; return; fi
    print_header "Updating webhook configuration"
    curl -s -X POST "${API_BASE_URL}/config/webhook" \
        -H "Content-Type: application/json" \
        -d "{\"type\": \"$1\", \"url\": \"$2\"}" | jq .
}

get_report() {
    print_header "Downloading PDF incident report"
    curl -s -o incident_report_curl.pdf "${API_BASE_URL}/reports/incidents"
    if [ -f "incident_report_curl.pdf" ]; then
        print_success "Report saved as incident_report_curl.pdf"
    else
        print_fail "Failed to download report."
    fi
}

show_help() {
    echo "Usage: $0 [command]"
    echo ""
    echo "Available commands:"
    echo "  log_success          - Submits a normal log message."
    echo "  log_anomaly          - Submits a log with an anomaly keyword."
    echo "  brute_force [ip]     - Simulates 5 failed logins from an IP (default: 198.51.100.21)."
    echo "  get_alerts           - Fetches all current alerts."
    echo "  get_logs             - Fetches all successful logs."
    echo "  resolve_latest_alert - Finds and resolves the most recent 'new' alert."
    echo "  get_whitelist        - Shows the current IP whitelist."
    echo "  whitelist_ip <ip>    - Adds an IP to the whitelist."
    echo "  unwhitelist_ip <ip>  - Removes an IP from the whitelist."
    echo "  get_blocklist        - Shows the current IP blocklist."
    echo "  block_ip <ip>        - Adds an IP to the blocklist."
    echo "  unblock_ip <ip>      - Removes an IP from the blocklist."
    echo "  update_webhook <type> <url> - Sets the notification webhook (e.g., update_webhook slack 'https://...')."
    echo "  get_report           - Downloads the incident report as a PDF."
    echo "  help                 - Shows this help message."
}

# --- Main Execution Logic ---
COMMAND=$1
shift

if [ -z "$COMMAND" ] || [ "$COMMAND" == "help" ]; then
    show_help
else
    if declare -f "$COMMAND" > /dev/null; then
        "$COMMAND" "$@"
    else
        print_fail "Unknown command: $COMMAND"
        show_help
    fi
fi

```

### How to Use Your New Test Script

1.  **Make it executable**: Open a terminal in your project root and run this command once:
    ```bash
    chmod +x test/curl_tests.sh
    ```
2.  **Run the tests**: You can now call any of the functions defined in the script.

    *   **Get help**:
        ```bash
        ./test/curl_tests.sh help
        ```
    *   **Submit an anomalous log**:
        ```bash
        ./test/curl_tests.sh log_anomaly
        ```
    *   **Simulate a brute-force attack**:
        ```bash
        ./test/curl_tests.sh brute_force
        ```
    *   **Block an IP address**:
        ```bash
        ./test/curl_tests.sh block_ip 1.2.3.4
        ```
    *   **Get all current alerts**:
        ```bash
        ./test/curl_tests.sh get_alerts
        ```

This script gives you a powerful and convenient way to manually interact with and test every part of your API.

<!--
[PROMPT_SUGGESTION]Can we add another chart to the PDF showing the top 5 attacked IPs?[/PROMPT_SUGGESTION]
[PROMPT_SUGGESTION]How can I change the schedule for the email reports?[/PROMPT_SUGGESTION]
-->