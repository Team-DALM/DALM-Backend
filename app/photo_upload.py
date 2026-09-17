import hashlib
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

from app.errors import ApiError

SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
FORMAT_CONTENT_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


@dataclass(frozen=True, slots=True)
class ProcessedPhoto:
    content: bytes
    content_type: str
    checksum: str
    width: int
    height: int


def process_photo(
    content: bytes,
    content_type: str | None,
    *,
    max_bytes: int,
    min_width: int,
    min_height: int,
) -> ProcessedPhoto:
    if len(content) > max_bytes:
        raise ApiError(413, "IMAGE_TOO_LARGE", "사진 파일 크기가 허용 범위를 초과했습니다.")
    if content_type not in SUPPORTED_CONTENT_TYPES:
        raise ApiError(
            415, "UNSUPPORTED_IMAGE_FORMAT", "JPEG, PNG 또는 WEBP 사진만 등록할 수 있습니다."
        )
    try:
        with Image.open(BytesIO(content)) as source:
            detected_content_type = FORMAT_CONTENT_TYPES.get(source.format or "")
            if detected_content_type != content_type:
                raise ApiError(
                    415,
                    "IMAGE_CONTENT_TYPE_MISMATCH",
                    "파일 내용과 이미지 형식이 일치하지 않습니다.",
                )
            source.verify()
        with Image.open(BytesIO(content)) as source:
            normalized = ImageOps.exif_transpose(source)
            width, height = normalized.size
            if width < min_width or height < min_height:
                raise ApiError(
                    422,
                    "IMAGE_RESOLUTION_TOO_SMALL",
                    f"사진은 최소 {min_width}x{min_height} 픽셀이어야 합니다.",
                )
            if abs(width / height - 0.8) > 0.01:
                raise ApiError(422, "INVALID_IMAGE_RATIO", "사진 비율은 4:5여야 합니다.")
            rgb = Image.new("RGB", normalized.size, "white")
            if normalized.mode in {"RGBA", "LA"}:
                rgb.paste(
                    normalized.convert("RGBA"), mask=normalized.convert("RGBA").getchannel("A")
                )
            else:
                rgb.paste(normalized.convert("RGB"))
            output = BytesIO()
            rgb.save(output, format="WEBP", quality=90, method=6, exif=b"")
    except ApiError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ApiError(422, "INVALID_IMAGE", "올바른 이미지 파일이 아닙니다.") from exc
    sanitized = output.getvalue()
    return ProcessedPhoto(
        content=sanitized,
        content_type="image/webp",
        checksum=hashlib.sha256(sanitized).hexdigest(),
        width=width,
        height=height,
    )
