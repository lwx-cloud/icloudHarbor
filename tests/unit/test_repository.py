from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest

from icloudharbor.config.models import AppConfig
from icloudharbor.database.repository import StateRepository
from icloudharbor.database.session import Database


def _repository(app_config: AppConfig) -> StateRepository:
    database = Database(app_config.runtime.database)
    database.initialize()
    repository = StateRepository(database)
    for account in app_config.accounts:
        repository.sync_account(account)
    return repository


def test_sync_request_generations_are_atomic(app_config: AppConfig) -> None:
    repository = _repository(app_config)

    with ThreadPoolExecutor(max_workers=8) as executor:
        requests = list(executor.map(repository.request_sync, ["personal"] * 20))

    assert sorted(request.generation for request in requests) == list(range(1, 21))
    assert repository.pending_sync_requests() == [
        max(requests, key=lambda request: request.generation)
    ]


def test_ack_sync_request_only_handles_the_captured_generation(
    app_config: AppConfig,
) -> None:
    repository = _repository(app_config)
    first = repository.request_sync("personal")
    second = repository.request_sync("personal")

    assert repository.ack_sync_request("personal", first.generation) is True
    assert repository.pending_sync_requests("personal") == [second]
    assert repository.ack_sync_request("personal", first.generation) is False
    assert repository.ack_sync_request("personal", second.generation + 1) is False
    assert repository.pending_sync_requests("personal") == [second]

    assert repository.ack_sync_request("personal", second.generation) is True
    assert repository.pending_sync_requests("personal") == []


def test_pending_sync_requests_are_visible_to_another_repository(
    app_config: AppConfig,
) -> None:
    producer = _repository(app_config)
    consumer = _repository(app_config)

    requested = producer.request_sync("personal")

    assert consumer.pending_sync_requests("personal") == [requested]
    assert consumer.ack_sync_request("personal", requested.generation) is True
    assert producer.pending_sync_requests("personal") == []


def test_pending_sync_requests_can_be_filtered_by_account(app_config: AppConfig) -> None:
    repository = _repository(app_config)
    other = app_config.accounts[0].model_copy(
        update={
            "id": "shared",
            "name": "共享图库",
        }
    )
    repository.sync_account(other)
    personal_request = repository.request_sync("personal")
    shared_request = repository.request_sync("shared")

    assert repository.pending_sync_requests("personal") == [personal_request]
    assert repository.pending_sync_requests("shared") == [shared_request]
    assert set(repository.pending_sync_requests()) == {
        personal_request,
        shared_request,
    }


def test_sync_request_is_immutable(app_config: AppConfig) -> None:
    request = _repository(app_config).request_sync("personal")

    with pytest.raises(FrozenInstanceError):
        request.generation = 2  # type: ignore[misc]
