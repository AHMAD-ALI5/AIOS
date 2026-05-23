"""
AIOS Message Bus
Redis Pub/Sub-based async inter-agent communication.
"""

from __future__ import annotations

import asyncio
import json
from typing import Callable, Optional

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.models import BusMessage, MessageType

logger = get_logger("message_bus")

# Topic constants
TOPIC_SCHEDULER_DISPATCH = "aios.scheduler.dispatch"
TOPIC_SCHEDULER_ACK = "aios.scheduler.ack"
TOPIC_AGENT_RESEARCH = "aios.agent.research"
TOPIC_AGENT_CODE = "aios.agent.code"
TOPIC_AGENT_WRITER = "aios.agent.writer"
TOPIC_AGENT_ANALYSIS = "aios.agent.analysis"
TOPIC_AGENT_COLLECTOR = "aios.agent.collector"

AGENT_TOPIC_MAP = {
    "research": TOPIC_AGENT_RESEARCH,
    "code": TOPIC_AGENT_CODE,
    "writer": TOPIC_AGENT_WRITER,
    "analysis": TOPIC_AGENT_ANALYSIS,
    "collector": TOPIC_AGENT_COLLECTOR,
}


class MessageBus:
    """
    Redis Pub/Sub message bus.
    Provides publish/subscribe for scheduler↔agent and peer agent communication.
    """

    def __init__(self, config: Optional[AIOSConfig] = None) -> None:
        self.config = config or get_config()
        self._pub_client = None
        self._sub_client = None
        self._pubsub = None
        self._handlers: dict[str, list[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None

    async def _get_pub(self):
        if self._pub_client is None:
            import redis.asyncio as redis
            self._pub_client = await redis.from_url(
                self.config.redis.url, decode_responses=True
            )
        return self._pub_client

    async def _get_pubsub(self):
        if self._pubsub is None:
            import redis.asyncio as redis
            self._sub_client = await redis.from_url(
                self.config.redis.url, decode_responses=True
            )
            self._pubsub = self._sub_client.pubsub()
        return self._pubsub

    async def publish(self, topic: str, message: BusMessage) -> None:
        """Publish a message to a topic."""
        try:
            client = await self._get_pub()
            await client.publish(topic, message.model_dump_json())
            logger.debug(f"Published {message.message_type} to {topic}")
        except Exception as exc:
            logger.error(f"Publish failed on {topic}: {exc}")

    async def subscribe(self, topic: str, handler: Callable[[BusMessage], None]) -> None:
        """Subscribe to a topic with a message handler."""
        if topic not in self._handlers:
            self._handlers[topic] = []
            pubsub = await self._get_pubsub()
            await pubsub.subscribe(topic)
        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed to {topic}")

    async def start_listener(self) -> None:
        """Start the background listener loop."""
        self._listener_task = asyncio.create_task(self._listen())
        logger.info("Message bus listener started")

    async def stop(self) -> None:
        if self._listener_task:
            self._listener_task.cancel()
        if self._pub_client:
            await self._pub_client.aclose()
        if self._sub_client:
            await self._sub_client.aclose()

    async def _listen(self) -> None:
        pubsub = await self._get_pubsub()
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            topic = raw["channel"]
            handlers = self._handlers.get(topic, [])
            if not handlers:
                continue
            try:
                msg = BusMessage.model_validate_json(raw["data"])
                for handler in handlers:
                    try:
                        if asyncio.iscoroutinefunction(handler):
                            await handler(msg)
                        else:
                            handler(msg)
                    except Exception as exc:
                        logger.error(f"Handler error on {topic}: {exc}")
            except Exception as exc:
                logger.error(f"Message parse error on {topic}: {exc}")

    async def send_to_agent(self, agent_type: str, message: BusMessage) -> None:
        topic = AGENT_TOPIC_MAP.get(agent_type, f"aios.agent.{agent_type}")
        await self.publish(topic, message)

    async def send_to_scheduler(self, message: BusMessage) -> None:
        await self.publish(TOPIC_SCHEDULER_ACK, message)

    async def send_peer(self, task_id: str, message: BusMessage) -> None:
        await self.publish(f"aios.peer.{task_id}", message)
