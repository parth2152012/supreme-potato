from aiokafka import AIOKafkaConsumer
from elasticsearch import AsyncElasticsearch
import json
import os
import re
import redis.asyncio as redis
import asyncio

# A simple regex to find the first IP address in a string
IP_REGEX = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')

# --- Configuration ---
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
KAFKA_LOGS_TOPIC = "logs"
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
ES_INDEX_NAME = "processed_logs"
CONFIG_UPDATES_TOPIC = "config-updates"

# Load configurable values from environment variables
ANOMALY_KEYWORDS = os.environ.get("ANOMALY_KEYWORDS", "error,failed,denied,exception,attack").split(',')
FAILED_LOGIN_KEYWORDS = ["failed login", "authentication failure"]
BRUTE_FORCE_THRESHOLD = 5  # Number of failed logins to trigger a brute-force alert
BRUTE_FORCE_WINDOW_SECONDS = 300  # 5 minutes

WHITELISTED_IPS = set(os.environ.get("WHITELISTED_IPS", "192.168.1.100,10.0.0.1").split(','))

def is_anomaly(log_message: str) -> bool:
    """Checks if a log message contains any anomaly keywords."""
    return any(keyword in log_message.lower() for keyword in ANOMALY_KEYWORDS)

async def connect_with_retry(connect_func, service_name, max_retries=15, delay=5):
    """Tries to connect to a service with an async retry mechanism."""
    for i in range(max_retries):
        try:
            print(f"ML Worker: Attempting to connect to {service_name}...")
            connection = await connect_func()
            print(f"Successfully connected to {service_name}.")
            return connection
        except Exception as e:
            print(f"ML Worker: Failed to connect to {service_name}: {e}. Retrying in {delay}s... ({i+1}/{max_retries})")
            await asyncio.sleep(delay)
    print(f"ML Worker: Could not connect to {service_name} after {max_retries} retries. Exiting.")
    exit(1)

print("ML Worker starting...")

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
        consumer = AIOKafkaConsumer(
            KAFKA_LOGS_TOPIC, CONFIG_UPDATES_TOPIC, # Subscribe to both topics
            bootstrap_servers=KAFKA_BROKER,
            group_id='ml-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
        await consumer.start()
        return consumer

    # Connect to services with retry logic
    es = await connect_with_retry(connect_es, "Elasticsearch")
    redis_client = await connect_with_retry(connect_redis, "Redis")
    consumer = await connect_with_retry(connect_kafka, "Kafka")

    print("ML Worker connected to Kafka. Waiting for logs...")

    try:
        async for msg in consumer:
            log_data = msg.value
            
            # --- Dynamic Whitelist Update ---
            if msg.topic == CONFIG_UPDATES_TOPIC:
                update_action = log_data.get("action")
                ip_to_update = log_data.get("ip")
                if update_action == "add" and ip_to_update:
                    WHITELISTED_IPS.add(ip_to_update)
                    print(f"[ML WORKER] Added '{ip_to_update}' to whitelist. Current whitelist: {WHITELISTED_IPS}")
                elif update_action == "remove" and ip_to_update in WHITELISTED_IPS:
                    WHITELISTED_IPS.remove(ip_to_update)
                    print(f"[ML WORKER] Removed '{ip_to_update}' from whitelist. Current whitelist: {WHITELISTED_IPS}")
                continue # Skip to next message

            # --- Log Processing ---
            if msg.topic == KAFKA_LOGS_TOPIC:
                message = log_data.get("message", "")
                log_data['status'] = 'new'
                log_data['timestamp'] = int(asyncio.get_running_loop().time())

                # --- Anomaly Detection with Whitelisting ---
                ip_match = IP_REGEX.search(message)
                ip_address = ip_match.group(0) if ip_match else None

                if ip_address and ip_address in WHITELISTED_IPS:
                    log_data['is_anomaly'] = False
                    print(f"[ML WORKER] IP {ip_address} is whitelisted. Ignoring anomaly check.")
                else:
                    # --- Brute-Force Detection ---
                    is_failed_login = any(keyword in message.lower() for keyword in FAILED_LOGIN_KEYWORDS)
                    
                    if ip_address and is_failed_login:
                        # Increment failed login counter in Redis
                        count = await redis_client.incr(f"failed_logins:{ip_address}")
                        # Set expiration only on the first attempt in a window
                        if count == 1:
                            await redis_client.expire(f"failed_logins:{ip_address}", BRUTE_FORCE_WINDOW_SECONDS)
                        
                        print(f"[ML WORKER] Failed login from {ip_address}. Count: {count}")

                        if count >= BRUTE_FORCE_THRESHOLD:
                            # This is a brute-force attack
                            log_data['is_anomaly'] = True
                            log_data['reason'] = f"Brute-force attempt detected from {ip_address} ({count} attempts)."
                            # Reset counter to prevent spamming alerts
                            await redis_client.delete(f"failed_logins:{ip_address}")
                        else:
                            # It's a failed login, but not yet a brute-force attack. Flag as a low-level anomaly.
                            log_data['is_anomaly'] = True
                            log_data['reason'] = "Single failed login attempt."
                    else:
                        # --- Standard Keyword-based Anomaly Detection ---
                        is_keyword_anomaly = is_anomaly(message)
                        log_data['is_anomaly'] = is_keyword_anomaly
                        if is_keyword_anomaly:
                            log_data['reason'] = "Log contains anomalous keyword."

                # Index the processed log into Elasticsearch
                await es.index(index=ES_INDEX_NAME, document=log_data)
                print(f"[ML WORKER] Processed and indexed log. Anomaly: {log_data.get('is_anomaly', False)}")
    finally:
        await consumer.stop()
        await es.close()

if __name__ == "__main__":
    asyncio.run(main())
