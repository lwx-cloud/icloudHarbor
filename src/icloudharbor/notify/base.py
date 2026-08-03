from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from enum import StrEnum
from html import escape
from pathlib import Path
from urllib.parse import quote

import httpx
import structlog

from icloudharbor.config.models import NotificationChannelConfig, NotificationsConfig
from icloudharbor.security.secrets import read_secret

LOGGER = structlog.get_logger(__name__)


class NotificationType(StrEnum):
    APP_STARTED = "APP_STARTED"
    SYNC_STARTED = "SYNC_STARTED"
    SYNC_COMPLETED = "SYNC_COMPLETED"
    SYNC_PARTIAL = "SYNC_PARTIAL"
    SYNC_FAILED = "SYNC_FAILED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_EXPIRING = "AUTH_EXPIRING"
    AUTH_RECOVERED = "AUTH_RECOVERED"
    MOUNT_MISSING = "MOUNT_MISSING"
    STORAGE_LOW = "STORAGE_LOW"
    RATE_LIMITED = "RATE_LIMITED"
    REMOTE_SCHEMA_CHANGED = "REMOTE_SCHEMA_CHANGED"
    DELETE_GUARD_TRIGGERED = "DELETE_GUARD_TRIGGERED"


@dataclass(slots=True, frozen=True)
class NotificationEvent:
    type: NotificationType
    title: str
    message: str
    payload: dict[str, object] | None = None
    details: str | None = None

    @property
    def detailed_message(self) -> str:
        if not self.details:
            return self.message
        return f"{self.message}\n\n{self.details}"


@dataclass(slots=True, frozen=True)
class DeliveryResult:
    channel: str
    success: bool
    status_code: int | None = None
    message: str | None = None


class NotifierHub:
    def __init__(self, config: NotificationsConfig) -> None:
        self.config = config

    def send(self, event: NotificationEvent) -> list[DeliveryResult]:
        if not self._enabled_for(event):
            return []
        return [
            self._send_channel(channel, event)
            for channel in self.config.channels
            if channel.enabled
        ]

    def _enabled_for(self, event: NotificationEvent) -> bool:
        if event.type == NotificationType.APP_STARTED:
            return self.config.startup
        if event.type == NotificationType.SYNC_COMPLETED:
            return self.config.success
        if event.type in {
            NotificationType.AUTH_REQUIRED,
            NotificationType.AUTH_EXPIRING,
            NotificationType.AUTH_RECOVERED,
        }:
            return self.config.auth_required
        return self.config.failure

    def _send_channel(
        self,
        channel: NotificationChannelConfig,
        event: NotificationEvent,
    ) -> DeliveryResult:
        channel_name = {
            "bark": "Bark",
            "serverchan": "Server酱",
            "telegram": "Telegram",
            "wecom": "企业微信",
            "webhook": "Webhook",
        }[channel.type]
        LOGGER.info(f"正在发送{channel_name}通知")
        try:
            with httpx.Client(timeout=channel.timeout, follow_redirects=False) as client:
                if channel.type == "bark":
                    response = self._bark(client, channel, event, self.config.silent)
                elif channel.type == "serverchan":
                    response = self._serverchan(client, channel, event)
                elif channel.type == "telegram":
                    response = self._telegram(client, channel, event, self.config.silent)
                elif channel.type == "wecom":
                    response = self._wecom(client, channel, event)
                else:
                    response = self._webhook(client, channel, event, self.config.silent)
            if response.is_success:
                LOGGER.info(f"{channel_name}通知发送成功（HTTP {response.status_code}）")
            else:
                LOGGER.warning(f"{channel_name}通知发送失败（HTTP {response.status_code}）")
            return DeliveryResult(
                channel.type,
                response.is_success,
                response.status_code,
                None if response.is_success else "通知服务返回失败状态",
            )
        except Exception as exc:
            LOGGER.warning(f"{channel_name}通知发送失败：{type(exc).__name__}")
            return DeliveryResult(channel.type, False, message=type(exc).__name__)

    @staticmethod
    def _bark(
        client: httpx.Client,
        channel: NotificationChannelConfig,
        event: NotificationEvent,
        silent: bool = False,
    ) -> httpx.Response:
        if not channel.device_key_file:
            raise ValueError("Bark 缺少 device_key_file")
        server = str(channel.server or "https://api.day.app").rstrip("/")
        key = read_secret(channel.device_key_file)
        payload = {"body": event.detailed_message, "group": "iCloudHarbor"}
        if silent:
            payload["level"] = "passive"
        return client.post(
            f"{server}/{quote(key, safe='')}/{quote(event.title, safe='')}",
            json=payload,
        )

    @staticmethod
    def _serverchan(
        client: httpx.Client,
        channel: NotificationChannelConfig,
        event: NotificationEvent,
    ) -> httpx.Response:
        if not channel.send_key_file:
            raise ValueError("Server酱缺少 send_key_file")
        key = read_secret(channel.send_key_file)
        return client.post(
            f"https://sctapi.ftqq.com/{quote(key, safe='')}.send",
            data={"title": event.title, "desp": event.detailed_message},
        )

    @staticmethod
    def _telegram(
        client: httpx.Client,
        channel: NotificationChannelConfig,
        event: NotificationEvent,
        silent: bool = False,
    ) -> httpx.Response:
        if not channel.token_file or not channel.chat_id:
            raise ValueError("Telegram 缺少 token_file 或 chat_id")
        token = read_secret(channel.token_file)
        return client.post(
            f"https://api.telegram.org/bot{quote(token, safe='')}/sendMessage",
            json={
                "chat_id": channel.chat_id,
                "text": f"{event.title}\n\n{event.detailed_message}",
                "disable_notification": silent,
            },
        )

    @staticmethod
    def _wecom(
        client: httpx.Client,
        channel: NotificationChannelConfig,
        event: NotificationEvent,
    ) -> httpx.Response:
        if (
            not channel.corp_id
            or not channel.corp_secret_file
            or not channel.agent_id
            or not channel.to_user
        ):
            raise ValueError("企业微信缺少 corp_id、corp_secret_file、agent_id 或 to_user")

        server = str(channel.server or "https://qyapi.weixin.qq.com").rstrip("/")
        secret = read_secret(channel.corp_secret_file)
        token_response = client.get(
            f"{server}/cgi-bin/gettoken",
            params={"corpid": channel.corp_id, "corpsecret": secret},
        )
        token_response.raise_for_status()
        token_payload = token_response.json()
        access_token = token_payload.get("access_token")
        if token_payload.get("errcode", 0) != 0 or not isinstance(access_token, str):
            raise ValueError("企业微信 access token 获取失败")

        content = f"{event.title}\n\n{event.detailed_message}"
        if channel.name:
            content = f"{channel.name}\n{content}"
        message: dict[str, object] = {
            "touser": channel.to_user,
            "agentid": channel.agent_id,
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 1,
            "duplicate_check_interval": 1800,
        }
        media_id = NotifierHub._wecom_media_id(channel, event.type)
        if media_id:
            article: dict[str, object] = {
                "title": event.title,
                "thumb_media_id": media_id,
                "content": escape(content).replace("\n", "<br>"),
                "digest": event.message,
            }
            if channel.name:
                article["author"] = channel.name
            if channel.content_source_url:
                article["content_source_url"] = str(channel.content_source_url)
            message.update({"msgtype": "mpnews", "mpnews": {"articles": [article]}})
        elif channel.content_source_url:
            message.update(
                {
                    "msgtype": "textcard",
                    "textcard": {
                        "title": event.title,
                        "description": content,
                        "url": str(channel.content_source_url),
                        "btntxt": "查看详情",
                    },
                }
            )
        else:
            message.update({"msgtype": "text", "text": {"content": content}})

        response = client.post(
            f"{server}/cgi-bin/message/send",
            params={"access_token": access_token},
            json=message,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("errcode", 0) != 0:
            raise ValueError("企业微信消息发送失败")
        return response

    @staticmethod
    def _wecom_media_id(
        channel: NotificationChannelConfig,
        event_type: NotificationType,
    ) -> str | None:
        if event_type in {
            NotificationType.APP_STARTED,
            NotificationType.AUTH_RECOVERED,
        }:
            return channel.media_id_startup
        if event_type == NotificationType.SYNC_COMPLETED:
            return channel.media_id_download
        if event_type == NotificationType.AUTH_EXPIRING:
            return channel.media_id_expiration
        return channel.media_id_warning

    @staticmethod
    def _webhook(
        client: httpx.Client,
        channel: NotificationChannelConfig,
        event: NotificationEvent,
        silent: bool = False,
    ) -> httpx.Response:
        if not channel.url:
            raise ValueError("Webhook 缺少 url")
        payload = {
            "event": event.type.value,
            "title": event.title,
            "message": event.message,
            "data": event.payload or {},
            "timestamp": int(time.time()),
            "silent": silent,
        }
        if event.details:
            payload["details"] = event.details
        headers: dict[str, str] = {}
        if channel.secret_file:
            secret = read_secret(Path(channel.secret_file)).encode()
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            headers["X-iCloudHarbor-Signature"] = hmac.new(secret, body, hashlib.sha256).hexdigest()
            headers["Content-Type"] = "application/json"
            return client.post(str(channel.url), content=body, headers=headers)
        return client.post(str(channel.url), json=payload)
