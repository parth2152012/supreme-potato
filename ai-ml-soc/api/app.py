from fastapi import FastAPI, HTTPException, Depends
from aiokafka import AIOKafkaProducer
from elasticsearch import AsyncElasticsearch
import json
import os
import asyncio
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

# --- Configuration ---
KAFKA_BROKER = os.environ.get("KAFKA_BROKER", "localhost:9092")
ELASTICSEARCH_URL = os.environ.get("ELASTICSEARCH_URL", "http://localhost:9200")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
KAFKA_LOGS_TOPIC = "logs"
ES_INDEX_NAME = "processed_logs"
CONFIG_UPDATES_TOPIC = "config-updates"
INITIAL_WHITELISTED_IPS = set(os.environ.get("WHITELISTED_IPS", "192.168.1.100,10.0.0.1").split(','))

# --- Global Connection Handlers ---
kafka_producer: Optional[AIOKafkaProducer] = None
es_client: Optional[AsyncElasticsearch] = None
whitelisted_ips: set = INITIAL_WHITELISTED_IPS


async def get_kafka_producer() -> AIOKafkaProducer:
    if kafka_producer is None:
        raise HTTPException(status_code=503, detail="Kafka producer is not available.")
    return kafka_producer

async def get_es_client() -> AsyncElasticsearch:
    if es_client is None:
        raise HTTPException(status_code=503, detail="Elasticsearch client is not available.")
    return es_client


# --- FastAPI App Setup ---

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    global kafka_producer, es_client
    loop = asyncio.get_event_loop()
    print("API: Initializing connections...")
    kafka_producer = AIOKafkaProducer(
        loop=loop,
        bootstrap_servers=KAFKA_BROKER,
        value_serializer=lambda v: json.dumps(v).encode('utf-8')
    )
    es_client = AsyncElasticsearch(hosts=[ELASTICSEARCH_URL])
    
    # Start connections in parallel
    await asyncio.gather(
        kafka_producer.start(),
        es_client.ping()  # Use ping to verify ES connection
    )
    print("API: Connections established successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    print("API: Closing connections...")
    await asyncio.gather(
        kafka_producer.stop() if kafka_producer else asyncio.sleep(0),
        es_client.close() if es_client else asyncio.sleep(0)
    )
    print("API: Connections closed.")

# --- Pydantic Models ---
class Log(BaseModel):
    message: str

class Alert(BaseModel):
    id: str = Field(..., alias='_id')
    message: str
    is_anomaly: bool
    timestamp: int
    status: str

class AlertStatusUpdate(BaseModel):
    status: str

class WhitelistIP(BaseModel):
    ip: str

class WhitelistResponse(BaseModel):
    whitelisted_ips: List[str]

# --- API Endpoints ---
@app.get("/")
def read_root():
    return {"message": "SOC API is running"}

@app.post("/logs")
async def submit_log(log: Log, producer: AIOKafkaProducer = Depends(get_kafka_producer)):
    try:
        await producer.send_and_wait(KAFKA_LOGS_TOPIC, {'message': log.message})
        return {"status": "Log submitted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send log to Kafka: {e}")

@app.get("/alerts")
async def get_alerts(is_anomaly: bool = True, es: AsyncElasticsearch = Depends(get_es_client)):
    try:
        res = await es.search(
            index=ES_INDEX_NAME,
            query={"match": {"is_anomaly": is_anomaly}},
            ignore_unavailable=True
        )
        return [{"id": hit["_id"], **hit["_source"]} for hit in res["hits"]["hits"]]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query Elasticsearch: {e}")

@app.patch("/alerts/{alert_id}")
async def update_alert_status(alert_id: str, update: AlertStatusUpdate, es: AsyncElasticsearch = Depends(get_es_client)):
    try:
        await es.update(
            index=ES_INDEX_NAME,
            id=alert_id,
            doc={"status": update.status}
        )
        return {"status": "Alert status updated successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update alert status: {e}")

@app.get("/whitelist", response_model=WhitelistResponse)
async def get_whitelist():
    return {"whitelisted_ips": sorted(list(whitelisted_ips))}

@app.post("/whitelist", status_code=201)
async def add_to_whitelist(item: WhitelistIP, producer: AIOKafkaProducer = Depends(get_kafka_producer)):
    if item.ip in whitelisted_ips:
        return {"status": "IP already in whitelist"}
    
    whitelisted_ips.add(item.ip)
    try:
        await producer.send_and_wait(CONFIG_UPDATES_TOPIC, {"action": "add", "ip": item.ip})
        return {"status": "IP added to whitelist"}
    except Exception as e:
        whitelisted_ips.remove(item.ip) # Rollback change on failure
        raise HTTPException(status_code=500, detail=f"Failed to update whitelist: {e}")

@app.delete("/whitelist/{ip}", status_code=200)
async def remove_from_whitelist(ip: str, producer: AIOKafkaProducer = Depends(get_kafka_producer)):
    if ip not in whitelisted_ips:
        raise HTTPException(status_code=404, detail="IP not found in whitelist")
    
    whitelisted_ips.remove(ip)
    await producer.send_and_wait(CONFIG_UPDATES_TOPIC, {"action": "remove", "ip": ip})
    return {"status": "IP removed from whitelist"}
