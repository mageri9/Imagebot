from unittest.mock import AsyncMock

import pytest

import src.services.image_gen as image_gen
from src.services.image_gen import (
    generate_from_text,
    NSFWContentError,
)


def _make_provider(name, generate_mock=None, supports_edits=True):
    # Mock возвращает кортеж (байты, токены) в соответствии с новой сигнатурой
    default_mock = AsyncMock(return_value=(b"image-bytes", {"prompt_tokens": 1000, "completion_tokens": 0}))
    return {
        "name": name,
        "provider": type(
            "FakeProvider", (), {"generate": generate_mock or default_mock}
        )(),
        "supports_edits": supports_edits,
    }


@pytest.fixture
def patched_deps(monkeypatch):
    """Общие моки для quota/settings/logging, не относящиеся к тестируемой логике."""
    monkeypatch.setattr(
        image_gen, "try_consume_quota", AsyncMock(return_value=(True, 1, 10))
    )
    monkeypatch.setattr(image_gen, "release_quota", AsyncMock())
    monkeypatch.setattr(image_gen, "log_generation", AsyncMock())
    monkeypatch.setattr(image_gen, "get_active_model", AsyncMock(return_value="gpt-image-2"))
    monkeypatch.setattr(
        image_gen, "get_image_params", AsyncMock(return_value={"size": "1024x1024", "quality": "low"})
    )
    # Заменяем отправку телеметрии на пустышку во избежание ошибок подключения к Redis в тестах
    monkeypatch.setattr(image_gen, "_publish_telemetry", AsyncMock())
    return monkeypatch


@pytest.mark.asyncio
async def test_success_on_first_provider(patched_deps):
    ok_provider = _make_provider(
        "providerA",
        AsyncMock(return_value=(b"image-bytes", {"prompt_tokens": 1000, "completion_tokens": 0}))
    )
    patched_deps.setattr(image_gen, "PROVIDER_POOL", [ok_provider])
    patched_deps.setattr(
        image_gen,
        "_get_next_provider",
        AsyncMock(side_effect=[ok_provider]),
    )

    result = await generate_from_text(user_id=1, prompt="a cat")
    assert result == b"image-bytes"
    ok_provider["provider"].generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_to_second_provider_on_transient_error(patched_deps):
    failing_provider = _make_provider(
        "providerA", AsyncMock(side_effect=RuntimeError("boom"))
    )
    ok_provider = _make_provider(
        "providerB",
        AsyncMock(return_value=(b"image-bytes", {"prompt_tokens": 1000, "completion_tokens": 0}))
    )
    pool = [failing_provider, ok_provider]

    patched_deps.setattr(image_gen, "PROVIDER_POOL", pool)
    patched_deps.setattr(
        image_gen,
        "_get_next_provider",
        AsyncMock(side_effect=[failing_provider, ok_provider]),
    )

    result = await generate_from_text(user_id=1, prompt="a dog")
    assert result == b"image-bytes"
    failing_provider["provider"].generate.assert_awaited_once()
    ok_provider["provider"].generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_stops_cleanly_when_no_untried_providers_left(patched_deps):
    failing_provider = _make_provider(
        "providerA", AsyncMock(side_effect=RuntimeError("boom"))
    )
    pool = [failing_provider]

    patched_deps.setattr(image_gen, "PROVIDER_POOL", pool)
    patched_deps.setattr(
        image_gen,
        "_get_next_provider",
        AsyncMock(side_effect=[failing_provider, None]),
    )

    with pytest.raises(RuntimeError, match="временно недоступны"):
        await generate_from_text(user_id=1, prompt="a fox")


@pytest.mark.asyncio
async def test_parser_error_blocks_fallback_double_charge_guard(patched_deps):
    # Возвращаем кортеж, который вызовет ValueError при распаковке
    bad_parser_provider = _make_provider(
        "providerA", AsyncMock(side_effect=ValueError("bad response shape"))
    )
    other_provider = _make_provider(
        "providerB",
        AsyncMock(return_value=(b"unused", {"prompt_tokens": 0, "completion_tokens": 0}))
    )
    pool = [bad_parser_provider, other_provider]

    patched_deps.setattr(image_gen, "PROVIDER_POOL", pool)
    patched_deps.setattr(
        image_gen,
        "_get_next_provider",
        AsyncMock(side_effect=[bad_parser_provider, other_provider]),
    )

    with pytest.raises(RuntimeError, match="внутренняя ошибка обработки ответа"):
        await generate_from_text(user_id=1, prompt="a bird")

    other_provider["provider"].generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_nsfw_error_releases_quota_and_raises_without_fallback(patched_deps):
    nsfw_provider = _make_provider(
        "providerA",
        AsyncMock(side_effect=RuntimeError("moderation_blocked: content rejected")),
    )
    other_provider = _make_provider(
        "providerB",
        AsyncMock(return_value=(b"unused", {"prompt_tokens": 0, "completion_tokens": 0}))
    )
    pool = [nsfw_provider, other_provider]

    patched_deps.setattr(image_gen, "PROVIDER_POOL", pool)
    patched_deps.setattr(
        image_gen,
        "_get_next_provider",
        AsyncMock(side_effect=[nsfw_provider, other_provider]),
    )

    with pytest.raises(NSFWContentError):
        await generate_from_text(user_id=1, prompt="something rejected")

    other_provider["provider"].generate.assert_not_awaited()
    image_gen.release_quota.assert_awaited_once_with(1)