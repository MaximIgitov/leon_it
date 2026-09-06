"""Ошибки валидации запросов приходят человеческой фразой, а не только списком Pydantic."""

from __future__ import annotations

from httpx import AsyncClient

from leonit.core.errors import describe_validation_errors


def test_describe_validation_errors_translates_common_cases() -> None:
    errors = [
        {
            "type": "value_error",
            "loc": ("body", "email"),
            "msg": "value is not a valid email address: bad",
        },
        {"type": "missing", "loc": ("body", "password"), "msg": "Field required"},
        {
            "type": "string_too_short",
            "loc": ("body", "title"),
            "msg": "…",
            "ctx": {"min_length": 3},
        },
        {"type": "uuid_parsing", "loc": ("body", "vacancy_id"), "msg": "…"},
    ]
    text = describe_validation_errors(errors)
    assert text.startswith("Проверьте данные — ")
    assert "E-mail: некорректный адрес электронной почты" in text
    assert "Пароль: обязательное поле" in text
    assert "Название: не короче 3 символов" in text
    assert "Вакансия: неверный идентификатор" in text
    assert describe_validation_errors([]) == "Проверьте введённые данные"


async def test_invalid_email_returns_message_and_keeps_detail(client: AsyncClient) -> None:
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "ivan@mail,ru",
            "password": "correct-horse-battery",
            "full_name": "Иван",
            "organization_name": "ООО Ромашка",
        },
    )
    assert response.status_code == 422
    body = response.json()
    # Список остаётся для клиентов, которые смотрят на ``loc``; фраза — для формы.
    assert isinstance(body["detail"], list)
    assert ["body", "email"] in [error["loc"] for error in body["detail"]]
    assert body["message"] == "Проверьте данные — E-mail: некорректный адрес электронной почты"
