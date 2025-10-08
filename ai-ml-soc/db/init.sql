CREATE TABLE alerts (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT NOW(),
    message TEXT,
    severity VARCHAR(10),
    resolved BOOLEAN DEFAULT FALSE
);
