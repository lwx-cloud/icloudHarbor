"""pyicloud compatibility boundary.

No module outside ``icloudharbor.protocol`` imports pyicloud.  The adapter is
intentionally tolerant of pyicloud field variations and emits only stable
iCloudHarbor models.
"""

from __future__ import annotations

import io
import mimetypes
import secrets
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from icloudharbor.protocol.base import ICloudProtocol
from icloudharbor.protocol.exceptions import (
    AuthenticationRequired,
    CursorInvalid,
    ErrorCode,
    ProtocolError,
)
from icloudharbor.protocol.models import (
    AssetQuery,
    AuthResult,
    AuthStatus,
    ChangeBatch,
    Credentials,
    RemoteAlbum,
    RemoteAsset,
    RemoteLibrary,
    RemoteResource,
    ResourceStream,
)


class PyicloudProtocolAdapter(ICloudProtocol):
    capability_version = "pyicloud-2.6.5/libraries-albums-cursor-reconcile"

    def __init__(
        self,
        session_directory: Path,
        account_id: str = "default",
        download_timeout: int = 300,
    ) -> None:
        self.session_directory = session_directory
        self.account_id = account_id
        self.download_timeout = download_timeout
        self.session_directory.mkdir(parents=True, exist_ok=True)
        self._api: Any | None = None
        self._challenge_id: str | None = None
        self._asset_versions: dict[tuple[str, str], Any] = {}

    def authenticate(self, credentials: Credentials) -> AuthResult:
        try:
            from pyicloud import PyiCloudService  # type: ignore[import-untyped]

            china_mainland = self._resolve_china_mainland(credentials.region)
            self._api = PyiCloudService(
                credentials.apple_id,
                credentials.password if credentials.password is not None else "",
                cookie_directory=str(self.session_directory),
                china_mainland=china_mainland,
            )
            # pyicloud has completed SRP/session bootstrap at this point. Do not
            # retain the plaintext password for the lifetime of the daemon.
            if hasattr(self._api, "_password_raw"):
                self._api._password_raw = None
            self._secure_session_files()
        except Exception as exc:
            raise self._map_exception(exc) from exc

        delivery_method = str(getattr(self._api, "two_factor_delivery_method", "unknown"))
        if delivery_method == "security_key" and not bool(
            getattr(self._api, "is_trusted_session", False)
        ):
            return AuthResult(
                AuthStatus.SECURITY_KEY_REQUIRED,
                message="账号要求使用安全密钥，当前 CLI 暂不支持",
            )
        if self._requires_two_factor(self._api, delivery_method):
            self._challenge_id = secrets.token_urlsafe(24)
            return AuthResult(
                AuthStatus.TWO_FACTOR_REQUIRED,
                self._challenge_id,
                "需要双重认证验证码",
            )
        if bool(getattr(self._api, "requires_2sa", False)):
            return AuthResult(
                AuthStatus.SECURITY_KEY_REQUIRED,
                message="账号要求旧式两步认证，当前 CLI 不支持设备选择",
            )
        return AuthResult(AuthStatus.AUTHENTICATED, message="认证成功")

    def submit_2fa(self, challenge_id: str, code: str) -> AuthResult:
        if not self._api or not self._challenge_id or challenge_id != self._challenge_id:
            raise AuthenticationRequired("认证挑战不存在或已失效")
        if len(code) != 6 or not code.isdigit():
            return AuthResult(AuthStatus.AUTH_FAILED, message="验证码必须是 6 位数字")
        try:
            if not bool(self._api.validate_2fa_code(code)):
                return AuthResult(AuthStatus.AUTH_FAILED, message="验证码无效")
            trusted = bool(getattr(self._api, "is_trusted_session", False))
            if not trusted:
                trusted = bool(self._api.trust_session())
            if not trusted or not bool(getattr(self._api, "is_trusted_session", False)):
                return AuthResult(
                    AuthStatus.AUTH_FAILED,
                    message="验证码已验证，但 Apple 未能建立受信任会话，请检查账号区域",
                )
            self._challenge_id = None
            self._secure_session_files()
            return AuthResult(AuthStatus.AUTHENTICATED, message="认证成功，会话已受信任")
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def trust_session(self) -> bool:
        if not self._api:
            raise AuthenticationRequired()
        try:
            return bool(self._api.trust_session())
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def auth_status(self) -> AuthStatus:
        if not self._api:
            return AuthStatus.AUTH_REQUIRED
        delivery_method = str(getattr(self._api, "two_factor_delivery_method", "unknown"))
        if self._requires_two_factor(self._api, delivery_method):
            return AuthStatus.TWO_FACTOR_REQUIRED
        if delivery_method == "security_key" and not bool(
            getattr(self._api, "is_trusted_session", False)
        ):
            return AuthStatus.SECURITY_KEY_REQUIRED
        if bool(getattr(self._api, "requires_2sa", False)):
            return AuthStatus.SECURITY_KEY_REQUIRED
        return AuthStatus.AUTHENTICATED

    def session_expires_at(self) -> datetime | None:
        if not self._api:
            return None
        session = getattr(self._api, "session", None)
        cookies = list(getattr(session, "cookies", []))
        for name in (
            "X-APPLE-WEBAUTH-USER",
            "X-APPLE-WEBAUTH-HSA-TRUST",
            "X-APPLE-WEBAUTH-TOKEN",
        ):
            expirations = [
                datetime.fromtimestamp(cookie.expires, UTC)
                for cookie in cookies
                if getattr(cookie, "name", None) == name
                and isinstance(getattr(cookie, "expires", None), int | float)
            ]
            if expirations:
                return min(expirations)
        return None

    def list_libraries(self) -> list[RemoteLibrary]:
        api = self._require_api()
        try:
            libraries = api.photos.libraries
            result: list[RemoteLibrary] = []
            for library_id in libraries:
                if library_id == "root":
                    name, library_type = "个人图库", "personal"
                elif library_id == "shared":
                    name, library_type = "共享相册", "shared-albums"
                else:
                    name, library_type = str(library_id), "shared-library"
                result.append(RemoteLibrary(str(library_id), name, library_type))
            return result
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def list_albums(self, library_id: str) -> list[RemoteAlbum]:
        api = self._require_api()
        try:
            library = api.photos.libraries.get(library_id)
            if library is None:
                return []
            container = getattr(library, "albums", None)
            if container is None and library_id == "root":
                container = api.photos.albums
            if container is None:
                return []
            result: list[RemoteAlbum] = []
            if hasattr(container, "items"):
                entries = container.items()
            else:
                entries = ((None, item) for item in container)
            for key, album in entries:
                album_id = str(
                    getattr(album, "id", None)
                    or getattr(album, "guid", None)
                    or getattr(album, "name", None)
                    or getattr(album, "fullname", None)
                    or key
                )
                name = str(
                    getattr(album, "fullname", None)
                    or getattr(album, "name", None)
                    or key
                    or album_id
                )
                result.append(
                    RemoteAlbum(
                        album_id,
                        library_id,
                        name,
                        str(getattr(album, "type", None) or "album"),
                    )
                )
            return result
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def list_assets(self, query: AssetQuery) -> list[RemoteAsset]:
        api = self._require_api()
        try:
            library = api.photos.libraries.get(query.library_id)
            if library is None:
                return []
            if query.album_id:
                albums = getattr(library, "albums", None)
                if albums is None and query.library_id == "root":
                    albums = api.photos.albums
                if albums is None:
                    raise ProtocolError(
                        f"图库不提供相册访问：{query.library_id}",
                        ErrorCode.REMOTE_NOT_FOUND,
                    )
                album = albums.get(query.album_id)
                if album is None and hasattr(albums, "find"):
                    album = albums.find(query.album_id)
                if album is None:
                    raise ProtocolError(
                        f"相册不存在：{query.album_id}",
                        ErrorCode.REMOTE_NOT_FOUND,
                    )
                sources = (album,)
            elif query.library_id == "root" and hasattr(api.photos, "all"):
                sources = (api.photos.all,)
            elif hasattr(library, "all"):
                sources = (library.all,)
            else:
                sources = tuple(library.albums)

            result: list[RemoteAsset] = []
            seen: set[str] = set()
            for source in sources:
                for asset in source:
                    normalized = self._normalize_asset(query, asset)
                    if normalized.asset_id in seen:
                        continue
                    seen.add(normalized.asset_id)
                    result.append(normalized)
                    if query.limit is not None and len(result) >= query.limit:
                        return result
            return result
        except ProtocolError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def list_recently_deleted(self, library_id: str) -> list[RemoteAsset]:
        """Return deleted assets without exposing pyicloud smart-album objects."""

        api = self._require_api()
        if library_id != "root":
            raise ProtocolError(
                f"图库不支持最近删除扫描：{library_id}",
                ErrorCode.REMOTE_NOT_FOUND,
            )
        try:
            library = api.photos.libraries.get(library_id)
            if library is None:
                raise ProtocolError("个人图库不可访问", ErrorCode.REMOTE_NOT_FOUND)
            albums = getattr(library, "albums", None)
            if albums is None:
                albums = getattr(api.photos, "albums", None)
            if albums is None:
                raise ProtocolError("个人图库不提供最近删除相册", ErrorCode.REMOTE_NOT_FOUND)
            album = albums.get("Recently Deleted")
            if album is None and hasattr(albums, "find"):
                album = albums.find("Recently Deleted")
            if album is None:
                raise ProtocolError("最近删除相册不可访问", ErrorCode.REMOTE_NOT_FOUND)

            result: list[RemoteAsset] = []
            seen: set[str] = set()
            query = AssetQuery(self.account_id, library_id, album_id="Recently Deleted")
            for raw_asset in album:
                asset = self._normalize_asset(query, raw_asset)
                if asset.asset_id in seen:
                    continue
                seen.add(asset.asset_id)
                metadata = dict(asset.metadata)
                deleted_at = self._deleted_at(raw_asset)
                if deleted_at is not None:
                    metadata["deleted_at"] = deleted_at.isoformat()
                result.append(replace(asset, deleted=True, metadata=metadata))
            return result
        except ProtocolError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def get_sync_cursor(self, library_id: str) -> str | None:
        api = self._require_api()
        try:
            library = api.photos.libraries.get(library_id)
            if library is None or not hasattr(library, "sync_cursor"):
                return None
            return str(library.sync_cursor())
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def iter_changes(self, library_id: str, cursor: str) -> ChangeBatch:
        api = self._require_api()
        try:
            library = api.photos.libraries.get(library_id)
            if library is None or not hasattr(library, "iter_changes"):
                raise CursorInvalid()
            changes = list(library.iter_changes(since=cursor))
            next_cursor = str(library.sync_cursor())
            if not changes:
                return ChangeBatch((), next_cursor)
            # pyicloud change events identify CloudKit records rather than
            # complete logical assets. A changed cursor therefore triggers a
            # safe metadata reconciliation; iCloudHarbor's own idempotency store
            # keeps this from re-downloading unchanged resources.
            assets = self.list_assets(AssetQuery(self.account_id, library_id))
            return ChangeBatch(tuple(assets), next_cursor)
        except CursorInvalid:
            raise
        except Exception as exc:
            message = str(exc).lower()
            if "sync token" in message or "cursor" in message:
                raise CursorInvalid() from exc
            raise self._map_exception(exc) from exc

    def open_resource(self, resource: RemoteResource, offset: int = 0) -> ResourceStream:
        api = self._require_api()
        try:
            if resource.download_url:
                try:
                    response = self._request_download_url(
                        api,
                        resource.download_url,
                        offset,
                    )
                except Exception as exc:
                    if self._response_status(exc) not in {401, 403}:
                        raise
                    response = self._refresh_resource(api, resource, offset)
                if getattr(response, "status_code", None) in {401, 403}:
                    close = getattr(response, "close", None)
                    if callable(close):
                        close()
                    response = self._refresh_resource(api, resource, offset)
            else:
                asset = self._asset_versions[(resource.asset_id, resource.version)]
                response = asset.download(resource.version)
            if isinstance(response, bytes):
                return ResourceStream(
                    io.BytesIO(response),
                    total_size=len(response),
                    supports_range=False,
                )
            if response is None:
                raise ProtocolError("远端资源不存在", ErrorCode.REMOTE_NOT_FOUND)
            if getattr(response, "status_code", None) in {401, 403}:
                raise ProtocolError(
                    "资源下载地址已失效，需要重新扫描",
                    ErrorCode.DOWNLOAD_URL_EXPIRED,
                )
            response.raise_for_status()
            total = response.headers.get("Content-Length")
            return ResourceStream(
                response.iter_content(chunk_size=1024 * 1024),
                status_code=response.status_code,
                total_size=int(total) if total and total.isdigit() else None,
                supports_range=response.status_code == 206
                or "bytes" in response.headers.get("Accept-Ranges", "").lower(),
                close_callback=response.close,
            )
        except ProtocolError:
            raise
        except KeyError as exc:
            raise ProtocolError(
                "资源下载地址已失效，需要重新扫描",
                ErrorCode.DOWNLOAD_URL_EXPIRED,
            ) from exc
        except Exception as exc:
            raise self._map_exception(exc) from exc

    def _request_download_url(self, api: Any, url: str, offset: int) -> Any:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        return api.session.get(
            url,
            stream=True,
            headers=headers,
            timeout=self.download_timeout,
        )

    def _refresh_resource(
        self,
        api: Any,
        resource: RemoteResource,
        offset: int,
    ) -> Any:
        asset = self._find_asset(api, resource.asset_id)
        if asset is None:
            raise ProtocolError("远端资源不存在", ErrorCode.REMOTE_NOT_FOUND)

        self._asset_versions[(resource.asset_id, resource.version)] = asset
        versions = getattr(asset, "versions", {}) or {}
        raw = versions.get(resource.version, {})
        refreshed_url = raw.get("url") if isinstance(raw, dict) else None
        if refreshed_url:
            try:
                response = self._request_download_url(api, str(refreshed_url), offset)
            except Exception as exc:
                if self._response_status(exc) in {401, 403}:
                    raise ProtocolError(
                        "资源下载地址已失效，需要重新扫描",
                        ErrorCode.DOWNLOAD_URL_EXPIRED,
                    ) from exc
                raise
            if getattr(response, "status_code", None) in {401, 403}:
                raise ProtocolError(
                    "资源下载地址已失效，需要重新扫描",
                    ErrorCode.DOWNLOAD_URL_EXPIRED,
                )
            return response
        return asset.download(resource.version)

    @staticmethod
    def _find_asset(api: Any, asset_id: str) -> Any | None:
        for library_id, library in api.photos.libraries.items():
            if library_id == "root" and hasattr(api.photos, "all"):
                sources = (api.photos.all,)
            elif hasattr(library, "all"):
                sources = (library.all,)
            else:
                sources = tuple(library.albums)
            for source in sources:
                getter = getattr(source, "get", None)
                asset = getter(asset_id) if callable(getter) else None
                if asset is not None:
                    return asset
                for candidate in source:
                    candidate_id = str(
                        getattr(candidate, "id", None)
                        or getattr(candidate, "guid", None)
                        or getattr(candidate, "record_name", None)
                    )
                    if candidate_id == asset_id:
                        return candidate
        return None

    def logout(self) -> None:
        self._api = None
        self._challenge_id = None
        self._asset_versions.clear()
        for path in self.session_directory.iterdir():
            if path.is_file():
                path.unlink()

    def _normalize_asset(self, query: AssetQuery, asset: Any) -> RemoteAsset:
        asset_id = str(
            getattr(asset, "id", None)
            or getattr(asset, "guid", None)
            or getattr(asset, "record_name", None)
        )
        if not asset_id or asset_id == "None":
            raise ProtocolError("照片响应缺少稳定 Asset ID", ErrorCode.UNKNOWN_PROTOCOL_ERROR)
        filename = str(getattr(asset, "filename", None) or f"{asset_id}.bin")
        created = self._to_datetime(
            getattr(asset, "asset_date", None)
            or getattr(asset, "created", None)
            or getattr(asset, "added_date", None)
        )
        added = self._to_datetime(getattr(asset, "added_date", None), fallback=None)
        versions = getattr(asset, "versions", {}) or {}
        is_live_photo = bool(getattr(asset, "is_live_photo", False))
        resources: list[RemoteResource] = []
        for version_name, raw in versions.items():
            if not isinstance(raw, dict):
                raw = {}
            resource_filename = str(raw.get("filename") or filename)
            size = self._optional_int(raw.get("size"))
            mime_type = raw.get("type") or mimetypes.guess_type(resource_filename)[0]
            resource_type = self._resource_type(
                str(version_name),
                resource_filename,
                is_live_photo=is_live_photo,
            )
            resource_id = str(
                raw.get("id")
                or raw.get("recordName")
                or raw.get("asset_record", {}).get("recordName", "")
                or f"{asset_id}:{version_name}"
            )
            resource = RemoteResource(
                resource_id=resource_id,
                asset_id=asset_id,
                resource_type=resource_type,
                version=str(version_name),
                filename=resource_filename,
                size=size,
                mime_type=str(mime_type) if mime_type else None,
                checksum=str(raw.get("checksum")) if raw.get("checksum") else None,
                download_url=str(raw.get("url")) if raw.get("url") else None,
            )
            resources.append(resource)
            self._asset_versions[(asset_id, str(version_name))] = asset
        if not resources:
            resources.append(
                RemoteResource(
                    resource_id=f"{asset_id}:original",
                    asset_id=asset_id,
                    resource_type=self._resource_type(
                        "original",
                        filename,
                        is_live_photo=is_live_photo,
                    ),
                    version="original",
                    filename=filename,
                    mime_type=mimetypes.guess_type(filename)[0],
                )
            )
            self._asset_versions[(asset_id, "original")] = asset
        item_type = str(getattr(asset, "item_type", "")).lower()
        media_type = (
            "video" if item_type in {"movie", "video"} or self._is_video(filename) else "photo"
        )
        return RemoteAsset(
            account_id=query.account_id,
            library_id=query.library_id,
            asset_id=asset_id,
            filename=filename,
            media_type=media_type,
            created_at=created,
            added_at=added,
            modified_at=self._to_datetime(getattr(asset, "modified", None), fallback=None),
            width=self._optional_int(getattr(asset, "width", None)),
            height=self._optional_int(getattr(asset, "height", None)),
            duration=self._optional_float(getattr(asset, "duration", None)),
            favorite=bool(getattr(asset, "is_favorite", False)),
            hidden=bool(getattr(asset, "is_hidden", False)),
            resources=tuple(resources),
            metadata={"is_live_photo": is_live_photo},
        )

    def _require_authenticated(self) -> None:
        if self.auth_status() != AuthStatus.AUTHENTICATED:
            raise AuthenticationRequired()

    def _require_api(self) -> Any:
        self._require_authenticated()
        if self._api is None:
            raise AuthenticationRequired()
        return self._api

    def _secure_session_files(self) -> None:
        try:
            self.session_directory.chmod(0o700)
            for path in self.session_directory.iterdir():
                if path.is_file():
                    path.chmod(0o600)
        except OSError:
            # Windows ACLs do not implement POSIX chmod semantics.
            pass

    def _resolve_china_mainland(self, region: str) -> bool:
        if region == "global":
            return False
        if region == "china":
            return True
        raise ValueError("iCloud 区域必须显式设置为 global 或 china")

    @staticmethod
    def _requires_two_factor(api: Any, delivery_method: str | None = None) -> bool:
        """Recognize pyicloud challenges even when its legacy flag is stale.

        pyicloud starts MFA challenges before every Apple response contains
        the fields used by ``requires_2fa``.  Its internal MFA flag and active
        delivery state remain authoritative while that challenge is active.
        """

        method = delivery_method or str(getattr(api, "two_factor_delivery_method", "unknown"))
        trusted = bool(getattr(api, "is_trusted_session", False))
        return (
            bool(getattr(api, "requires_2fa", False))
            or (bool(getattr(api, "_requires_mfa", False)) and not trusted)
            or (method in {"trusted_device", "sms"} and not trusted)
        )

    @staticmethod
    def _resource_type(
        version: str,
        filename: str,
        *,
        is_live_photo: bool = False,
    ) -> str:
        key = version.lower()
        lower = filename.lower()
        is_video = PyicloudProtocolAdapter._is_video(filename)
        if is_live_photo and (is_video or key.endswith("_video")):
            return "live_photo_video"
        if is_live_photo and key == "original":
            return "live_photo_image"
        if key in {"alternative", "jpeg_alternative"}:
            return "jpeg_alternative"
        if key in {"sidecar", "xmp_sidecar"}:
            return "xmp_sidecar"
        if "raw" in key or lower.endswith((".dng", ".cr2", ".nef", ".arw")):
            return "raw_original"
        if "adjust" in key:
            return "video_adjusted" if is_video else "photo_adjusted"
        if key in {"medium", "medium_size"}:
            return "video_medium" if is_video else "photo_medium"
        if key in {"thumb", "thumbnail"}:
            return "video_thumbnail" if is_video else "photo_thumbnail"
        return "video_original" if is_video else "photo_original"

    @staticmethod
    def _is_video(filename: str) -> bool:
        return filename.lower().endswith((".mov", ".mp4", ".m4v", ".avi"))

    @staticmethod
    def _to_datetime(value: Any, fallback: datetime | None = None) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if isinstance(value, int | float):
            timestamp = value / 1000 if value > 10_000_000_000 else value
            return datetime.fromtimestamp(timestamp, tz=UTC)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return fallback or datetime.now(UTC)

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @classmethod
    def _deleted_at(cls, asset: Any) -> datetime | None:
        record = getattr(asset, "_asset_record", None)
        value: Any = None
        if isinstance(record, dict):
            field = record.get("fields", {}).get("dateExpunged")
            value = field.get("value") if isinstance(field, dict) else field
        else:
            fields = getattr(record, "fields", None)
            get_value = getattr(fields, "get_value", None)
            if callable(get_value):
                value = get_value("dateExpunged")
        if value is None:
            return None
        return cls._to_datetime(value)

    @staticmethod
    def _response_status(exc: Exception) -> int | None:
        value = getattr(getattr(exc, "response", None), "status_code", None)
        if isinstance(value, int):
            return value
        # pyicloud's _raise_request_exception stores the HTTP status in
        # exc.code but omits exc.response; use that as a fallback.
        code = getattr(exc, "code", None)
        if isinstance(code, int):
            return code
        return None

    @staticmethod
    def _map_exception(exc: Exception) -> ProtocolError:
        name = type(exc).__name__.lower()
        message = str(exc)
        lower = message.lower()
        if "term" in lower:
            return ProtocolError("需要先接受 Apple 服务条款", ErrorCode.TERMS_REQUIRED)
        if "web access" in lower or "web_access" in lower:
            return ProtocolError("账号未允许通过 Web 访问 iCloud", ErrorCode.WEB_ACCESS_DISABLED)
        if "advanced data" in lower or "approval" in lower:
            return ProtocolError("高级数据保护账号需要临时批准", ErrorCode.ADP_APPROVAL_REQUIRED)
        if "login" in name or "authentication" in lower or "password" in lower:
            return ProtocolError("Apple Account 认证失败", ErrorCode.AUTH_ERROR)
        if "timeout" in name or "timed out" in lower:
            return ProtocolError("Apple 服务请求超时", ErrorCode.NETWORK_TIMEOUT)
        status = PyicloudProtocolAdapter._response_status(exc)
        if status == 401:
            return ProtocolError("Apple Account 会话已失效", ErrorCode.AUTH_ERROR)
        if status == 403:
            return ProtocolError("Apple 服务拒绝访问", ErrorCode.ACCESS_DENIED)
        if status == 429:
            return ProtocolError("Apple 服务正在限流", ErrorCode.RATE_LIMITED)
        if status in {500, 502, 503, 504}:
            return ProtocolError("Apple 服务暂时不可用", ErrorCode.SERVICE_UNAVAILABLE)
        if status == 404:
            return ProtocolError("远端资源不存在", ErrorCode.REMOTE_NOT_FOUND)
        return ProtocolError(
            f"Apple 协议调用失败：{type(exc).__name__}；详情：{exc}",
            ErrorCode.UNKNOWN_PROTOCOL_ERROR,
        )
