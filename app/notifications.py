from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

NotificationType = Literal[
    "VALIDATION_PASSED",
    "PHOTO_REJECTED",
    "MATCHED",
    "POSTCARD_RECEIVED",
    "SEARCH_EXPIRED",
    "SYSTEM",
]


class NotificationWriter(Protocol):
    async def create(self, **values): ...


@dataclass(frozen=True, slots=True)
class NotificationTemplate:
    title: str
    message: str
    target_type: str


TEMPLATES: dict[NotificationType, NotificationTemplate] = {
    "VALIDATION_PASSED": NotificationTemplate(
        "탐색을 시작했어요", "오늘의 순간이 닮은 장면을 찾고 있어요.", "PHOTO"
    ),
    "PHOTO_REJECTED": NotificationTemplate(
        "다른 사진이 필요해요", "사진을 확인하고 새로운 순간을 등록해주세요.", "PHOTO"
    ),
    "MATCHED": NotificationTemplate(
        "닮은 순간을 발견했어요", "당신과 나란한 순간을 확인해보세요.", "MATCH"
    ),
    "POSTCARD_RECEIVED": NotificationTemplate(
        "엽서가 도착했어요", "평행한 순간으로부터 온 메시지를 확인해보세요.", "POSTCARD"
    ),
    "SEARCH_EXPIRED": NotificationTemplate(
        "탐색이 끝났어요", "7일간의 순간 탐색이 종료되었습니다.", "PHOTO"
    ),
    "SYSTEM": NotificationTemplate("DALM 안내", "새로운 운영 안내가 있습니다.", "SYSTEM"),
}


async def create_event_notification(
    writer: NotificationWriter,
    *,
    user_id: UUID,
    type: NotificationType,
    target_id: UUID | None = None,
    message: str | None = None,
):
    template = TEMPLATES[type]
    return await writer.create(
        user_id=user_id,
        type=type,
        title=template.title,
        message=message or template.message,
        target_type=template.target_type,
        target_id=target_id,
    )
