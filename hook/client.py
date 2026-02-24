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
CONNECT_TIMEOUT   = 5.0   # seconds
HANDSHAKE_TIMEOUT = 10.0  # seconds
NOTIFY_SEND_WAIT  = 0.5   # 通知送信後に切断するまでの待機時間 (seconds)
BTN_TIMEOUT       = 60.0  # ボタン押下待機タイムアウト (seconds)

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


# ---------------------------------------------------------------------------
# BLE デバイス検索
# ---------------------------------------------------------------------------

async def find_ble_device() -> str:
    """M5-Claude-Notify の BLE アドレスを返す（キャッシュ優先）。"""
    # 高速パス: キャッシュ済みアドレスを試す
    cached = _load_ble_cache()
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
# BLE 共通: ハンドシェイク
# ---------------------------------------------------------------------------

async def _handshake_ble(client: BleakClient, queue: asyncio.Queue) -> None:
    """TX Characteristic の通知を購読し、'hello' を待つ。"""
    loop = asyncio.get_running_loop()

    def handler(sender, data: bytearray) -> None:
        line = data.decode("utf-8", errors="ignore").replace('\x00', '').strip()
        loop.call_soon_threadsafe(queue.put_nowait, line)

    sys.stderr.write("[client] Subscribing to TX characteristic...\n")
    await client.start_notify(NUS_TX_UUID, handler)
    sys.stderr.write("[client] Waiting for hello...\n")

    greeting = await asyncio.wait_for(queue.get(), timeout=HANDSHAKE_TIMEOUT)
    if greeting.lower() != "hello":
        raise RuntimeError(f"Handshake failed: expected 'hello', got {greeting!r}")
    sys.stderr.write("[client] Handshake OK\n")


# ---------------------------------------------------------------------------
# PermissionRequest: コマンド送信 → ALLOW/DENY 待機
# ---------------------------------------------------------------------------

async def communicate_permission_ble(address: str, display: str) -> str:
    """許可リクエストを M5Stick に送信し、ボタン応答を待つ。"""
    sys.stderr.write(f"[client] Connecting to {address} (permission)...\n")
    queue: asyncio.Queue = asyncio.Queue()

    async with BleakClient(address, timeout=CONNECT_TIMEOUT) as client:
        sys.stderr.write("[client] Connected.\n")
        try:
            await client.request_mtu(512)
        except AttributeError:
            pass  # Windows WinRT backend handles MTU automatically
        await _handshake_ble(client, queue)

        payload = (display + "\n").encode("utf-8")
        sys.stderr.write("[client] Writing to RX characteristic...\n")
        await client.write_gatt_char(NUS_RX_UUID, payload, response=False)
        sys.stderr.write("[client] Sent command, waiting for button...\n")

        response = await asyncio.wait_for(queue.get(), timeout=BTN_TIMEOUT)
        msg = response.strip().upper()
        if msg not in ("ALLOW", "DENY"):
            raise RuntimeError(f"Unexpected response: {msg!r}")

        sys.stderr.write(f"[client] M5Stick responded: {msg}\n")
        return msg


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
    queue: asyncio.Queue = asyncio.Queue()

    async with BleakClient(address, timeout=CONNECT_TIMEOUT) as client:
        sys.stderr.write("[client] Connected.\n")
        try:
            await client.request_mtu(512)
        except AttributeError:
            pass  # Windows WinRT backend handles MTU automatically
        await _handshake_ble(client, queue)

        payload = f"NOTIFY:{message}\n".encode("utf-8")
        sys.stderr.write("[client] Writing to RX characteristic...\n")
        await client.write_gatt_char(NUS_RX_UUID, payload, response=False)
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
            address = args.ble_address if args.ble_address else await find_ble_device()
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

    if hook_type == "permission":
        # PermissionRequest: コマンドを表示して ALLOW/DENY を待つ
        sys.stderr.write(f"[client] PermissionRequest: {tool_name}\n")
        display = f"{tool_name}: {json.dumps(tool_input)}"[:120]
        try:
            address  = args.ble_address if args.ble_address else await find_ble_device()
            decision = await communicate_permission_ble(address, display)
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
            address = args.ble_address if args.ble_address else await find_ble_device()
            await communicate_notify_ble(address, display)
        except Exception as e:
            sys.stderr.write(f"[client] {e} → M5Stick unavailable, skipping notification\n")


def main() -> None:
    args = parse_args()
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    main()
