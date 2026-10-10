"""Pluggable SMS provider abstraction.

Business logic depends only on SMSProvider. Swapping Twilio for Vonage or a local
gateway is a one-line change in `build_sms_provider`. API keys come from settings
(env), never hardcoded. If SMS is disabled or misconfigured, NullSMSProvider is
used and the bot keeps working via Telegram.
"""
from __future__ import annotations

import abc

import structlog

from app.config import settings

log = structlog.get_logger(__name__)


class SMSProvider(abc.ABC):
    @abc.abstractmethod
    async def send(self, to: str, text: str) -> bool:
        """Send an SMS. Returns True on success, never raises to the caller."""
        raise NotImplementedError


class NullSMSProvider(SMSProvider):
    """Fallback: logs instead of sending. Used when SMS is off or unconfigured."""

    async def send(self, to: str, text: str) -> bool:
        log.info("sms.null.send", to=to, text=text)
        return True


class TwilioSMSProvider(SMSProvider):
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        from twilio.rest import Client  # imported lazily

        self._client = Client(account_sid, auth_token)
        self._from = from_number

    async def send(self, to: str, text: str) -> bool:
        import asyncio

        def _send() -> bool:
            try:
                self._client.messages.create(body=text, from_=self._from, to=to)
                return True
            except Exception as exc:  # pragma: no cover - network
                log.error("sms.twilio.error", error=str(exc), to=to)
                return False

        return await asyncio.to_thread(_send)


def build_sms_provider() -> SMSProvider:
    if not settings.sms_enabled:
        return NullSMSProvider()
    if not (
        settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_from_number
    ):
        log.warning("sms.twilio.misconfigured", detail="missing credentials, using Null")
        return NullSMSProvider()
    return TwilioSMSProvider(
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_from_number,
    )
