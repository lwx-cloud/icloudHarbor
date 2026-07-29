from __future__ import annotations

import json
from pathlib import Path

import httpx

from icloudharbor.config.models import NotificationChannelConfig
from icloudharbor.notify.base import NotificationEvent, NotificationType, NotifierHub


def test_wecom_sends_text_message_with_enterprise_application(
    tmp_path: Path,
) -> None:
    secret_file = tmp_path / "wecom-secret"
    secret_file.write_text("test-secret\n", encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/gettoken"):
            assert request.url.params["corpid"] == "corp-id"
            assert request.url.params["corpsecret"] == "test-secret"
            return httpx.Response(200, json={"errcode": 0, "access_token": "access-token"})
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    channel = NotificationChannelConfig(
        type="wecom",
        corp_id="corp-id",
        corp_secret_file=secret_file,
        agent_id=1000002,
        to_user="@all",
        name="家庭相册",
    )
    event = NotificationEvent(
        NotificationType.SYNC_COMPLETED,
        "iCloudHarbor 同步完成",
        "新增 3 个文件",
    )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = NotifierHub._wecom(client, channel, event)

    assert response.status_code == 200
    assert len(requests) == 2
    payload = json.loads(requests[1].content)
    assert payload["touser"] == "@all"
    assert payload["agentid"] == 1000002
    assert payload["msgtype"] == "text"
    assert payload["text"]["content"] == "家庭相册\niCloudHarbor 同步完成\n\n新增 3 个文件"


def test_wecom_uses_textcard_when_source_url_is_configured(tmp_path: Path) -> None:
    secret_file = tmp_path / "wecom-secret"
    secret_file.write_text("test-secret", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/gettoken"):
            return httpx.Response(200, json={"errcode": 0, "access_token": "access-token"})
        payload = json.loads(request.content)
        assert payload["msgtype"] == "textcard"
        assert payload["textcard"]["url"] == "https://example.com/status"
        return httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})

    channel = NotificationChannelConfig(
        type="wecom",
        corp_id="corp-id",
        corp_secret_file=secret_file,
        agent_id=1000002,
        to_user="liuwx",
        content_source_url="https://example.com/status",
    )
    event = NotificationEvent(NotificationType.SYNC_FAILED, "同步失败", "需要检查日志")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        response = NotifierHub._wecom(client, channel, event)

    assert response.status_code == 200


def test_wecom_api_error_is_reported_without_secret(tmp_path: Path) -> None:
    secret_file = tmp_path / "wecom-secret"
    secret_file.write_text("private-value", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 40013, "errmsg": "invalid corpid"})

    channel = NotificationChannelConfig(
        type="wecom",
        corp_id="corp-id",
        corp_secret_file=secret_file,
        agent_id=1000002,
        to_user="@all",
    )
    event = NotificationEvent(NotificationType.SYNC_FAILED, "同步失败", "需要检查日志")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        try:
            NotifierHub._wecom(client, channel, event)
        except ValueError as exc:
            assert str(exc) == "企业微信 access token 获取失败"
            assert "private-value" not in str(exc)
        else:
            raise AssertionError("企业微信 API 错误必须引发异常")
