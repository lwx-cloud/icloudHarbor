"""Command-line product surface for Docker and NAS operations."""

from __future__ import annotations

import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import structlog
import typer
from pydantic import ValidationError

from icloudharbor import __version__
from icloudharbor.application import HarborApplication
from icloudharbor.config.loader import (
    bootstrap_config,
    config_mode_from_env,
    config_path_from_env,
)
from icloudharbor.config.models import AccountConfig
from icloudharbor.notify import NotificationEvent
from icloudharbor.notify.base import NotificationType
from icloudharbor.observability.logging import configure_logging
from icloudharbor.observability.startup import log_startup_summary, startup_summary
from icloudharbor.photos.engine import SyncExecution, SyncPreview
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
    add_completion=False,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"iCloudHarbor {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config_file: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="配置文件或 env 模式快照路径。"),
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
        _echo_configuration_error("配置或初始化失败", exc)
        raise typer.Exit(2) from exc


def _echo_configuration_error(prefix: str, exc: Exception) -> None:
    typer.echo(f"iCloudHarbor {__version__} {prefix}：{redact(exc)}", err=True)


def _account(instance: HarborApplication) -> AccountConfig:
    return instance.config.account()


def _display_apple_id(instance: HarborApplication, account: AccountConfig) -> str:
    if instance.config.security.redact_apple_id:
        return redact(account.apple_id)
    return account.apple_id


def _container_name() -> str:
    return os.environ.get("IH_CONTAINER_NAME", "").strip() or "icloudharbor"


def _auth_command(instance: HarborApplication, account: AccountConfig) -> str:
    del instance, account
    return f"docker exec -it {_container_name()} icloudharbor setup"


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


@app.command("bootstrap", hidden=True)
def bootstrap(ctx: typer.Context) -> None:
    """Generate an env snapshot or validate the advanced YAML configuration."""

    try:
        config, created = bootstrap_config(ctx.obj)
        mode = config_mode_from_env()
    except Exception as exc:
        _echo_configuration_error("无法自动生成配置", exc)
        raise typer.Exit(2) from exc
    if mode == "yaml":
        typer.echo(f"现有配置有效：{ctx.obj}（yaml 模式：已校验高级配置）")
    elif created:
        typer.echo(f"已按当前 IH_* 参数生成配置：{ctx.obj}（账号数={len(config.accounts)}）")
    else:
        typer.echo(f"配置有效：{ctx.obj}（env 模式：已按当前 IH_* 参数同步）")


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


def _validate_photos_access(
    instance: HarborApplication,
    account: AccountConfig,
) -> None:
    protocol = instance.protocol(account)
    libraries = protocol.list_libraries()
    by_selector = {
        selector: library
        for library in libraries
        for selector in (library.library_id, library.name)
    }
    missing = [selector for selector in account.libraries if selector not in by_selector]
    if missing:
        typer.echo(f"图库不可访问：{', '.join(missing)}", err=True)
        raise typer.Exit(1)
    for selector in account.libraries:
        library = by_selector[selector]
        album_id = None
        configured_albums = [*account.filters.albums, *account.filters.exclude_albums]
        if configured_albums:
            albums = protocol.list_albums(library.library_id)
            by_album = {key: album for album in albums for key in (album.album_id, album.name)}
            missing_albums = [name for name in configured_albums if name not in by_album]
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


def _request_background_sync(
    instance: HarborApplication,
    account: AccountConfig,
) -> bool:
    if instance.repository.pending_sync_requests(account.id):
        return False
    instance.repository.request_sync(account.id)
    return True


@app.command("setup")
def setup(ctx: typer.Context) -> None:
    """建立或续期 Apple 认证。"""

    instance = _load_application(ctx)
    account = _account(instance)
    credential_store = instance.credential_store(account)
    renewal = credential_store.exists()
    heading = "***** iCloudHarbor 认证续期 *****" if renewal else "***** iCloudHarbor 初始化 *****"
    typer.echo(heading)
    for line in startup_summary(instance.config, account, ctx.obj):
        typer.echo(f"  {line}")

    health = instance.health.readiness()
    typer.echo("配置、数据库和下载目录检查")
    for name, result in health.checks.items():
        typer.echo(f"  {name}: {result}")
    if not health.ok:
        typer.echo("设置停止：请先修复以上本地检查。", err=True)
        raise typer.Exit(2)

    password: str | None = None
    try:
        with instance.account_operation(account):
            if renewal:
                try:
                    password = credential_store.read()
                except (OSError, ValueError) as exc:
                    typer.echo(f"无法读取本地凭据：{exc}", err=True)
                    typer.echo("请先运行 icloudharbor reset，再重新运行 setup。", err=True)
                    raise typer.Exit(2) from exc
                if password is None:
                    typer.echo("本地凭据不完整，请先运行 icloudharbor reset。", err=True)
                    raise typer.Exit(2)
                typer.echo("正在使用本地保存的密码续期 Apple 会话。")
            else:
                typer.echo("Apple Account 密码与双重认证")
                password = _password(account)

            instance.auth_manager(account).logout()
            _authenticate_account(instance, account, password)

            if not renewal:
                typer.echo("iCloud Photos 访问检查")
                try:
                    _validate_photos_access(instance, account)
                except typer.Exit:
                    raise
                except Exception as exc:
                    typer.echo(f"iCloud Photos 检查失败：{exc}", err=True)
                    raise typer.Exit(1) from exc

                typer.echo("保存本地续期凭据")
                try:
                    credential_store.write(password)
                except (OSError, ValueError) as exc:
                    typer.echo(f"无法保存本地凭据：{exc}", err=True)
                    raise typer.Exit(1) from exc
                typer.echo("  凭据: AES-256-GCM / 文件权限 0600")

            try:
                submitted = _request_background_sync(instance, account)
            except Exception as exc:
                typer.echo(f"认证已完成，但无法通知后台同步：{exc}", err=True)
                raise typer.Exit(1) from exc
    except HarborError as exc:
        if exc.code != ErrorCode.ALREADY_RUNNING:
            raise
        typer.echo("当前账号正在同步或认证，请等待其结束后重新运行 setup。", err=True)
        raise typer.Exit(1) from exc
    finally:
        password = ""

    instance.notify_auth_recovered(account, renewal=renewal)
    action = "续期完成" if renewal else "设置完成"
    queue_state = "后台同步任务已提交" if submitted else "后台已有同步任务"
    typer.echo(f"{action}，{queue_state}。")
    typer.echo(f"查看日志：docker logs -f {_container_name()}")


@app.command("reset")
def reset(ctx: typer.Context) -> None:
    """清除 Apple Session 和本地保存的密码。"""

    instance = _load_application(ctx)
    account = _account(instance)
    typer.echo("将清除 Apple Session、Cookie 和本地保存的密码。")
    typer.echo("不会删除已下载照片、SQLite 数据库或配置。")
    if not typer.confirm("继续"):
        typer.echo("已取消。")
        return
    try:
        with instance.account_operation(account):
            instance.auth_manager(account).logout()
            instance.credential_store(account).clear()
    except HarborError as exc:
        if exc.code != ErrorCode.ALREADY_RUNNING:
            raise
        typer.echo("当前正在同步或认证，请等待结束后再运行 reset。", err=True)
        raise typer.Exit(1) from exc
    typer.echo("认证信息已清除；下次运行 setup 时会重新询问密码。")


def _ensure_remote_session(instance: HarborApplication, account: AccountConfig) -> None:
    try:
        status = instance.ensure_session(account)
    except Exception as exc:
        typer.echo(f"无法恢复 Apple 会话：{exc}", err=True)
        raise typer.Exit(1) from exc
    if status != AuthStatus.AUTHENTICATED:
        typer.echo("需要先执行 icloudharbor setup。", err=True)
        raise typer.Exit(1)


@app.command("list")
def list_remote(ctx: typer.Context) -> None:
    """列出所有可访问图库及其相册。"""

    instance = _load_application(ctx)
    account = _account(instance)
    _ensure_remote_session(instance, account)
    protocol = instance.protocol(account)
    libraries = protocol.list_libraries()
    if not libraries:
        typer.echo("没有可访问的图库。")
        return
    for library in libraries:
        typer.echo(f"图库：{library.name} [{library.library_id}]")
        albums = protocol.list_albums(library.library_id)
        if not albums:
            typer.echo("  相册：无")
            continue
        for album in albums:
            typer.echo(f"  相册：{album.name} [{album.album_id}]")


def _show_preview(result: SyncPreview) -> None:
    plan = result.plan
    typer.echo(
        f"计划：扫描 {result.asset_count} 个 iCloud 项目；"
        f"下载 {plan.download_count} 个文件；"
        f"已有 {len(plan.skips)} 个文件；"
        f"删除 {plan.local_delete_count} 个本地文件"
    )
    typer.echo(f"预计数据：{plan.estimated_bytes} 字节")
    for task in plan.downloads:
        typer.echo(f"  下载：{task.relative_path.as_posix()}")
    for task in plan.updates:
        typer.echo(f"  修复：{task.relative_path.as_posix()}")
    for deletion_task in plan.local_deletions:
        for local_file in deletion_task.local_files:
            typer.echo(f"  删除：{local_file.relative_path}")
            for artifact in local_file.artifacts:
                typer.echo(f"  删除：{artifact.root}/{artifact.relative_path}")
    if plan.unmatched_deleted_count:
        typer.echo(
            f"最近删除共 {result.recently_deleted_count} 个项目；"
            f"其中 {plan.unmatched_deleted_count} 个没有本地记录，已忽略。"
        )
    for warning in plan.warnings:
        typer.echo(f"警告：{warning}")


@app.command("plan")
def plan(ctx: typer.Context) -> None:
    """只读预览下载、修复和本地删除候选。"""

    instance = _load_application(ctx)
    account = _account(instance)
    try:
        result = instance.preview_sync(account)
    except HarborError as exc:
        if exc.code == ErrorCode.ALREADY_RUNNING:
            typer.echo("当前正在同步或认证，请等待结束后再查看计划。", err=True)
        elif exc.code == ErrorCode.AUTH_REQUIRED:
            typer.echo("需要先执行 icloudharbor setup。", err=True)
        else:
            typer.echo(f"无法生成计划：{exc}", err=True)
        raise typer.Exit(1) from exc
    _show_preview(result)


@app.command("sync")
def sync(ctx: typer.Context) -> None:
    """向容器后台提交一次同步任务。"""

    instance = _load_application(ctx)
    account = _account(instance)
    submitted = _request_background_sync(instance, account)
    typer.echo("同步任务已提交。" if submitted else "后台已有同步任务。")
    typer.echo(f"查看日志：docker logs -f {_container_name()}")


@app.command("backup")
def backup(ctx: typer.Context) -> None:
    """创建带时间戳的 SQLite 在线备份。"""

    instance = _load_application(ctx)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = instance.config.runtime.database.with_name(f"icloudharbor-{stamp}.db.backup")
    typer.echo(str(instance.repository.backup(output)))


def _schedule_text(account: AccountConfig) -> str:
    schedule = account.sync.schedule
    if schedule is None:
        text = "未安排"
    elif isinstance(schedule, str):
        text = f"Cron {schedule}" if len(schedule.split()) == 5 else f"每 {schedule}"
    elif schedule.interval:
        text = f"每 {schedule.interval}"
    else:
        text = f"Cron {schedule.cron}"
    if account.sync.run_on_start:
        text += "；启动时检查"
    return text


@app.command("status")
def status(ctx: typer.Context) -> None:
    """查看服务、认证、同步和调度状态。"""

    instance = _load_application(ctx)
    account = _account(instance)
    health = instance.health.readiness()
    auth_status = instance.repository.get_auth_status(account.id).value
    credentials = "已保存" if instance.credential_store(account).exists() else "未保存"
    runs = [
        run
        for run in instance.repository.list_runs(20)
        if not run.dry_run and run.status != "SKIPPED_ALREADY_RUNNING"
    ]
    pending = bool(instance.repository.pending_sync_requests(account.id))
    typer.echo(f"iCloudHarbor {__version__}：{'正常' if health.ok else '异常'}")
    typer.echo(
        f"账号：{_display_apple_id(instance, account)}；认证={auth_status}；凭据={credentials}"
    )
    if runs:
        latest = runs[0]
        typer.echo(
            f"最近同步：{latest.started_at.isoformat()}；{latest.status}；"
            f"下载={latest.downloaded_count}；失败={latest.failed_count}"
        )
    else:
        typer.echo("最近同步：无")
    typer.echo(f"计划：{_schedule_text(account)}")
    typer.echo(f"后台任务：{'等待处理' if pending else '无'}")
    if not health.ok:
        for name, result in health.checks.items():
            if result != "ok":
                typer.echo(f"异常：{name}={result}")
        raise typer.Exit(1)


@app.command("healthcheck", hidden=True)
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


@app.command("daemon", hidden=True)
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

    def scheduled(account_id: str) -> SyncExecution:
        result = _run_daemon_sync(instance, account_id)
        for job_id, run_at in scheduler.next_run_times():
            if job_id == f"sync:{account_id}":
                LOGGER.info(f"下一次同步：{run_at:%Y-%m-%d %H:%M:%S %Z}")
        return result

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
