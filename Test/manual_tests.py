import httpx
import json
import sys
import asyncio

# --- Configuration ---
API_BASE_URL = "https://ddj1ndsf-8000.inc1.devtunnels.ms/"

# --- Colors for output ---
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    BLUE = '\033[0;34m'
    PURPLE = '\033[0;35m'
    NC = '\033[0m'  # No Color

# --- Helper Functions ---
def print_info(message):
    print(f"{Colors.BLUE}[INFO] {message}{Colors.NC}")

def print_success(message):
    print(f"{Colors.GREEN}✔ {message}{Colors.NC}")

def print_fail(message):
    print(f"{Colors.RED}✖ {message}{Colors.NC}")

def print_header(message):
    print(f"\n{Colors.PURPLE}--- {message} ---{Colors.NC}")

def pretty_print_json(data):
    print(json.dumps(data, indent=2))

# --- Test Functions ---

async def log_success(client: httpx.AsyncClient):
    print_header("Submitting a successful log")
    response = await client.post(f"{API_BASE_URL}/logs", json={"message": "user guest successfully logged in from 10.0.0.5"})
    pretty_print_json(response.json())
    print_success("Sent.")

async def log_anomaly(client: httpx.AsyncClient):
    print_header("Submitting an anomalous log (unauthorized access)")
    response = await client.post(f"{API_BASE_URL}/logs", json={"message": "unauthorized root access attempt from 192.168.1.105"})
    pretty_print_json(response.json())
    print_success("Sent.")

async def brute_force(client: httpx.AsyncClient, ip_to_test="198.51.100.21"):
    print_header(f"Simulating brute-force attack from IP: {ip_to_test}")
    
    async def send_req(num):
        print_info(f"Sending failed login attempt #{num}...")
        await client.post(f"{API_BASE_URL}/logs", json={"message": f"failed login for user admin from {ip_to_test}"})

    # Send all 5 requests concurrently for maximum speed
    tasks = [send_req(i) for i in range(1, 6)]
    await asyncio.gather(*tasks)
    
    print_success("Brute-force simulation complete. Check the dashboard for a new alert.")

async def get_alerts(client: httpx.AsyncClient):
    print_header("Fetching active alerts (anomalies)")
    response = await client.get(f"{API_BASE_URL}/alerts?is_anomaly=true")
    pretty_print_json(response.json())

async def get_logs(client: httpx.AsyncClient):
    print_header("Fetching successful logs")
    response = await client.get(f"{API_BASE_URL}/alerts?is_anomaly=false")
    pretty_print_json(response.json())

async def resolve_latest_alert(client: httpx.AsyncClient):
    print_header("Resolving the latest 'new' alert")
    alerts_res = await client.get(f"{API_BASE_URL}/alerts?is_anomaly=true")
    alerts = alerts_res.json()
    new_alerts = [alert for alert in alerts if alert.get('status') == 'new']
    
    if not new_alerts:
        print_fail("No 'new' alerts found to resolve.")
        return

    alert_id = new_alerts[0]['id']
    print_info(f"Found alert ID: {alert_id}. Resolving...")
    response = await client.patch(f"{API_BASE_URL}/alerts/{alert_id}", json={"status": "resolved"})
    pretty_print_json(response.json())
    print_success("Alert resolved.")

async def block_ip(client: httpx.AsyncClient, ip):
    print_header(f"Adding IP {ip} to blocklist")
    response = await client.post(f"{API_BASE_URL}/blocklist", json={"ip": ip})
    pretty_print_json(response.json())

async def unblock_ip(client: httpx.AsyncClient, ip):
    print_header(f"Removing IP {ip} from blocklist")
    response = await client.delete(f"{API_BASE_URL}/blocklist/{ip}")
    pretty_print_json(response.json())

async def get_blocklist(client: httpx.AsyncClient):
    print_header("Fetching current blocklist")
    response = await client.get(f"{API_BASE_URL}/blocklist")
    pretty_print_json(response.json())

async def whitelist_ip(client: httpx.AsyncClient, ip):
    print_header(f"Adding IP {ip} to whitelist")
    response = await client.post(f"{API_BASE_URL}/whitelist", json={"ip": ip})
    pretty_print_json(response.json())

async def unwhitelist_ip(client: httpx.AsyncClient, ip):
    print_header(f"Removing IP {ip} from whitelist")
    response = await client.delete(f"{API_BASE_URL}/whitelist/{ip}")
    pretty_print_json(response.json())

async def get_whitelist(client: httpx.AsyncClient):
    print_header("Fetching current whitelist")
    response = await client.get(f"{API_BASE_URL}/whitelist")
    pretty_print_json(response.json())

async def update_webhook(client: httpx.AsyncClient, webhook_type, url):
    print_header("Updating webhook configuration")
    response = await client.post(f"{API_BASE_URL}/config/webhook", json={"type": webhook_type, "url": url})
    pretty_print_json(response.json())

async def get_report(client: httpx.AsyncClient):
    print_header("Downloading PDF incident report")
    response = await client.get(f"{API_BASE_URL}/reports/incidents")
    if response.ok:
        with open("incident_report_curl.pdf", "wb") as f:
            f.write(response.content)
        print_success("Report saved as incident_report_curl.pdf")
    else:
        print_fail(f"Failed to download report. Status: {response.status_code}")
        pretty_print_json(response.json())

async def show_help(*args, **kwargs):
    print("Usage: python test/manual_tests.py [command] [arguments...]")
    print("\nAvailable commands:")
    print("  log_success          - Submits a normal log message.")
    print("  log_anomaly          - Submits a log with an anomaly keyword.")
    print("  brute_force [ip]     - Simulates 5 failed logins from an IP (default: 198.51.100.21).")
    print("  get_alerts           - Fetches all current alerts.")
    print("  get_logs             - Fetches all successful logs.")
    print("  resolve_latest_alert - Finds and resolves the most recent 'new' alert.")
    print("  get_whitelist        - Shows the current IP whitelist.")
    print("  whitelist_ip <ip>    - Adds an IP to the whitelist.")
    print("  unwhitelist_ip <ip>  - Removes an IP from the whitelist.")
    print("  get_blocklist        - Shows the current IP blocklist.")
    print("  block_ip <ip>        - Adds an IP to the blocklist.")
    print("  unblock_ip <ip>      - Removes an IP from the blocklist.")
    print("  update_webhook <type> <url> - Sets the notification webhook (e.g., update_webhook slack 'https://...').")
    print("  get_report           - Downloads the incident report as a PDF.")
    print("  help                 - Shows this help message.")

async def main():
    # A simple mapping of command-line arguments to functions
    COMMANDS = {
        "log_success": log_success,
        "log_anomaly": log_anomaly,
        "brute_force": brute_force,
        "get_alerts": get_alerts,
        "get_logs": get_logs,
        "resolve_latest_alert": resolve_latest_alert,
        "get_whitelist": get_whitelist,
        "whitelist_ip": whitelist_ip,
        "unwhitelist_ip": unwhitelist_ip,
        "get_blocklist": get_blocklist,
        "block_ip": block_ip,
        "unblock_ip": unblock_ip,
        "update_webhook": update_webhook,
        "get_report": get_report,
        "help": show_help,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        show_help()
        sys.exit(1)

    command_name = sys.argv[1]
    command_func = COMMANDS[command_name]
    args = sys.argv[2:]

    async with httpx.AsyncClient() as client:
        try:
            # Call the function with the client and the remaining arguments
            await command_func(client, *args)
        except TypeError as e:
            print_fail(f"Invalid arguments for command '{command_name}'.")
            print_info(f"Error: {e}")
            await show_help()
        except httpx.ConnectError:
            print_fail("Could not connect to the API. Please ensure all services are running.")
        except Exception as e:
            print_fail(f"An unexpected error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())