import os
import requests
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email.utils import formatdate
from email import encoders
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000")
SMTP_SERVER = os.environ.get("SMTP_SERVER")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
EMAIL_FROM = os.environ.get("EMAIL_FROM")
EMAIL_TO = os.environ.get("EMAIL_TO", "").split(',')

def send_report():
    """Fetches the PDF report and emails it."""
    if not all([SMTP_SERVER, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM, EMAIL_TO]):
        logger.warning("SMTP environment variables not fully configured. Skipping email.")
        return

    logger.info("Starting scheduled report generation...")
    try:
        # Fetch the PDF report from the API
        response = requests.get(f"{API_BASE_URL}/reports/incidents")
        response.raise_for_status()
        pdf_data = response.content
        logger.info("Successfully fetched PDF report from API.")

        # Create the email
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = ", ".join(EMAIL_TO)
        msg['Date'] = formatdate(localtime=True)
        msg['Subject'] = f"Daily Security Incident Report - {datetime.now().strftime('%Y-%m-%d')}"

        msg.attach(MIMEText("Please find the attached daily security incident report."))

        part = MIMEBase('application', "octet-stream")
        part.set_payload(pdf_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="incident_report.pdf"')
        msg.attach(part)

        # Send the email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        logger.info(f"Successfully sent report to: {', '.join(EMAIL_TO)}")

    except Exception as e:
        logger.error(f"Failed to send scheduled report: {e}", exc_info=True)

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    # Schedule the job to run every day at a specific time (e.g., 08:00 UTC)
    # You can change the schedule by modifying the arguments below.
    # Examples:
    #   - Every day at 11 PM UTC: hour=23, minute=0
    #   - Every 30 minutes: minute='*/30'
    scheduler.add_job(send_report, 'cron', hour=8, minute=0)
    logger.info("Reporter service started. Waiting for scheduled job to run.")
    scheduler.start()