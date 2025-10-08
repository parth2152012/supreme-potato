from aiokafka import AIOKafkaConsumer
from elasticsearch import AsyncElasticsearch
import json
import os
import time
import re
import asyncio

# A simple regex to find the first IP address in a string
IP_REGEX = re.compile(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b')

# --- Configuration ---
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
KAFKA_LOGS_TOPIC = "logs"
ES_INDEX_NAME = "processed_logs"

# Load configurable values from environment variables
ANOMALY_KEYWORDS = os.environ.get("ANOMALY_KEYWORDS", "error,failed,denied,exception,attack").split(',')
WHITELISTED_IPS = set(os.environ.get("WHITELISTED_IPS", "192.168.1.100,10.0.0.1").split(','))

def is_anomaly(log_message: str) -> bool:
    """Checks if a log message contains any anomaly keywords."""
    return any(keyword in log_message.lower() for keyword in ANOMALY_KEYWORDS)

def connect_with_retry(connector, service_name, max_retries=15, delay=5):
    """Tries to connect to a service with a retry mechanism."""
    for i in range(max_retries):
        try:
            print(f"Attempting to connect to {service_name}...")
            connection = connector()
            print(f"Successfully connected to {service_name}.")
            return connection
        except Exception as e:
            print(f"Failed to connect to {service_name}: {e}. Retrying in {delay}s... ({i+1}/{max_retries})")
            time.sleep(delay)
    print(f"Could not connect to {service_name} after {max_retries} retries. Exiting.")
    exit(1)

print("ML Worker starting...")

async def main():
    es = connect_with_retry(lambda: AsyncElasticsearch(hosts=[ELASTICSEARCH_URL]), "Elasticsearch")

    consumer = AIOKafkaConsumer(
        KAFKA_LOGS_TOPIC,
        bootstrap_servers=KAFKA_BROKER,
        group_id='ml-group',
        auto_offset_reset='earliest',
        value_deserializer=lambda m: json.loads(m.decode('utf-8'))
    )

    await consumer.start()
    print("ML Worker connected to Kafka. Waiting for logs...")

    try:
        async for msg in consumer:
            log_data = msg.value
            print(f"[ML WORKER] Received log: {log_data}")

            message = log_data.get("message", "")

            # --- Anomaly Detection with Whitelisting ---
            ip_match = IP_REGEX.search(message)
            ip_address = ip_match.group(0) if ip_match else None

            anomaly_status = False
            if ip_address and ip_address in WHITELISTED_IPS:
                # If IP is whitelisted, it's never an anomaly
                anomaly_status = False
                print(f"[ML WORKER] IP {ip_address} is whitelisted. Ignoring anomaly check.")
            else:
                # Otherwise, perform the standard check
                anomaly_status = is_anomaly(message)
            
            # Enrich the log data with the analysis result
            log_data['is_anomaly'] = anomaly_status
            log_data['timestamp'] = int(time.time())
            log_data['status'] = 'new' # Default status for all incoming logs

            # Index the processed log into Elasticsearch
            await es.index(index=ES_INDEX_NAME, document=log_data)
            print(f"[ML WORKER] Processed and indexed log. Anomaly: {anomaly_status}")
    finally:
        await consumer.stop()
        await es.close()

if __name__ == "__main__":
    asyncio.run(main())
