"""Command-line product surface for Docker and NAS operations."""

from __future__ import annotations

import signal
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

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
from icloudharbor.photos.engine import SyncExecution
from icloudharbor.protocol.models import AssetQuery, AuthResult, AuthStatus
from icloudharbor.scheduler.service import SchedulerService
from icloudharbor.security.prompt import masked_password_prompt
from icloudharbor.security.redaction import redact

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
        result = manager.login(password)
        if result.status == AuthStatus.TWO_FACTOR_REQUIRED:
            typer.echo("需要双重认证。")
            code = typer.prompt("验证码", hide_input=False)
            result = manager.verify(result.challenge_id or "", code)
            code = ""
        typer.echo(f"{result.status.value}：{result.message or ''}")
        if result.status != AuthStatus.AUTHENTICATED:
            raise typer.Exit(1)
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
    """Configure credentials, authenticate, and probe iCloud Photos."""

    instance = _load_application(ctx)
    account = _account(instance, account_id)
    typer.echo(f"设置账号：{account.id}（{_display_apple_id(instance, account)}）")

    health = instance.health.readiness()
    typer.echo("1/5 配置、数据库和下载目录检查")
    for name, result in health.checks.items():
        typer.echo(f"  {name}: {result}")
    if not health.ok:
        typer.echo("设置停止：请先修复以上本地检查。", err=True)
        raise typer.Exit(2)

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
        libraries = {item.library_id for item in protocol.list_libraries()}
        if "root" not in libraries:
            typer.echo("个人图库不可访问。", err=True)
            raise typer.Exit(1)
        protocol.list_assets(AssetQuery(account.id, "root", limit=1))
    except typer.Exit:
        raise
    except Exception as exc:
        typer.echo(f"iCloud Photos 检查失败：{exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo("  个人图库: ok")

    typer.echo("5/5 设置完成")
    typer.echo("下一步：先运行 icloudharbor sync plan，再决定是否执行正式同步。")


@session_app.command("renew")
def session_renew(
    ctx: typer.Context,
    account_id: Annotated[str | None, typer.Option("--account", "-a")] = None,
) -> None:
    """Clear the expired session and renew it using the saved credential."""

    instance = _load_application(ctx)
    account = _account(instance, account_id)
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
    try:
        _authenticate_account(instance, account, password)
    finally:
        password = ""


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
    instance.auth_manager(account).logout()
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
            f"下载={result.downloaded_count} 跳过={result.skipped_count} "
            f"失败={result.failed_count} 数据={result.bytes_downloaded} 字节"
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


@app.command("daemon")
def daemon(ctx: typer.Context) -> None:
    """Run the container's foreground scheduler without opening a network port."""
    instance = _load_application(ctx)

    def scheduled(account_id: str) -> None:
        account = instance.config.account(account_id)
        instance.run_sync(account)

    scheduler = SchedulerService(instance.config, scheduled)
    scheduler.start()
    instance.notifier.send(
        NotificationEvent(
            NotificationType.APP_STARTED,
            "iCloudHarbor 已启动",
            "容器调度器已启动，等待下一次同步计划。",
        )
    )
    typer.echo("iCloudHarbor 调度器已启动。")
    stopped = threading.Event()

    def stop(_: int, __: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while not stopped.wait(30):
        pass
    scheduler.shutdown(wait=True)
    typer.echo("iCloudHarbor 已安全停止。")
