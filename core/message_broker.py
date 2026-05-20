import json
import logging
import aio_pika
import asyncio
from typing import Callable

logger = logging.getLogger("integrator.broker")

RABBITMQ_URL = "amqp://integrator:integrator123@localhost:5672/"

QUEUES = {
    "upload.orion": "sensor.upload.orion",
    "upload.nexus": "sensor.upload.nexus",
    "upload.atlas": "sensor.upload.atlas",
    "quality.events": "sensor.quality.events",
    "notifications": "sensor.notifications",
}


async def get_connection():
    return await aio_pika.connect_robust(RABBITMQ_URL)


async def publish(queue_name: str, message: dict):
    """Publish a message to a queue."""
    try:
        conn = await get_connection()
        async with conn:
            channel = await conn.channel()
            queue = await channel.declare_queue(queue_name, durable=True)
            await channel.default_exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=queue_name,
            )
            logger.info(f"[broker] ✅ Published to {queue_name}: {message}")
    except Exception as e:
        logger.error(f"[broker] ✗ Failed to publish to {queue_name}: {e}")
        raise


async def consume(queue_name: str, callback: Callable):
    """Consume messages from a queue."""
    try:
        conn = await get_connection()
        channel = await conn.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await channel.declare_queue(queue_name, durable=True)

        logger.info(f"[broker] 👂 Listening on {queue_name}")

        async with queue.iterator() as queue_iter:
            async for message in queue_iter:
                async with message.process():
                    try:
                        body = json.loads(message.body.decode())
                        await callback(body)
                    except Exception as e:
                        logger.error(f"[broker] ✗ Error processing message: {e}")
    except Exception as e:
        logger.error(f"[broker] ✗ Consumer error on {queue_name}: {e}")
        raise