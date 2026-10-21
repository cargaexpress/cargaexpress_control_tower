"""Background worker process for consuming and normalizing RabbitMQ webhook events.

How to run:
    uv run python -m app.worker
"""

import asyncio
import logging
import signal
import sys

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.event_consumer import consume_events
from app.services.rabbitmq_service import rabbitmq_service

logger = logging.getLogger("cargaexpress.worker")


async def main() -> None:
    """Entry point for the consumer worker process."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting CargaExpress Webhook Event Consumer Worker...")
    logger.info("Connecting to RabbitMQ broker at: %s", settings.rabbitmq_url)

    stop_event = asyncio.Event()

    # Register OS signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, AttributeError):
            # Fallback for Windows environments where signal handlers are not implemented
            pass

    try:
        await consume_events(
            rabbitmq_service=rabbitmq_service,
            session_factory=AsyncSessionLocal,
            stop_event=stop_event,
        )
    except asyncio.CancelledError:
        logger.info("Worker consumer task was cancelled.")
    except Exception as exc:
        logger.exception("Worker encountered a fatal error: %s", exc)
        sys.exit(1)
    finally:
        await rabbitmq_service.close()
        logger.info("Worker consumer shutdown completed cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker terminated by user via KeyboardInterrupt.")
