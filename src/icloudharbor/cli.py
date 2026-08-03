"""Command-line product surface for Docker and NAS operations."""

from __future__ import annotations

import os
import signal
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import structlog
import typer
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from icloudharbor import __version__
from icloudharbor.application import HarborApplication
from icloudharbor.config.loader import (
    bootstrap_config,
    config_path_from_env,
    config_snapshot,
    load_config,
)
from icloudharbor.config.models import AccountConfig
from icloudharbor.notify import NotificationEvent
from icloudharbor.notify.base import NotificationType
from icloudharbor.observability.logging import configure_logging
from icloudharbor.observability.startup import log_startup_summary, startup_summary
from icloudharbor.photos.engine import SyncExecution
from icloudharbor.protocol.exceptions import ErrorCode, HarborError
from icloudharbor.protocol.models import AssetQuery, AuthResult, AuthStatus
from icloudharbor.scheduler.service import SchedulerService
from icloudharbor.security.prompt import masked_password_prompt
from icloudharbor.security.redaction import redact

LOGGER = structlog.get_logger(__name__)
AUTH_REQUIRED_ERROR_CODES = {
    "AUTH_REQUIRED",
    "TERMS_REQUIRED",
    "WEB_ACCESS_DISABLED",
    "ADP_APPROVAL_REQUIRED",
}
SYNC_REQUEST_POLL_SECONDS = 1.0
AUTH_ACTION_STATUSES = {
    AuthStatus.AUTH_REQUIRED,
    AuthStatus.TWO_FACTOR_REQUIRED,
    AuthStatus.SECURITY_KEY_REQUIRED,
    AuthStatus.TERMS_REQUIRED,
    AuthStatus.WEB_ACCESS_DISABLED,
    AuthStatus.ADP_APPROVAL_REQUIRED,
    AuthStatus.AUTH_FAILED,
    AuthStatus.REAUTHENTICATION_REQUIRED,
}

app = typer.Typer(
    name="icloudharbor",
    help="可靠地将 iCloud Photos 备份到本地磁盘或 NAS。",
    no_args_is_help=True,
)
config_app = typer.Typer(help="配置校验和查看。")
accounts_app = typer.Typer(help="查看已配置账号。")
session_app = typer.Typer(help="Apple 会话创建、续期和清理。")
credentials_app = typer.Typer(help="本地保存凭据的状态和清理。")
libraries_app = typer.Typer(help="查看远端图库。")
albums_app = typer.Typer(help="查看远端相册。")
sync_app = typer.Typer(help="生成计划或执行同步。")
database_app = typer.Typer(help="SQLite 状态库维护。")

app.add_typer(config_app, name="config")
app.add_typer(accounts_app, name="accounts")
app.add_typer(session_app, name="session")
app.add_typer(credentials_app, name="credentials")
app.add_typer(libraries_app, name="libraries")
app.add_typer(albums_app, name="albums")
app.add_typer(sync_app, name="sync")
app.add_typer(database_app, name="database")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"iCloudHarbor {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config_file: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="配置文件路径。"),
    ] = None,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version, is_eager=True, help="显示版本。"),
    ] = False,
) -> None:
    del version
    ctx.obj = config_path_from_env(config_file)


def _load_application(ctx: typer.Context) -> HarborApplication:
    try:
        instance = HarborApplication.from_path(ctx.obj)
        configure_logging(instance.config.runtime)
        return instance
    except (FileNotFoundError, ValueError, ValidationError, OSError) as exc:
        typer.echo(f"配置或初始化失败：{exc}", err=True)
        raise typer.Exit(2) from exc


def _account(instance: HarborApplication, account_id: str | None) -> AccountConfig:
    try:
        return instance.config.account(account_id)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc


def _display_apple_id(instance: HarborApplication, account: AccountConfig) -> str:
    if instance.config.security.redact_apple_id:
        return redact(account.apple_id)
    return account.apple_id


def _container_name() -> str:
    return os.environ.get("IH_CONTAINER_NAME", "").strip() or "icloudharbor"


def _auth_command(instance: HarborApplication, account: AccountConfig) -> str:
    action = "session renew" if instance.credential_store(account).exists() else "setup"
    return f"docker exec -it {_container_name()} icloudharbor {action}"


def _log_auth_guidance(
    instance: HarborApplication,
    account: AccountConfig,
    *,
    force: bool = False,
) -> None:
    status = instance.repository.get_auth_status(account.id)
    if status == AuthStatus.AUTHENTICATED and not force:
        if not instance.credential_store(account).exists():
            LOGGER.warning(
                "本地续期凭据未保存；当前 Session 过期后请运行："
                f"docker exec -it {_container_name()} icloudharbor setup"
            )
        return
    LOGGER.warning(f"Apple 认证尚未完成，请运行：{_auth_command(instance, account)}")
    LOGGER.warning("输入密码和验证码的命令退出后，后台会自动开始同步；请继续查看本容器日志")


@config_app.command("validate")
def config_validate(ctx: typer.Context) -> None:
    try:
        config = load_config(ctx.obj)
    except Exception as exc:
        typer.echo(f"配置无效：{exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(f"配置有效：version={config.version}，账号数={len(config.accounts)}")


@config_app.command("bootstrap")
def config_bootstrap(ctx: typer.Context) -> None:
    """Generate the initial YAML from Docker environment parameters."""

    try:
        config, created = bootstrap_config(ctx.obj)
    except Exception as exc:
        typer.echo(f"无法自动生成配置：{exc}", err=True)
        raise typer.Exit(2) from exc
    if created:
        typer.echo(f"已自动生成配置：{ctx.obj}（账号数={len(config.accounts)}）")
    else:
        typer.echo(f"现有配置有效：{ctx.obj}（未覆盖）")


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    try:
        typer.echo(config_snapshot(load_config(ctx.obj)))
    except Exception as exc:
        typer.echo(f"无法读取配置：{exc}", err=True)
        raise typer.Exit(2) from exc


@accounts_app.command("list")
def accounts_list(ctx: typer.Context) -> None:
    instance = _load_application(ctx)
    for account in instance.config.accounts:
        status = instance.repository.get_auth_status(account.id).value
        enabled = "启用" if account.enabled else "禁用"
        typer.echo(
            f"{account.id}\t{enabled}\t{_display_apple_id(instance, account)}\t认证={status}\t"
            f"目标={account.destination.path}"
        )


def _authenticate_account(
    instance: HarborApplication,
    account: AccountConfig,
    password: str,
) -> AuthResult:
    try:
        manager = instance.auth_manager(account)
        typer.echo("正在验证 Apple Account 凭据……")
        result = manager.login(password)
        if result.status == AuthStatus.TWO_FACTOR_REQUIRED:
            typer.echo("Apple 要求双重认证，请在受信任设备上查看 6 位验证码。")
            code = typer.prompt("Apple 双重认证验证码", hide_input=False)
            result = manager.verify(result.challenge_id or "", code)
            code = ""
        if result.status != AuthStatus.AUTHENTICATED:
            typer.echo(f"认证未完成：{result.message or result.status.value}", err=True)
            raise typer.Exit(1)
        typer.echo("认证成功：Apple 会话已建立并受信任。")
        return result
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"认证失败：{exc}", err=True)
        raise typer.Exit(1) from exc


def _password(account: AccountConfig) -> str:
    try:
        password = masked_password_prompt(f"{account.apple_id} 的 Apple Account 密码: ")
    except (EOFError, KeyboardInterrupt) as exc:
        typer.echo("已取消密码输入。", err=True)
        raise typer.Exit(130) from exc
    if not password:
        typer.echo("密码不能为空。", err=True)
        raise typer.Exit(2)
    return password


@app.command("setup")
def setup(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    """Authenticate, persist credentials, and request the first background sync."""

    instance = _load_application(ctx)
    account = _account(instance, account_id)
    typer.echo("***** iCloudHarbor 初始化 *****")
    for line in startup_summary(instance.config, account, ctx.obj):
        typer.echo(f"  {line}")

    health = instance.health.readiness()
    typer.echo("1/5 配置、数据库和下载目录检查")
    for name, result in health.checks.items():
        typer.echo(f"  {name}: {result}")
    if not health.ok:
        typer.echo("设置停止：请先修复以上本地检查。", err=True)
        raise typer.Exit(2)

    try:
        with instance.account_operation(account):
            typer.echo("2/5 Apple Account 密码与双重认证")
            password = _password(account)
            instance.auth_manager(account).logout()
            _authenticate_account(instance, account, password)

            typer.echo("3/5 保存本地续期凭据")
            try:
                instance.credential_store(account).write(password)
            except (OSError, ValueError) as exc:
                typer.echo(f"无法保存本地凭据：{exc}", err=True)
                raise typer.Exit(1) from exc
            finally:
                password = ""
            typer.echo("  凭据: AES-256-GCM / 文件权限 0600")

            typer.echo("4/5 iCloud Photos 访问检查")
            try:
                protocol = instance.protocol(account)
                libraries = protocol.list_libraries()
                by_selector = {
                    selector: library
                    for library in libraries
                    for selector in (library.library_id, library.name)
                }
                missing = [
                    selector for selector in account.libraries if selector not in by_selector
                ]
                if missing:
                    typer.echo(f"图库不可访问：{', '.join(missing)}", err=True)
                    raise typer.Exit(1)
                for selector in account.libraries:
                    library = by_selector[selector]
                    album_id = None
                    configured_albums = [
                        *account.filters.albums,
                        *account.filters.exclude_albums,
                    ]
                    if configured_albums:
                        albums = protocol.list_albums(library.library_id)
                        by_album = {
                            key: album for album in albums for key in (album.album_id, album.name)
                        }
                        missing_albums = [
                            name for name in configured_albums if name not in by_album
                        ]
                        if missing_albums:
                            typer.echo(
                                f"图库 {library.name} 中相册不可访问：{', '.join(missing_albums)}",
                                err=True,
                            )
                            raise typer.Exit(1)
                        if account.filters.albums:
                            album_id = by_album[account.filters.albums[0]].album_id
                    protocol.list_assets(
                        AssetQuery(
                            account.id,
                            library.library_id,
                            album_id=album_id,
                            limit=1,
                        )
                    )
                    typer.echo(f"  {library.name}: ok")
            except typer.Exit:
                raise
            except Exception as exc:
                typer.echo(f"iCloud Photos 检查失败：{exc}", err=True)
                raise typer.Exit(1) from exc

            try:
                instance.repository.request_sync(account.id)
            except Exception as exc:
                typer.echo(f"认证已完成，但无法通知后台同步：{exc}", err=True)
                raise typer.Exit(1) from exc
    except HarborError as exc:
        if exc.code != ErrorCode.ALREADY_RUNNING:
            raise
        typer.echo("当前账号正在同步或认证，请等待其结束后重新运行 setup。", err=True)
        raise typer.Exit(1) from exc

    instance.notify_auth_recovered(account)
    typer.echo("5/5 设置完成，已通知容器后台开始首次同步")
    typer.echo("  当前认证命令现在退出；下载由主容器继续执行。")
    typer.echo(f"  查看下载日志：docker logs -f {_container_name()}")


@session_app.command("renew")
def session_renew(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    """Renew the saved session and request an immediate background sync."""

    instance = _load_application(ctx)
    account = _account(instance, account_id)
    password: str | None = None
    try:
        with instance.account_operation(account):
            try:
                password = instance.credential_store(account).read()
            except (OSError, ValueError) as exc:
                typer.echo(f"无法读取本地凭据：{exc}", err=True)
                raise typer.Exit(2) from exc
            if password is None:
                typer.echo("尚未保存密码，请先运行 icloudharbor setup。", err=True)
                raise typer.Exit(2)
            instance.auth_manager(account).logout()
            typer.echo("旧 Session 已清除，正在使用本地凭据续期。")
            _authenticate_account(instance, account, password)
            try:
                instance.repository.request_sync(account.id)
            except Exception as exc:
                typer.echo(f"认证已完成，但无法通知后台同步：{exc}", err=True)
                raise typer.Exit(1) from exc
    except HarborError as exc:
        if exc.code != ErrorCode.ALREADY_RUNNING:
            raise
        typer.echo("当前账号正在同步或认证，请等待其结束后重新运行 session renew。", err=True)
        raise typer.Exit(1) from exc
    finally:
        password = ""
    instance.notify_auth_recovered(account, renewal=True)
    typer.echo("续期完成，已通知容器后台同步。")
    typer.echo(f"当前认证命令现在退出；查看下载日志：docker logs -f {_container_name()}")


@session_app.command("status")
def session_status(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    typer.echo(instance.repository.get_auth_status(account.id).value)


@session_app.command("clear")
def session_clear(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    try:
        with instance.account_operation(account):
            instance.auth_manager(account).logout()
    except HarborError as exc:
        if exc.code != ErrorCode.ALREADY_RUNNING:
            raise
        typer.echo("当前账号正在同步或认证，请等待其结束后再清除 Session。", err=True)
        raise typer.Exit(1) from exc
    typer.echo("Session、Cookie 和本地认证状态已清除；保存的密码未删除。")


@credentials_app.command("status")
def credentials_status(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    status = "SAVED" if instance.credential_store(account).exists() else "MISSING"
    typer.echo(status)


@credentials_app.command("clear")
def credentials_clear(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    removed = instance.credential_store(account).clear()
    typer.echo("本地保存的密码已删除。" if removed else "没有找到本地保存的密码。")


def _ensure_remote_session(instance: HarborApplication, account: AccountConfig) -> None:
    try:
        status = instance.ensure_session(account)
    except Exception as exc:
        typer.echo(f"无法恢复 Apple 会话：{exc}", err=True)
        raise typer.Exit(1) from exc
    if status != AuthStatus.AUTHENTICATED:
        typer.echo("需要先执行 icloudharbor setup 或 icloudharbor session renew。", err=True)
        raise typer.Exit(1)


@libraries_app.command("list")
def libraries_list(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    _ensure_remote_session(instance, account)
    for library in instance.protocol(account).list_libraries():
        typer.echo(f"{library.library_id}\t{library.name}\t{library.library_type}")


@albums_app.command("list")
def albums_list(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
    library_id: Annotated[str, typer.Option("--library", "-l")] = "root",
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    _ensure_remote_session(instance, account)
    for album in instance.protocol(account).list_albums(library_id):
        typer.echo(f"{album.album_id}\t{album.name}\t{album.album_type}")


def _show_plan(result: SyncExecution) -> None:
    plan = result.plan
    typer.echo(f"运行 ID：{result.run_id}")
    typer.echo(f"状态：{result.status}")
    typer.echo(f"待下载：{plan.download_count}")
    typer.echo(f"预计数据：{plan.estimated_bytes} 字节")
    typer.echo(f"已存在：{len(plan.skips)}")
    typer.echo(f"待删除本地文件：{plan.local_delete_count}")
    for task in plan.local_deletions:
        typer.echo(f"  删除候选：{task.asset.filename}（Asset {task.asset.asset_id}）")
    for warning in plan.warnings:
        typer.echo(f"警告：{warning}")


@sync_app.command("plan")
def sync_plan(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
    full_scan: Annotated[bool, typer.Option("--full-scan")] = False,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    result = instance.run_sync(account, dry_run=True, force_full_scan=full_scan)
    _show_plan(result)
    if result.status == "FAILED":
        raise typer.Exit(1)


@sync_app.command("run")
def sync_run(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    full_scan: Annotated[bool, typer.Option("--full-scan")] = False,
) -> None:
    instance = _load_application(ctx)
    account = _account(instance, account_id)
    result = instance.run_sync(
        account,
        dry_run=dry_run,
        force_full_scan=full_scan,
    )
    _show_plan(result)
    if not dry_run:
        typer.echo(
            f"下载={result.downloaded_count} 删除本地={result.deleted_count} "
            f"跳过={result.skipped_count} 失败={result.failed_count} "
            f"下载数据={result.bytes_downloaded} 字节 释放空间={result.bytes_deleted} 字节"
        )
    if result.status in {"FAILED", "PARTIAL"}:
        raise typer.Exit(1)


@sync_app.command("status")
def sync_status(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", min=1, max=100)] = 10,
) -> None:
    instance = _load_application(ctx)
    runs = instance.repository.list_runs(limit)
    if not runs:
        typer.echo("还没有同步记录。")
        return
    for run in runs:
        typer.echo(
            f"{run.started_at.isoformat()}\t{run.account_id}\t{run.status}\t"
            f"下载={run.downloaded_count}\t失败={run.failed_count}\tID={run.id}"
        )


@database_app.command("check")
def database_check(ctx: typer.Context) -> None:
    instance = _load_application(ctx)
    result = instance.database.check()
    typer.echo(result)
    if result.lower() != "ok":
        raise typer.Exit(1)


@database_app.command("backup")
def database_backup(
    ctx: typer.Context,
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
) -> None:
    instance = _load_application(ctx)
    if output is None:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output = instance.config.runtime.database.with_name(f"icloudharbor-{stamp}.db.backup")
    typer.echo(str(instance.repository.backup(output)))


@app.command("doctor")
def doctor(ctx: typer.Context) -> None:
    instance = _load_application(ctx)
    health = instance.health.readiness()
    typer.echo(f"应用状态：{health.status}")
    for name, result in health.checks.items():
        typer.echo(f"{name}: {result}")
    for account in instance.config.accounts:
        typer.echo(f"auth:{account.id}: {instance.repository.get_auth_status(account.id).value}")
    if not health.ok:
        raise typer.Exit(1)


@app.command("status")
def status(ctx: typer.Context) -> None:
    instance = _load_application(ctx)
    health = instance.health.readiness()
    typer.echo(f"状态：{health.status}")
    runs = instance.repository.list_runs(1)
    if runs:
        typer.echo(yaml.safe_dump(asdict(runs[0]), allow_unicode=True, sort_keys=False))
    else:
        typer.echo("最近同步：无")


@app.command("healthcheck")
def healthcheck(
    ctx: typer.Context,
    liveness: Annotated[bool, typer.Option("--liveness")] = False,
    readiness: Annotated[bool, typer.Option("--readiness")] = False,
) -> None:
    instance = _load_application(ctx)
    result = (
        instance.health.liveness() if liveness or not readiness else instance.health.readiness()
    )
    typer.echo(result.status)
    if not result.ok:
        raise typer.Exit(1)


def _run_daemon_sync(
    instance: HarborApplication,
    account_id: str,
) -> SyncExecution:
    account = instance.config.account(account_id)
    pending = instance.repository.pending_sync_requests(account_id)
    request = pending[0] if pending else None
    if request is not None:
        LOGGER.info(
            f"收到认证后的后台同步请求：账号={account.name}；generation={request.generation}"
        )
    result = instance.run_sync(account, refresh_protocol=request is not None)
    if (
        request is not None
        and result.status != "SKIPPED_ALREADY_RUNNING"
        and instance.repository.ack_sync_request(account.id, request.generation)
    ):
        LOGGER.info(
            f"后台同步请求已处理：账号={account.name}；"
            f"generation={request.generation}；状态={result.status}"
        )
    if result.error_code in AUTH_REQUIRED_ERROR_CODES:
        _log_auth_guidance(instance, account, force=True)
    return result


def _dispatch_pending_sync_requests(
    instance: HarborApplication,
    scheduler: SchedulerService,
) -> int:
    dispatched = 0
    enabled_account_ids = {account.id for account in instance.config.accounts if account.enabled}
    for request in instance.repository.pending_sync_requests():
        if request.account_id not in enabled_account_ids:
            acknowledged = instance.repository.ack_sync_request(
                request.account_id,
                request.generation,
            )
            LOGGER.warning(
                "忽略已删除或禁用账号的后台同步请求："
                f"account_id={request.account_id}；generation={request.generation}；"
                f"acknowledged={acknowledged}"
            )
            continue
        if scheduler.trigger_now(request.account_id):
            dispatched += 1
    return dispatched


def _startup_notification(
    instance: HarborApplication,
    account: AccountConfig,
    scheduler: SchedulerService,
) -> NotificationEvent:
    lines = [f"账号：{account.name}"]
    if instance.repository.pending_sync_requests(account.id):
        lines.append("已收到同步请求，即将检查 iCloud 并下载新内容。")
    elif account.sync.run_on_start:
        if account.sync.download_delay:
            lines.append(f"将在 {account.sync.download_delay} 分钟后检查 iCloud 并下载新内容。")
        else:
            lines.append("正在检查 iCloud，有新内容时会自动下载。")
    else:
        next_runs = [
            run_at
            for job_id, run_at in scheduler.next_run_times()
            if job_id == f"sync:{account.id}"
        ]
        if next_runs:
            lines.append(f"下一次同步：{min(next_runs):%Y-%m-%d %H:%M:%S %Z}")
        else:
            lines.append("当前未安排自动同步。")
    return NotificationEvent(
        NotificationType.APP_STARTED,
        f"{instance.config.notifications.title} 容器已启动",
        "\n".join(lines),
    )


def _startup_auth_notification(
    instance: HarborApplication,
    account: AccountConfig,
) -> NotificationEvent | None:
    status = instance.repository.get_auth_status(account.id)
    credentials_exist = instance.credential_store(account).exists()
    if status == AuthStatus.AUTHENTICATED:
        return None
    if credentials_exist and status not in AUTH_ACTION_STATUSES:
        return None

    event_type = (
        NotificationType.AUTH_REQUIRED
        if instance.config.notifications.auth_required
        else NotificationType.APP_STARTED
    )
    return NotificationEvent(
        event_type,
        f"{instance.config.notifications.title} 等待 Apple 认证",
        (
            f"账号：{account.name}\n"
            "容器已启动，但 Apple 认证尚未完成。\n"
            f"请运行：{_auth_command(instance, account)}\n"
            "认证成功后后台会自动开始同步。"
        ),
        {
            "account_id": account.id,
            "error_code": "AUTH_REQUIRED",
            "startup": True,
        },
    )


@app.command("daemon")
def daemon(ctx: typer.Context) -> None:
    """Run the container's foreground scheduler without opening a network port."""
    instance = _load_application(ctx)
    account = instance.config.account()
    log_startup_summary(instance.config, account, ctx.obj)
    credential_status = "已保存" if instance.credential_store(account).exists() else "未保存"
    LOGGER.info(f"本地续期凭据：{credential_status}")
    LOGGER.info(f"Apple 会话状态：{instance.repository.get_auth_status(account.id).value}")
    if account.sync.auto_delete:
        LOGGER.info("安全模式：永不删除 iCloud；仅按最近删除精确清理已验证的本地文件")
    else:
        LOGGER.info("安全模式：只从 iCloud 备份到本地，不会删除云端或本地文件")
    _log_auth_guidance(instance, account)

    def scheduled(account_id: str) -> None:
        _run_daemon_sync(instance, account_id)
        for job_id, run_at in scheduler.next_run_times():
            if job_id == f"sync:{account_id}":
                LOGGER.info(f"下一次同步：{run_at:%Y-%m-%d %H:%M:%S %Z}")

    scheduler = SchedulerService(instance.config, scheduled)
    auth_event = _startup_auth_notification(instance, account)
    if auth_event is not None:
        if auth_event.type == NotificationType.AUTH_REQUIRED:
            instance.notify_auth_required(account, auth_event)
        else:
            instance.notifier.send(auth_event)
    scheduler.start()
    if auth_event is None:
        instance.notifier.send(_startup_notification(instance, account, scheduler))
    LOGGER.info("iCloudHarbor 调度器已启动")
    for job_id, run_at in scheduler.next_run_times():
        LOGGER.info(f"下一次任务：{job_id}；{run_at:%Y-%m-%d %H:%M:%S %Z}")
    stopped = threading.Event()

    def stop(_: int, __: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopped.wait(SYNC_REQUEST_POLL_SECONDS):
        try:
            _dispatch_pending_sync_requests(instance, scheduler)
        except Exception as exc:
            LOGGER.warning(
                "background_sync_request_poll_failed",
                error=f"{type(exc).__name__}: {exc}",
            )
    scheduler.shutdown(wait=True)
    LOGGER.info("iCloudHarbor 已安全停止")
