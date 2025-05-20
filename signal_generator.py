import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, AsyncIterator

import json
import os

# External dependencies are optional and may not be installed in all environments.
try:
    import psycopg2
except ImportError:  # pragma: no cover - optional dependency
    psycopg2 = None  # type: ignore

try:
    import openai
except ImportError:  # pragma: no cover - optional dependency
    openai = None  # type: ignore

try:
    import requests
except ImportError:  # pragma: no cover - optional dependency
    requests = None  # type: ignore


@dataclass
class Config:
    """Configuration for the signal generator."""

    db_dsn: str = os.getenv("DB_DSN", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4")
    confidence_threshold: float = 0.8
    message_queue_url: str = os.getenv("MESSAGE_QUEUE_URL", "")
    batch_size: int = 100
    max_retries: int = 3
    additional_params: Dict[str, Any] = field(default_factory=dict)


class SignalGenerator:
    """Generate MEV related signals from blockchain events."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        self.db_conn = None
        self._connect_db()
        self.last_event_id = 0
        if openai:
            openai.api_key = self.config.openai_api_key

    # Database -----------------------------------------------------------------
    def _connect_db(self) -> None:
        """Connect to PostgreSQL database."""
        if not psycopg2:
            self.logger.warning("psycopg2 is not installed; database features disabled")
            return
        try:
            self.db_conn = psycopg2.connect(self.config.db_dsn)
            self.logger.info("Connected to database")
        except Exception as exc:  # pragma: no cover - connection errors
            self.logger.error("DB connection failed: %s", exc)
            self.db_conn = None

    def _fetch_events_since(self, last_id: int, limit: int) -> List[Dict[str, Any]]:
        """Query events since the given ID."""
        if not self.db_conn:
            self.logger.warning("No database connection; returning empty event list")
            return []
        try:
            with self.db_conn.cursor() as cur:
                cur.execute(
                    "SELECT id, data FROM events WHERE id > %s ORDER BY id ASC LIMIT %s",
                    (last_id, limit),
                )
                rows = cur.fetchall()
                events = [{"id": row[0], **json.loads(row[1])} for row in rows]
                self.logger.debug("Fetched %d events after id %s", len(events), last_id)
                return events
        except Exception as exc:  # pragma: no cover - query failure
            self.logger.error("Event query failed: %s", exc)
            return []

    async def fetch_event_batches(self) -> AsyncIterator[List[Dict[str, Any]]]:
        """Asynchronously yield batches of events for processing."""
        last_id = self.last_event_id
        while True:
            events = await asyncio.get_event_loop().run_in_executor(
                None, self._fetch_events_since, last_id, self.config.batch_size
            )
            if not events:
                break
            last_id = events[-1].get("id", last_id)
            self.last_event_id = last_id
            yield events

    # Analysis -----------------------------------------------------------------
    async def analyze_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use OpenAI to rank events via streaming API."""
        if not openai:
            self.logger.warning("openai package not available; analysis skipped")
            return []

        prompt = self._build_prompt(events)
        for attempt in range(self.config.max_retries):
            try:
                stream = await openai.ChatCompletion.acreate(
                    model=self.config.openai_model,
                    messages=[{"role": "system", "content": prompt}],
                    stream=True,
                    **self.config.additional_params,
                )
                content = ""
                async for chunk in stream:
                    delta = chunk["choices"][0].get("delta", {}).get("content", "")
                    content += delta
                self.logger.debug("OpenAI streamed response: %s", content)
                try:
                    ranked = json.loads(content)
                except json.JSONDecodeError:
                    self.logger.error("Failed to decode OpenAI JSON response")
                    ranked = []
                return ranked
            except Exception as exc:  # pragma: no cover - API errors
                self.logger.error("OpenAI request attempt %d failed: %s", attempt + 1, exc)
                await asyncio.sleep(2 ** attempt)
        self.logger.warning("Falling back to heuristic analysis")
        return self._heuristic_fallback(events)

    def _heuristic_fallback(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Simple heuristic ranking used when OpenAI fails."""
        signals = []
        for evt in events:
            signals.append({
                "signal": evt.get("id"),
                "confidence": 0.5,
                "heuristic": True,
            })
        return signals

    def _build_prompt(self, events: List[Dict[str, Any]]) -> str:
        """Create prompt for OpenAI with event data."""
        return (
            "Analyze the following blockchain events for liquidation and MEV "
            "sandwich opportunities. Return JSON with fields 'signal', "
            "'confidence', and any other useful information.\n" + json.dumps(events)
        )

    # Filtering ----------------------------------------------------------------
    def filter_signals(self, signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter and sort signals by confidence and reduce noise."""
        filtered = [
            s for s in signals if s.get("confidence", 0) >= self.config.confidence_threshold
        ]
        filtered.sort(key=lambda s: s.get("confidence", 0), reverse=True)
        avg_conf = (
            sum(s.get("confidence", 0) for s in filtered) / len(filtered)
            if filtered
            else 0
        )
        self.logger.info(
            "Signals after filtering: %d, average confidence %.2f",
            len(filtered),
            avg_conf,
        )
        return filtered

    # Publishing ---------------------------------------------------------------
    async def publish_signals(self, signals: List[Dict[str, Any]]) -> None:
        """Publish actionable signals to a message queue or API."""
        if not signals:
            self.logger.info("No signals to publish")
            return
        if not requests:
            self.logger.warning("requests package not available; cannot publish signals")
            return
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: requests.post(
                    self.config.message_queue_url, json=signals, timeout=10
                ),
            )
            resp.raise_for_status()
            self.logger.info("Published %d signals", len(signals))
        except Exception as exc:  # pragma: no cover - network errors
            self.logger.error("Failed to publish signals: %s", exc)

    # Orchestration ------------------------------------------------------------
    async def run(self) -> None:
        """Main execution method to fetch, analyze, filter and publish."""
        try:
            async for events in self.fetch_event_batches():
                raw_signals = await self.analyze_events(events)
                signals = self.filter_signals(raw_signals)
                await self.publish_signals(signals)
        except Exception as exc:  # pragma: no cover - unexpected errors
            self.logger.exception("Unexpected failure during run: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    config = Config()
    generator = SignalGenerator(config)
    asyncio.run(generator.run())
