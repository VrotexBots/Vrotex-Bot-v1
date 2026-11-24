
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


logger = logging.getLogger("vrotex.ai_brain")


# ============================================================
# VROTEX AI CONFIGURATION
# ============================================================

AI_API_KEY = os.getenv("VROTEX_AI_API_KEY", "").strip()

AI_BASE_URL = os.getenv(
    "VROTEX_AI_BASE_URL",
    "https://api.openai.com/v1",
).strip().rstrip("/")

AI_MODEL = os.getenv(
    "VROTEX_AI_MODEL",
    "gpt-4o-mini",
).strip()

AI_TIMEOUT = 60

MAX_MESSAGE_LENGTH = 12000
MAX_HISTORY_MESSAGES = 24


# ============================================================
# VROTEX AI IDENTITY AND INSTRUCTIONS
# ============================================================

VROTEX_SYSTEM_PROMPT = """
You are Vrotex AI, the intelligent assistant inside Vrotex Bot V1.

You are a knowledgeable assistant specializing in:

- Smart Money Concepts (SMC)
- Market structure
- Liquidity and liquidity sweeps
- BOS and CHoCH
- Order blocks and breaker blocks
- Fair Value Gaps (FVG) and IFVG
- Inducement
- Displacement
- Premium and discount
- Fibonacci equilibrium
- Multi-timeframe trading analysis
- Trading bot development and technical troubleshooting

VROTEX V1 PROJECT CONTEXT:

Active trading instruments:
- EURUSD
- GBPUSD
- BTCUSD

Approved strategy timeframes:
- H1: external market narrative
- M5: confirmation
- M1: entry

Approved strategy principles:

1. Market structure uses HH/HL and LH/LL.
2. BOS and CHoCH require a full candle-body close beyond the relevant level.
3. A wick through a level alone is a liquidity sweep or probe.
4. Look for suitable demand in discount and supply in premium.
5. Consider clean, unmitigated higher-timeframe order blocks
   and fair value gaps.
6. M5 confirmation includes liquidity sweep, external
   CHoCH, displacement and FVG.
7. M1 entry models include CHoCH and FVG, sweep and
   engulfing, breaker, MSS and displacement, and
   support/resistance flips.
8. The original A+ qualification threshold is 85%.

IMPORTANT BEHAVIOUR:

- Respect the user's approved Vrotex V1 decisions.
- Do not silently rename, upgrade or restructure Vrotex.
- Do not invent live prices, account balances, trades,
  bot status or market-analysis results.
- Do not claim to have inspected live bot data unless
  that information was actually provided to you.
- Explain technical answers clearly and practically.
- Help the user develop and improve the existing project.
- Do not change approved trading rules without permission.
- Do not treat external trading examples as replacements
  for the user's approved strategy.

You are the conversational intelligence assistant.
The trading engine remains responsible for actual
market scanning and trade execution.
"""


# ============================================================
# AI EXCEPTIONS
# ============================================================

class AIConfigurationError(Exception):
    pass


class AIProviderError(Exception):
    pass


# ============================================================
# VROTEX AI BRAIN
# ============================================================

class VrotexAIBrain:

    def __init__(self):

        self.api_key = AI_API_KEY
        self.base_url = AI_BASE_URL
        self.model = AI_MODEL

        self.db_path = Path(
            os.getenv(
                "VROTEX_AI_DB_PATH",
                str(
                    Path(__file__).resolve().parent
                    / "data"
                    / "vrotex_ai_memory.db"
                ),
            )
        )

        self.logger = logger

    # --------------------------------------------------------
    # DATABASE INITIALIZATION
    # --------------------------------------------------------

    def _connect_db(self):

        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            str(self.db_path),
            timeout=20,
        )

        connection.execute("""
            CREATE TABLE IF NOT EXISTS ai_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        connection.execute("""
            CREATE INDEX IF NOT EXISTS
            idx_ai_messages_conversation
            ON ai_messages(conversation_id, id)
        """)

        connection.commit()

        return connection

    # --------------------------------------------------------
    # CONVERSATION HISTORY
    # --------------------------------------------------------

    def _load_history(self, conversation_id):

        connection = self._connect_db()

        try:

            rows = connection.execute(
                """
                SELECT role, content
                FROM ai_messages
                WHERE conversation_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (
                    conversation_id,
                    MAX_HISTORY_MESSAGES,
                ),
            ).fetchall()

            rows.reverse()

            return [
                {
                    "role": role,
                    "content": content,
                }
                for role, content in rows
            ]

        finally:
            connection.close()

    # --------------------------------------------------------
    # SAVE CONVERSATION
    # --------------------------------------------------------

    def _save_messages(
        self,
        conversation_id,
        user_message,
        assistant_message,
    ):

        timestamp = datetime.now(
            timezone.utc
        ).isoformat()

        connection = self._connect_db()

        try:

            connection.execute(
                """
                INSERT INTO ai_messages
                (
                    conversation_id,
                    role,
                    content,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    "user",
                    user_message,
                    timestamp,
                ),
            )

            connection.execute(
                """
                INSERT INTO ai_messages
                (
                    conversation_id,
                    role,
                    content,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    conversation_id,
                    "assistant",
                    assistant_message,
                    timestamp,
                ),
            )

            connection.commit()

        finally:
            connection.close()

    # --------------------------------------------------------
    # AI PROVIDER REQUEST
    # --------------------------------------------------------

    def _request_ai(self, messages):

        if not self.api_key:

            raise AIConfigurationError(
                "VROTEX_AI_API_KEY is not configured."
            )

        if not self.model:

            raise AIConfigurationError(
                "VROTEX_AI_MODEL is not configured."
            )

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.6,
        }

        body = json.dumps(
            payload,
            ensure_ascii=False,
        ).encode("utf-8")

        request = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=body,
            headers={
                "Authorization": (
                    "Bearer " + self.api_key
                ),
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=AI_TIMEOUT,
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

        except urllib.error.HTTPError as exc:

            try:
                error_body = exc.read().decode(
                    "utf-8",
                    errors="replace",
                )

                error_data = json.loads(error_body)

                detail = (
                    error_data.get("error", {}).get(
                        "message",
                        "AI provider rejected the request.",
                    )
                )

            except Exception:
                detail = "AI provider returned an HTTP error."

            raise AIProviderError(
                f"AI provider HTTP {exc.code}: {detail}"
            ) from exc

        except urllib.error.URLError as exc:

            raise AIProviderError(
                "Unable to reach the AI provider: "
                + str(exc.reason)
            ) from exc

        except TimeoutError as exc:

            raise AIProviderError(
                "AI provider request timed out."
            ) from exc

        except Exception as exc:

            raise AIProviderError(
                f"AI request failed: {type(exc).__name__}"
            ) from exc

        try:

            answer = result["choices"][0]["message"]["content"]

            if isinstance(answer, list):

                answer = "".join(
                    part.get("text", "")
                    for part in answer
                    if isinstance(part, dict)
                )

            answer = str(answer).strip()

            if not answer:
                raise ValueError("Empty AI response.")

            return answer

        except Exception as exc:

            raise AIProviderError(
                "The AI provider returned an invalid response."
            ) from exc

    # --------------------------------------------------------
    # CHAT PROCESSING
    # --------------------------------------------------------

    def _chat_sync(
        self,
        conversation_id,
        user_message,
    ):

        history = self._load_history(
            conversation_id
        )

        messages = [
            {
                "role": "system",
                "content": VROTEX_SYSTEM_PROMPT,
            }
        ]

        messages.extend(history)

        messages.append({
            "role": "user",
            "content": user_message,
        })

        answer = self._request_ai(messages)

        self._save_messages(
            conversation_id,
            user_message,
            answer,
        )

        return {
            "success": True,
            "conversation_id": conversation_id,
            "reply": answer,
            "model": self.model,
        }

    # --------------------------------------------------------
    # PUBLIC CHAT METHOD
    # --------------------------------------------------------

    async def chat(
        self,
        message: str,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:

        message = str(message or "").strip()

        if not message:

            raise ValueError(
                "Message cannot be empty."
            )

        if len(message) > MAX_MESSAGE_LENGTH:

            raise ValueError(
                "Message exceeds the maximum length."
            )

        if not conversation_id:

            conversation_id = uuid.uuid4().hex

        conversation_id = str(
            conversation_id
        ).strip()

        if (
            not conversation_id
            or len(conversation_id) > 80
        ):

            raise ValueError(
                "Invalid conversation ID."
            )

        try:

            return await asyncio.to_thread(
                self._chat_sync,
                conversation_id,
                message,
            )

        except (
            AIConfigurationError,
            AIProviderError,
            ValueError,
        ):

            raise

        except Exception as exc:

            self.logger.exception(
                "Vrotex AI chat processing failed."
            )

            raise AIProviderError(
                "Vrotex AI could not process the message."
            ) from exc


# ============================================================
# SHARED AI BRAIN INSTANCE
# ============================================================

vrotex_ai_brain = VrotexAIBrain()
