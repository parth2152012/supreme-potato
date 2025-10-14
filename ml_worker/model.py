from elasticsearch import AsyncElasticsearch
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
import json
import os
import re
import redis.asyncio as redis
import logging
import asyncio, time
from typing import Optional

# --- Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# A simple regex to find the first IP address in a string
IP_REGEX = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')

# --- Configuration ---
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
KAFKA_LOGS_TOPIC = "logs"
KAFKA_ALERTS_TOPIC = "high-priority-alerts"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
ES_INDEX_NAME = "processed_logs"
CONFIG_UPDATES_TOPIC = "config-updates"

# Load configurable values from environment variables
ANOMALY_KEYWORDS = os.environ.get("ANOMALY_KEYWORDS", "error,failed,denied,exception,attack").split(',')
FAILED_LOGIN_KEYWORDS = ["failed login", "authentication failure"]
BRUTE_FORCE_THRESHOLD = int(os.environ.get("BRUTE_FORCE_THRESHOLD", 5))
BRUTE_FORCE_WINDOW_SECONDS = int(os.environ.get("BRUTE_FORCE_WINDOW_SECONDS", 300)) # 5 minutes
SPIKE_DETECTION_WINDOW_SECONDS = int(os.environ.get("SPIKE_DETECTION_WINDOW_SECONDS", 60)) # 1 minute
SPIKE_DETECTION_THRESHOLD_MULTIPLIER = float(os.environ.get("SPIKE_DETECTION_THRESHOLD_MULTIPLIER", 10.0))

WHITELISTED_IPS = set(os.environ.get("WHITELISTED_IPS", "192.168.1.100,10.0.0.1").split(','))

# Define which anomaly reasons are considered high-priority enough to send a real-time alert
HIGH_PRIORITY_REASON_PREFIXES = [
    "Brute-force attempt detected",
    "High log volume detected"
    "High log volume detected",
    "Log from blocked IP"
]

def is_anomaly(log_message: str) -> bool:
    """Checks if a log message contains any anomaly keywords."""
    return any(keyword in log_message.lower() for keyword in ANOMALY_KEYWORDS)

def handle_config_update(log_data: dict):
    """Updates the in-memory IP whitelist based on a config message."""
    update_action = log_data.get("action")
    ip_to_update = log_data.get("ip")
    if update_action == "add" and ip_to_update:
        WHITELISTED_IPS.add(ip_to_update)
        logger.info(f"Added '{ip_to_update}' to whitelist. Current whitelist size: {len(WHITELISTED_IPS)}")
    elif update_action == "remove" and ip_to_update in WHITELISTED_IPS:
        WHITELISTED_IPS.remove(ip_to_update)
        logger.info(f"Removed '{ip_to_update}' from whitelist. Current whitelist size: {len(WHITELISTED_IPS)}")

async def detect_brute_force(message: str, ip_address: str, redis_client: redis.Redis) -> Optional[dict]:
    """Detects brute-force login attempts."""
    is_failed_login = any(keyword in message.lower() for keyword in FAILED_LOGIN_KEYWORDS)
    if not (ip_address and is_failed_login):
        return None

    redis_key = f"failed_logins:{ip_address}"
    count = await redis_client.incr(redis_key)
    if count == 1:
        await redis_client.expire(redis_key, BRUTE_FORCE_WINDOW_SECONDS)
    
    logger.info(f"Failed login from {ip_address}. Count: {count}")

    if count >= BRUTE_FORCE_THRESHOLD:
        await redis_client.delete(redis_key) # Reset counter to prevent spamming alerts
        return {
            "is_anomaly": True,
            "reason": "Brute-force attempt detected"
        }
    # If it's a failed login but hasn't hit the threshold, still flag it as an anomaly.
    return {
        "is_anomaly": True,
        "reason": f"Failed login attempt detected ({count}/{BRUTE_FORCE_THRESHOLD})"
    }
    # If it's a failed login but hasn't hit the threshold, still flag it as an anomaly for logging.
    if is_failed_login:
        return {
            "is_anomaly": True,
            "reason": f"Failed login attempt detected ({count}/{BRUTE_FORCE_THRESHOLD})"
        }
    return None

async def detect_keyword_anomaly(message: str) -> Optional[dict]:
    """Detects anomalies based on a list of keywords."""
    if is_anomaly(message):
        return {
            "is_anomaly": True,
            "reason": "Log contains anomalous keyword."
        }
    return None

async def detect_traffic_spike(redis_client: redis.Redis) -> Optional[dict]:
    """
    Detects a general spike in log volume using a moving average and standard deviation.
    """
    current_minute = int(time.time() / 60)
    current_minute_key = f"log_volume:{current_minute}"
    
    # Increment the count for the current minute window
    current_count = await redis_client.incr(current_minute_key)
    if current_count == 1:
        # Set expiry for the key to clear it out after it's no longer needed
        await redis_client.expire(current_minute_key, SPIKE_DETECTION_WINDOW_SECONDS * 2)

    # Get historical data from the last hour (60 minutes)
    historical_keys = [f"log_volume:{current_minute - i}" for i in range(1, 61)]
    historical_counts = await redis_client.mget(historical_keys)
    # Filter out None values and convert to int. These are minutes where no logs were received.
    historical_counts = [int(c) for c in historical_counts if c is not None]

    # We need at least a few data points to establish a baseline
    if len(historical_counts) < 10:
        return None # Not enough data for a reliable baseline

    # Calculate average and standard deviation
    avg_count = sum(historical_counts) / len(historical_counts)
    sum_sq_diff = sum((c - avg_count) ** 2 for c in historical_counts)
    std_dev = (sum_sq_diff / len(historical_counts)) ** 0.5

    # A low standard deviation can be too sensitive, so we establish a minimum floor.
    # Also, set a minimum threshold to avoid alerts on very low traffic.
    min_std_dev = 5
    min_threshold = 20
    effective_std_dev = max(std_dev, min_std_dev)
    
    threshold = avg_count + (effective_std_dev * SPIKE_DETECTION_THRESHOLD_MULTIPLIER)
    threshold = max(threshold, min_threshold)

    if current_count > threshold:
        # To avoid spamming, we only alert once when the threshold is crossed.
        alert_flag_key = "spike_alert_sent"
        if not await redis_client.get(alert_flag_key):
            await redis_client.set(alert_flag_key, 1, ex=SPIKE_DETECTION_WINDOW_SECONDS)
            return {
                "is_anomaly": True,
                "reason": f"High log volume detected: {current_count} logs in the last minute (threshold: {int(threshold)})."
            }
    return None


async def analyze_log(message: str, redis_client: redis.Redis) -> dict:
    """
    Analyzes a log message for anomalies and returns an analysis dictionary.
    It runs through a chain of detection functions.
    """
    ip_match = IP_REGEX.search(message)
    ip_address = ip_match.group(0) if ip_match else None

    # Highest priority: check if the IP is on the blocklist
    if ip_address and await redis_client.sismember("blocked_ips", ip_address):
        logger.warning(f"Log received from a blocked IP: {ip_address}. Flagging as anomaly.")
        return {"is_anomaly": True, "reason": f"Log from blocked IP {ip_address}.", "source_ip": ip_address}

    if ip_address and ip_address in WHITELISTED_IPS:
        logger.info(f"IP {ip_address} is whitelisted. Ignoring anomaly check.")
        return {"is_anomaly": False, "reason": f"IP {ip_address} is whitelisted.", "source_ip": ip_address}

    # --- Detection Chain ---
    # First, check for content-based anomalies
    content_detectors = [
        await detect_brute_force(message, ip_address, redis_client),
        await detect_keyword_anomaly(message)
    ]
    analysis_result = next(
        (result for result in content_detectors if result is not None), 
        None
    )

    # Always check for traffic spikes, regardless of other findings.
    # This is a meta-analysis of log volume.
    spike_result = await detect_traffic_spike(redis_client)
    if spike_result:
        # If a content-based anomaly was already found, just add the spike info.
        # Otherwise, the spike is the primary anomaly.
        if not analysis_result:
            analysis_result = spike_result
        elif analysis_result.get("is_anomaly"):
            analysis_result["reason"] += f" | {spike_result['reason']}"

    # Default response if no anomaly is detected
    if not analysis_result:
        analysis_result = {"is_anomaly": False, "reason": "No anomaly detected."}

    analysis_result["source_ip"] = ip_address
    return analysis_result


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

async def ensure_es_index_exists(client: AsyncElasticsearch, index_name: str):
    """Checks if an Elasticsearch index exists and creates it if it doesn't."""
    try:
        if not await client.indices.exists(index=index_name):
            logger.info(f"ML Worker: Index '{index_name}' not found. Creating it with mappings...")
            mappings = {
                "properties": {
                    "message": {"type": "text"},
                    "timestamp": {"type": "date", "format": "epoch_second"},
                    "status": {"type": "keyword"},
                    "is_anomaly": {"type": "boolean"},
                    "reason": {
                        "type": "text",
                        "fields": {
                            "keyword": {
                                "type": "keyword",
                                "ignore_above": 256
                            }
                        }
                    },
                    "source_ip": {"type": "ip"}
                }
            }
            await client.indices.create(index=index_name, mappings=mappings)
            logger.info(f"ML Worker: Index '{index_name}' created with explicit mappings.")
    except Exception as e:
        logger.error(f"ML Worker: Error checking or creating index '{index_name}': {e}")

logger.info("ML Worker starting...")

async def main():
    # Define async connection functions
    async def connect_es():
        es_client = AsyncElasticsearch(hosts=[ELASTICSEARCH_URL])
        await es_client.ping()
        return es_client

    async def connect_redis():
        redis_client = redis.from_url(REDIS_URL)
        await redis_client.ping()
        return redis_client

    async def connect_kafka():
        topics = [KAFKA_LOGS_TOPIC, CONFIG_UPDATES_TOPIC]
        consumer = AIOKafkaConsumer(
            *topics, # Unpack the list of topics into arguments
            bootstrap_servers=KAFKA_BROKER,
            group_id='ml-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
        await consumer.start()
        return consumer

    async def connect_kafka_producer():
        producer = AIOKafkaProducer(
            bootstrap_servers=KAFKA_BROKER,
            value_serializer=lambda v: json.dumps(v).encode('utf-8')
        )
        await producer.start()
        return producer

    # Connect to services with retry logic
    es = await connect_with_retry(connect_es, "Elasticsearch")
    redis_client = await connect_with_retry(connect_redis, "Redis")
    
    # Ensure the index exists before starting the consumer
    await ensure_es_index_exists(es, ES_INDEX_NAME)
    consumer = await connect_with_retry(connect_kafka, "Kafka")
    producer = await connect_with_retry(connect_kafka_producer, "Kafka Producer")

    logger.info("ML Worker connected to all services. Waiting for messages...")

    try:
        async for msg in consumer:
            try:
                log_data = msg.value
                
                if msg.topic == CONFIG_UPDATES_TOPIC:
                    handle_config_update(log_data)
                    continue

                if msg.topic == KAFKA_LOGS_TOPIC:
                    original_message = log_data.get("message", "")
                    if not original_message:
                        continue

                    analysis = await analyze_log(original_message, redis_client)

                    # Create the document for Elasticsearch, preserving the original message
                    processed_document = {
                        "message": original_message,
                        "timestamp": int(time.time()),
                        "status": "new",
                        "is_anomaly": analysis["is_anomaly"],
                        "reason": analysis["reason"],
                        "source_ip": analysis["source_ip"]
                    }

                    # Index the document in Elasticsearch
                    await es.index(index=ES_INDEX_NAME, document=processed_document)
                    logger.info(f"Processed log. Anomaly: {analysis['is_anomaly']}. Reason: {analysis['reason']}")

                    # If it's a high-priority alert, publish it to the alerts topic
                    is_high_priority = any(analysis["reason"].startswith(prefix) for prefix in HIGH_PRIORITY_REASON_PREFIXES)

                    if analysis["is_anomaly"] and is_high_priority:
                        await producer.send_and_wait(KAFKA_ALERTS_TOPIC, processed_document)
                        logger.warning(f"Published high-priority alert to '{KAFKA_ALERTS_TOPIC}' topic. Reason: {analysis['reason']}")
            except Exception as e:
                logger.error(f"Error processing message: {msg.value}. Error: {e}", exc_info=True)
    finally:
        logger.info("ML Worker shutting down. Closing connections...")
        await asyncio.gather(
            consumer.stop() if 'consumer' in locals() and consumer else asyncio.sleep(0),
            producer.stop() if 'producer' in locals() and producer else asyncio.sleep(0),
            es.close() if 'es' in locals() and es else asyncio.sleep(0)
        )
        if 'redis_client' in locals() and redis_client:
            await redis_client.disconnect()

        # A small sleep to allow connections to close gracefully before the loop terminates
        await asyncio.sleep(0.1)
        logger.info("ML Worker shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())
