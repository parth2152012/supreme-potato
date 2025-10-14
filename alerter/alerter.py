import asyncio
import json
import os
import logging
import httpx
from aiokafka import AIOKafkaConsumer

import redis.asyncio as redis
# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
KAFKA_ALERTS_TOPIC = "high-priority-alerts"
KAFKA_CONFIG_TOPIC = "alerter-config-updates"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
WEBHOOK_CONFIG_REDIS_KEY = "webhook_config"

# Global state for webhook configuration, initialized from environment variables
WEBHOOK_CONFIG = {
    "type": os.environ.get("WEBHOOK_TYPE", "slack"),  # Default to slack
    "url": os.environ.get("WEBHOOK_URL")
}

async def send_slack_notification(message: dict):
    """Formats and sends a notification to a Slack webhook."""
    global WEBHOOK_CONFIG
    webhook_url = WEBHOOK_CONFIG.get("url")
    webhook_type = WEBHOOK_CONFIG.get("type")

    if not webhook_url:
        logger.warning(f"Webhook URL is not configured. Skipping notification.")
        return

    reason = message.get("reason", "No reason provided")
    log_message = message.get("message", "N/A")
    source_ip = message.get("source_ip", "N/A")

    if webhook_type == "discord":
        # Discord uses embeds for rich formatting
        payload = {
            "embeds": [{
                "title": f"🚨 Security Alert: {reason}",
                "color": 15158332, # Red
                "fields": [
                    {"name": "Source IP", "value": f"`{source_ip}`", "inline": True},
                    {"name": "Original Log", "value": f"```{log_message}```"}
                ]
            }]
        }
    else:  # Default to Slack format
        payload = {
            "text": f"🚨 *Security Alert: {reason}*\n" \
                    f"> *Source IP:* `{source_ip}`\n" \
                    f"> *Original Log:* `{log_message}`"
        }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
            logger.info(f"Successfully sent alert to Slack: {reason}")
    except httpx.RequestError as e:
        logger.error(f"Could not send alert to Slack. Error: {e}")

async def connect_with_retry(connect_func, service_name, max_retries=15, delay=5):
    """Tries to connect to a service with an async retry mechanism."""
    for i in range(max_retries):
        try:
            logger.info(f"Attempting to connect to {service_name}...")
            connection = await connect_func()
            logger.info(f"Successfully connected to {service_name}.")
            return connection
        except Exception as e:
            logger.warning(f"Failed to connect to {service_name}: {e}. Retrying in {delay}s... ({i+1}/{max_retries})")
            await asyncio.sleep(delay)
    logger.error(f"Could not connect to {service_name} after {max_retries} retries. Exiting.")
    exit(1)

async def main():
    global WEBHOOK_CONFIG

    # --- Connect to Redis to fetch initial config ---
    async def connect_redis():
        client = redis.from_url(REDIS_URL, decode_responses=True)
        await client.ping()
        return client
    
    redis_client = await connect_with_retry(connect_redis, "Redis")
    
    # Fetch initial config from Redis, overriding environment variables if present
    saved_config = await redis_client.hgetall(WEBHOOK_CONFIG_REDIS_KEY)
    if saved_config:
        WEBHOOK_CONFIG["type"] = saved_config.get("type", "slack")
        WEBHOOK_CONFIG["url"] = saved_config.get("url")
        logger.info(f"Loaded webhook config from Redis. Type: {WEBHOOK_CONFIG['type']}")
    
    if not WEBHOOK_CONFIG.get("url"):
        logger.warning("No webhook URL is configured (checked environment variables and Redis). Alerter will not send notifications until configured via the UI.")

    async def connect_kafka():
        topics = [KAFKA_ALERTS_TOPIC, KAFKA_CONFIG_TOPIC]
        consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=KAFKA_BROKER,
            group_id='alerter-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            enable_auto_commit=True,      # Enable auto-committing offsets
            auto_commit_interval_ms=5000  # Commit every 5 seconds
        )
        await consumer.start()
        return consumer

    consumer = await connect_with_retry(connect_kafka, "Kafka Consumer")

    try:
        logger.info("Alerter service started. Waiting for high-priority alerts...")
        async for msg in consumer:
            if msg.topic == KAFKA_ALERTS_TOPIC:
                logger.info(f"Received high-priority alert: {msg.value}")
                await send_slack_notification(msg.value)
            elif msg.topic == KAFKA_CONFIG_TOPIC:
                config_data = msg.value
                if config_data.get("type") == "webhook_update":
                    WEBHOOK_CONFIG["type"] = config_data.get("webhook_type", "slack")
                    WEBHOOK_CONFIG["url"] = config_data.get("url")
                    logger.info(f"Updated webhook configuration. Type: {WEBHOOK_CONFIG['type']}, URL: {WEBHOOK_CONFIG['url']}")

    finally:
        logger.info("Alerter shutting down...")
        if consumer:
            await consumer.stop()
        if redis_client:
            await redis_client.close()

if __name__ == "__main__":
    asyncio.run(main())