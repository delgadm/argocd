import os
import random
import time

from fastapi import FastAPI, HTTPException
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

app = FastAPI()

resource = Resource.create({"service.name": "Order Service"})

# Configuring OTLP Exporter for tracing.
# Alloy's OTLP gRPC receiver listens on 0.0.0.0:4317 on the Mac Studio -
# override with OTEL_COLLECTOR_ENDPOINT if running this app elsewhere.
COLLECTOR_ENDPOINT = os.environ.get("OTEL_COLLECTOR_ENDPOINT", "192.168.0.75:4317")

trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)
span_exporter = OTLPSpanExporter(endpoint=COLLECTOR_ENDPOINT, insecure=True)
span_processor = BatchSpanProcessor(span_exporter)
trace.get_tracer_provider().add_span_processor(span_processor)

FastAPIInstrumentor.instrument_app(app)

# Configuring Meter Provider for metrics.
# Printed to console for now - swap ConsoleMetricExporter for an
# OTLPMetricExporter(endpoint=COLLECTOR_ENDPOINT, insecure=True) to ship
# these to Alloy too.
metric_reader = PeriodicExportingMetricReader(ConsoleMetricExporter())
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
meter = meter_provider.get_meter(__name__)
order_counter = meter.create_counter(name="otel_order", description="Count of orders")


@app.get("/")
async def read_root():
    with tracer.start_as_current_span("Connecting to DB") as span:
        try:
            # Simulate database connection
            time.sleep(random.uniform(0.01, 0.08))
            span.set_attribute("db-name", "prod-sql")
            span.set_attribute("connection-status", "success")
        except Exception as exc:
            span.set_attribute("connection-status", "failed")
            span.record_exception(exc)
            raise

    return {"message": "Order Service is running"}


@app.post("/orders")
async def create_order():
    with tracer.start_as_current_span("Connecting to DB") as span:
        span.set_attribute("db-name", "prod-sql")
        time.sleep(random.uniform(0.02, 0.15))
        if random.random() < 0.1:
            span.set_attribute("connection-status", "failed")
            raise HTTPException(status_code=500, detail="database connection failed")
        span.set_attribute("connection-status", "success")

    with tracer.start_as_current_span("Process Order") as span:
        order_id = random.randint(1000, 9999)
        span.set_attribute("order.id", order_id)
        time.sleep(random.uniform(0.01, 0.05))

    order_counter.add(1)
    return {"order_id": order_id, "status": "created"}


@app.get("/orders/{order_id}")
async def get_order(order_id: int):
    with tracer.start_as_current_span("Connecting to DB") as span:
        span.set_attribute("db-name", "prod-sql")
        span.set_attribute("order.id", order_id)
        time.sleep(random.uniform(0.01, 0.06))
        if random.random() < 0.15:
            span.set_attribute("connection-status", "failed")
            raise HTTPException(status_code=500, detail="database connection failed")
        span.set_attribute("connection-status", "success")

    return {"order_id": order_id, "status": "found"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
