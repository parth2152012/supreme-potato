import requests
import time
import os

# --- Configuration ---
API_BASE_URL = "http://localhost:8000"
PDF_REPORT_PATH = "incident_report_test.pdf"

# --- Helper functions for colored output ---
def print_info(message):
    print(f"\033[94m[INFO] {message}\033[0m")

def print_success(message):
    print(f"\033[92m[SUCCESS] {message}\033[0m")

def print_fail(message):
    print(f"\033[91m[FAIL] {message}\033[0m")

def print_step(step, message):
    print(f"\n{'='*20}\n\033[95mSTEP {step}: {message}\033[0m\n{'='*20}")

def check_api_health():
    """Checks if the API is running before starting tests."""
    print_info("Checking if API is reachable...")
    for i in range(5):
        try:
            response = requests.get(API_BASE_URL)
            if response.status_code == 200:
                print_success("API is up and running.")
                return True
            else:
                print_fail(f"API returned status {response.status_code}. Retrying...")
        except requests.ConnectionError:
            print_fail("Could not connect to the API. Retrying...")
        time.sleep(3)
    print_fail("Could not connect to the API after multiple retries. Please ensure all services are running with 'docker-compose up'.")
    return False

def run_validation():
    """Runs a sequence of validation tests against the SOC dashboard API."""

    if not check_api_health():
        return

    # --- STEP 1: Submit an Anomalous Log ---
    print_step(1, "Submitting an anomalous log")
    try:
        log_payload = {"message": "unauthorized root access attempt from 123.123.123.123"}
        requests.post(f"{API_BASE_URL}/logs", json=log_payload)
        print_success("Anomalous log submitted.")
        print_info("Waiting for ML worker to process...")
        time.sleep(10) # Give time for Kafka and the ML worker to process

        status_res = requests.get(f"{API_BASE_URL}/status").json()
        assert status_res['status'] == 'INCIDENT', f"Status should be INCIDENT, but was {status_res['status']}"
        print_success("System status correctly changed to INCIDENT.")

    except Exception as e:
        print_fail(f"Error during anomalous log test: {e}")
        return

    # --- STEP 2: Test Blocklist Functionality ---
    print_step(2, "Testing IP blocklist functionality")
    blocked_ip = "1.1.1.1"
    try:
        # Add to blocklist
        requests.post(f"{API_BASE_URL}/blocklist", json={"ip": blocked_ip})
        print_success(f"Added {blocked_ip} to blocklist.")
        time.sleep(1)

        # Verify it's in the list
        blocklist_res = requests.get(f"{API_BASE_URL}/blocklist").json()
        assert blocked_ip in blocklist_res['blocklisted_ips'], f"{blocked_ip} not found in blocklist."
        print_success(f"Verified {blocked_ip} is in the blocklist.")

        # Submit a log containing the blocked IP. The API will accept it, but the ML worker should flag it.
        log_payload = {"message": f"This is a test log from a blocked IP {blocked_ip}."}
        res = requests.post(f"{API_BASE_URL}/logs", json=log_payload)
        assert res.status_code == 200, "API should accept the log for processing."
        print_info(f"Submitted log containing blocked IP {blocked_ip}. Waiting for ML worker...")
        time.sleep(5)

        # Verify the ML worker flagged it correctly
        alerts_res = requests.get(f"{API_BASE_URL}/alerts?is_anomaly=true").json()
        blocked_log_alert = next((alert for alert in alerts_res if alert.get("source_ip") == blocked_ip), None)

        assert blocked_log_alert is not None, f"Could not find an alert for the blocked IP {blocked_ip}."
        assert "Log from blocked IP" in blocked_log_alert['reason'], "Alert reason for blocked IP is incorrect."
        print_success("ML worker correctly flagged the log from the blocked IP as an anomaly.")

        # Remove from blocklist
        requests.delete(f"{API_BASE_URL}/blocklist/{blocked_ip}")
        print_success(f"Removed {blocked_ip} from blocklist.")

    except Exception as e:
        print_fail(f"Error during blocklist test: {e}")
        return

    # --- STEP 3: Test Whitelist Functionality ---
    print_step(3, "Testing IP whitelist functionality")
    whitelisted_ip = "8.8.8.8"
    try:
        # Add to whitelist
        requests.post(f"{API_BASE_URL}/whitelist", json={"ip": whitelisted_ip})
        print_success(f"Added {whitelisted_ip} to whitelist.")
        time.sleep(2) # Allow time for config update to propagate
        
        # Verify it's in the list
        whitelist_res = requests.get(f"{API_BASE_URL}/whitelist").json()
        assert whitelisted_ip in whitelist_res['whitelisted_ips'], f"{whitelisted_ip} not found in whitelist."
        print_success(f"Verified {whitelisted_ip} is in the whitelist.")

        # Submit an anomalous log from the whitelisted IP
        stats_before = requests.get(f"{API_BASE_URL}/stats").json()['recent_incidents_24h']
        log_payload = {"message": f"denied access to critical resource from {whitelisted_ip}"}
        requests.post(f"{API_BASE_URL}/logs", json=log_payload)
        print_info(f"Submitted anomalous log from whitelisted IP {whitelisted_ip}. Waiting...")
        time.sleep(5)

        # Verify no new incident was created
        stats_after = requests.get(f"{API_BASE_URL}/stats").json()['recent_incidents_24h']
        assert stats_after == stats_before, "Incident count increased for a whitelisted IP."

        print_success("System correctly ignored anomalous log from whitelisted IP.")

        # Remove from whitelist
        requests.delete(f"{API_BASE_URL}/whitelist/{whitelisted_ip}")
        print_success(f"Removed {whitelisted_ip} from whitelist.")

    except Exception as e:
        print_fail(f"Error during whitelist test: {e}")
        return

    # --- STEP 4: Test Brute-Force Detection ---
    print_step(4, "Testing Brute-Force detection")
    brute_force_ip = "198.51.100.100"
    try:
        print_info(f"Simulating 5 failed login attempts from {brute_force_ip}...")
        for i in range(5):
            log_payload = {"message": f"failed login for user root from {brute_force_ip}"}
            res = requests.post(f"{API_BASE_URL}/logs", json=log_payload)
            assert res.status_code == 200, f"Log submission failed on attempt {i+1}"
            time.sleep(0.2) # Small delay between requests

        print_info("Brute-force simulation complete. Waiting for ML worker to process...")
        time.sleep(5)

        # Verify the ML worker flagged it correctly
        alerts_res = requests.get(f"{API_BASE_URL}/alerts?is_anomaly=true").json()
        brute_force_alert = next((alert for alert in alerts_res if alert.get("source_ip") == brute_force_ip), None)

        assert brute_force_alert is not None, f"Could not find an alert for the brute-force IP {brute_force_ip}."
        assert "Brute-force attempt detected" in brute_force_alert['reason'], "Alert reason for brute-force is incorrect."
        print_success("ML worker correctly flagged the brute-force attempt as a high-priority anomaly.")

    except Exception as e:
        print_fail(f"Error during brute-force test: {e}")
        return

    # --- STEP 5: Resolve an Alert ---
    print_step(5, "Resolving an alert")
    try:
        # Get a list of active alerts
        alerts_res_raw = requests.get(f"{API_BASE_URL}/alerts?is_anomaly=true")
        alerts_res_raw.raise_for_status()
        alerts_res = alerts_res_raw.json()
        
        new_alerts = [alert for alert in alerts_res if alert['status'] == 'new']
        
        if not new_alerts:
            print_fail("Could not find any 'new' alerts to resolve.")
            return

        alert_to_resolve = new_alerts[0]
        alert_id = alert_to_resolve['id']
        print_info(f"Found alert {alert_id} to resolve.")

        # Resolve it
        requests.patch(f"{API_BASE_URL}/alerts/{alert_id}", json={"status": "resolved"})
        print_success(f"Resolved alert {alert_id}.")
        time.sleep(2)

        # Verify its status changed
        alerts_after_res = requests.get(f"{API_BASE_URL}/alerts?is_anomaly=true").json()
        resolved_alert = next((alert for alert in alerts_after_res if alert['id'] == alert_id), None)
        
        assert resolved_alert is not None, "Resolved alert disappeared from the list."
        assert resolved_alert['status'] == 'resolved', "Alert status was not updated to 'resolved'."
        print_success("Verified alert status is now 'resolved'.")

    except Exception as e:
        print_fail(f"Error during alert resolution test: {e}")
        return

    # --- STEP 6: Test PDF Report Generation ---
    print_step(6, "Testing PDF report generation")
    try:
        response = requests.get(f"{API_BASE_URL}/reports/incidents")
        response.raise_for_status()

        # Check if the content is a PDF
        assert 'application/pdf' in response.headers.get('Content-Type', ''), "Response is not a PDF."
        
        # Check if the file has a valid PDF header
        assert response.content.startswith(b'%PDF-'), "File does not appear to be a valid PDF."

        # Save the PDF for manual inspection
        with open(PDF_REPORT_PATH, 'wb') as f:
            f.write(response.content)
        
        print_success(f"Successfully downloaded PDF report. Saved as '{PDF_REPORT_PATH}'.")

    except Exception as e:
        print_fail(f"Error during PDF report test: {e}")
        return


    print("\n" + "="*40)
    print_success("All validation steps completed successfully!")
    print("="*40 + "\n")

if __name__ == "__main__":
    run_validation()