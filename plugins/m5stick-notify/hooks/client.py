#!/usr/bin/env python3
"""
Claude Code M5StickC Hook クライアント (BLE版)
PermissionRequest / Stop / Start / PreToolUse の全フックを1ファイルで処理する。
事前にWindowsの設定→Bluetoothでペアリングしてください（一度だけ）。

使い方:
  # Claude Code hook として使用（settings.json で指定）
  python client.py --hook-type permission   # PermissionRequest フック
  python client.py                          # Stop / Start / PreToolUse フック（自動判定）

  # テスト
  python client.py --test                   # 全イベントをテスト
  python client.py --test permission        # PermissionRequest のみ
  python client.py --test start             # Start のみ
  python client.py --test stop              # Stop のみ
  python client.py --test question          # AskUserQuestion のみ
  python client.py --test plan              # ExitPlanMode のみ
  python client.py --ble-address AA:BB:CC:DD:EE:FF --test  # BLEアドレスを手動指定してテスト
"""

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path

from bleak import BleakClient, BleakScanner

TARGET_NAME       = "M5-Claude-Notify"
CONNECT_TIMEOUT  = 5.0   # seconds
NOTIFY_SEND_WAIT = 0.5   # 通知送信後に切断するまでの待機時間 (seconds)

NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_RX_UUID      = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_TX_UUID      = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

BLE_CACHE_FILE = Path(__file__).parent / ".ble_cache.json"

# テスト用メッセージ定義
TEST_EVENTS: dict = {
    "start":      "Start",
    "stop":       "Done",
    "question":   "Q:What should I do next?",
    "plan":       "Q:Plan ready - approval needed",
}
NOTIFY_EVENTS = set(TEST_EVENTS.keys())
ALL_EVENTS    = list(TEST_EVENTS.keys()) + ["permission"]


# ---------------------------------------------------------------------------
# 引数解析
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claude Code M5Stick Hook Client (BLE)")
    parser.add_argument(
        "--ble-address",
        default="",
        metavar="XX:XX:XX:XX:XX:XX",
        help="BLE address of M5-Claude-Notify. Auto-detected if omitted.",
    )
    parser.add_argument(
        "--hook-type",
        default="auto",
        choices=["auto", "permission", "notify"],
        help="フックの種類: permission=許可リクエスト / notify=通知 / auto=JSON から自動判定 (default: auto)",
    )
    parser.add_argument(
        "--test",
        nargs="?",
        const="all",
        metavar="EVENT",
        help="テストするイベント: permission / start / stop / question / plan / all (省略時は all)",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# BLE アドレスキャッシュ（高速再接続用）
# ---------------------------------------------------------------------------

def _load_ble_cache() -> str:
    """キャッシュされた BLE アドレスを返す。なければ空文字。"""
    try:
        with open(BLE_CACHE_FILE) as f:
            return json.load(f).get("address", "")
    except Exception:
        return ""


def _save_ble_cache(address: str) -> None:
    """BLE アドレスをキャッシュファイルに保存する。"""
    try:
        with open(BLE_CACHE_FILE, "w") as f:
            json.dump({"address": address.upper()}, f)
    except Exception:
        pass


def _clear_ble_cache() -> None:
    """BLE キャッシュを削除する（再ペアリング後の不整合解消用）。"""
    try:
        BLE_CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# BLE デバイス検索
# ---------------------------------------------------------------------------

async def find_ble_device(use_cache: bool = True) -> str:
    """M5-Claude-Notify の BLE アドレスを返す（キャッシュ優先）。"""
    # 高速パス: キャッシュ済みアドレスを試す
    cached = _load_ble_cache() if use_cache else ""
    if cached:
        sys.stderr.write(f"[client] Trying cached address: {cached}\n")
        try:
            device = await asyncio.wait_for(
                BleakScanner.find_device_by_address(cached),
                timeout=2.0,
            )
            if device is not None:
                sys.stderr.write(f"[client] Found (cache): {cached}\n")
                return cached
        except Exception:
            pass
        sys.stderr.write(f"[client] Cache miss, scanning...\n")

    # スキャンパス: デバイス名で検索
    sys.stderr.write(f"[client] Scanning for '{TARGET_NAME}'...\n")
    device = await asyncio.wait_for(
        BleakScanner.find_device_by_name(TARGET_NAME),
        timeout=CONNECT_TIMEOUT,
    )
    if device is None:
        raise RuntimeError(
            f"'{TARGET_NAME}' が見つかりません。\n"
            "  → M5StickC の電源がオンでアドバタイズ中か確認してください。\n"
            "  → または --ble-address XX:XX:XX:XX:XX:XX で手動指定してください。"
        )
    _save_ble_cache(device.address)
    sys.stderr.write(f"[client] Found (scan): {device.address}\n")
    return device.address


# ---------------------------------------------------------------------------
# PermissionRequest: コマンド送信 → ALLOW/DENY 待機
# ---------------------------------------------------------------------------

async def communicate_permission_ble(address: str, display: str) -> str:
    """許可リクエストを M5Stick に送信し、ボタン応答を待つ。
    接続失敗・切断時は 3 秒後に再接続して同じコマンドを再送する（無限待機）。
    """
    payload = (display + "\n").encode("utf-8")
    while True:
        sys.stderr.write(f"[client] Connecting to {address} (permission)...\n")
        try:
            async with BleakClient(address, timeout=CONNECT_TIMEOUT) as client:
                sys.stderr.write("[client] Connected.\n")
                await client.write_gatt_char(NUS_RX_UUID, payload, response=True)
                sys.stderr.write("[client] Command sent, polling for button...\n")

                # READ ポーリング: 0.5s ごとに TX char を読む（タイムアウトなし）
                # 0x00=未押下, 0x01=ALLOW, 0x02=DENY
                while True:
                    data = await client.read_gatt_char(NUS_TX_UUID)
                    if data and data[0] != 0x00:
                        sys.stderr.write(f"[client] TX read: {data!r}\n")
                    if data and data[0] == 0x01:
                        sys.stderr.write("[client] M5Stick responded: ALLOW\n")
                        return "ALLOW"
                    if data and data[0] == 0x02:
                        sys.stderr.write("[client] M5Stick responded: DENY\n")
                        return "DENY"
                    await asyncio.sleep(0.5)
        except Exception as e:
            sys.stderr.write(f"[client] Connection error: {e} — retrying in 3s...\n")
            await asyncio.sleep(3.0)
            # デバイスを再スキャンしてアドレスを更新（M5Stick 再起動対応）
            try:
                address = await find_ble_device(use_cache=False)
            except Exception:
                pass  # スキャン失敗は無視して同じアドレスで再試行


def output_decision(decision: str) -> None:
    """PermissionRequest の結果を stdout に出力"""
    behavior = "allow" if decision == "allow" else "deny"
    out: dict = {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": behavior},
        }
    }
    if behavior == "deny":
        out["hookSpecificOutput"]["decision"]["message"] = "Denied by M5Stick"
    print(json.dumps(out))
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Notify: メッセージ送信のみ（返答待ちなし）
# ---------------------------------------------------------------------------

async def communicate_notify_ble(address: str, message: str) -> None:
    """通知を M5Stick に送信する（返答待ちなし）。"""
    sys.stderr.write(f"[client] Connecting to {address} (notify)...\n")

    async with BleakClient(address, timeout=CONNECT_TIMEOUT) as client:
        sys.stderr.write("[client] Connected.\n")
        try:
            await client.request_mtu(512)
        except AttributeError:
            pass  # Windows WinRT backend handles MTU automatically

        payload = f"NOTIFY:{message}\n".encode("utf-8")
        sys.stderr.write("[client] Writing to RX characteristic...\n")
        await client.write_gatt_char(NUS_RX_UUID, payload, response=True)
        sys.stderr.write(f"[client] Sent notification: {message!r}\n")

        await asyncio.sleep(NOTIFY_SEND_WAIT)

    sys.stderr.write("[client] Done.\n")


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------

async def run_tests_ble(address: str, event: str) -> None:
    """指定イベントのテストを実行する（event='all' は全イベントを順番に実施）。"""
    sys.stderr.write(f"[test] Using BLE address: {address}\n")

    if event not in ALL_EVENTS + ["all"]:
        sys.stderr.write(
            f"[test] Unknown event: {event!r}\n"
            f"  Choose from: {', '.join(ALL_EVENTS + ['all'])}\n"
        )
        sys.exit(1)

    # notify 系イベントのテスト
    notify_targets = (
        list(TEST_EVENTS.items()) if event == "all"
        else [(event, TEST_EVENTS[event])] if event in NOTIFY_EVENTS
        else []
    )
    for name, message in notify_targets:
        sys.stderr.write(f"[test] --- {name} ---\n")
        try:
            await communicate_notify_ble(address, message)
            sys.stderr.write(f"[test] '{name}' OK\n")
        except Exception as e:
            sys.stderr.write(f"[test] '{name}' FAILED: {type(e).__name__}: {e}\n")
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
        if event == "all" and name != list(TEST_EVENTS)[-1]:
            sys.stderr.write("[test] 次のイベントまで 3 秒待機...\n")
            await asyncio.sleep(3)

    # permission テスト
    if event in ("all", "permission"):
        if event == "all":
            sys.stderr.write("\n[test] --- permission ---\n")
        try:
            decision = await communicate_permission_ble(address, "TEST: Allow this test?")
            sys.stderr.write(f"[test] Result: {decision}\n")
            sys.stderr.write("[test] 'permission' OK\n")
        except Exception as e:
            sys.stderr.write(f"[test] 'permission' FAILED: {type(e).__name__}: {e}\n")
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

async def _async_main(args: argparse.Namespace) -> None:
    # ---- テストモード ----
    if args.test is not None:
        try:
            if args.ble_address:
                address = args.ble_address
            else:
                try:
                    address = await find_ble_device(use_cache=True)
                except Exception:
                    sys.stderr.write("[test] Cache/scan failed, retrying with fresh scan...\n")
                    _clear_ble_cache()
                    address = await find_ble_device(use_cache=False)
        except Exception as e:
            sys.stderr.write(f"[test] {e}\n")
            sys.exit(1)
        await run_tests_ble(address, args.test)
        return

    # ---- フックモード ----
    raw = sys.stdin.read()
    try:
        hook_event = json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write("[client] Failed to parse stdin JSON\n")
        if args.hook_type == "permission":
            output_decision("deny")
        sys.exit(0)

    tool_name  = hook_event.get("tool_name", "")
    tool_input = hook_event.get("tool_input", {})

    # hook_type を自動判定
    hook_type = args.hook_type
    if hook_type == "auto":
        hook_type = "permission" if (tool_name and tool_name not in ("AskUserQuestion", "ExitPlanMode")) else "notify"

    async def _get_address(use_cache: bool = True) -> str:
        return args.ble_address if args.ble_address else await find_ble_device(use_cache)

    async def _run_with_retry(operation, *op_args) -> object:
        """BLE 操作を実行し、失敗時はキャッシュをクリアして一度だけ再試行する。"""
        try:
            address = await _get_address(use_cache=True)
            return await operation(address, *op_args)
        except Exception as first_err:
            if args.ble_address:
                raise  # 手動指定アドレスの場合は再試行しない
            sys.stderr.write(
                f"[client] Connection failed ({first_err}), "
                "clearing cache and retrying with scan...\n"
            )
            _clear_ble_cache()
            address = await _get_address(use_cache=False)
            return await operation(address, *op_args)

    if hook_type == "permission":
        # PermissionRequest: コマンドを表示して ALLOW/DENY を待つ
        sys.stderr.write(f"[client] PermissionRequest: {tool_name}\n")
        display = f"{tool_name}: {json.dumps(tool_input)}"[:120]
        try:
            decision = await _run_with_retry(communicate_permission_ble, display)
            output_decision("allow" if decision == "ALLOW" else "deny")
        except Exception as e:
            sys.stderr.write(f"[client] {e} → M5Stick unavailable, skipping hook\n")

    else:
        # Notify: Stop / Start / PreToolUse(AskUserQuestion, ExitPlanMode)
        title   = hook_event.get("title", "")
        message = hook_event.get("message", "")

        if tool_name == "AskUserQuestion":
            display = f"Q:{tool_input.get('question', '')}"[:80]
        elif tool_name == "ExitPlanMode":
            display = "Q:Plan ready - approval needed"
        elif title:
            display = title[:80]
        elif message:
            display = message[:80]
        elif "stop_hook_active" in hook_event:
            display = "Done"
        else:
            display = "Start"

        sys.stderr.write(f"[client] Notify: {display!r}\n")
        try:
            await _run_with_retry(communicate_notify_ble, display)
        except Exception as e:
            sys.stderr.write(f"[client] {e} → M5Stick unavailable, skipping notification\n")


def main() -> None:
    args = parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
