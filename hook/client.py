#!/usr/bin/env python3
"""
Claude Code M5StickC Hook クライアント (Bluetooth Classic SPP版)
PermissionRequest / Stop / Start / PreToolUse の全フックを1ファイルで処理する。
事前に Windows の設定で M5StickC をペアリングしてください。

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
  python client.py --com-port COM5 --test   # COM ポートを手動指定してテスト
"""

import argparse
import json
import re
import sys
import threading
import time
import winreg
import serial
import serial.tools.list_ports

TARGET_NAME       = "M5-Claude-Notify"
CONNECT_TIMEOUT   = 5.0   # seconds
HANDSHAKE_TIMEOUT = 10.0  # seconds
BAUD_RATE         = 9600
NOTIFY_SEND_WAIT  = 0.5   # 通知送信後に切断するまでの待機時間 (seconds)

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
    parser = argparse.ArgumentParser(description="Claude Code M5Stick Hook Client")
    parser.add_argument(
        "--com-port",
        default="",
        metavar="COMx",
        help="COM port for M5-Claude-Notify (e.g. COM5). Auto-detected if omitted.",
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
# Bluetooth ポート検出
# ---------------------------------------------------------------------------

def get_bt_device_name(mac_hex: str) -> str:
    """Windows レジストリから Bluetooth デバイス名を取得"""
    reg_path = r"SYSTEM\CurrentControlSet\Services\BTHPORT\Parameters\Devices"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path) as devices_key:
            i = 0
            while True:
                try:
                    subkey_name = winreg.EnumKey(devices_key, i)
                    if subkey_name.lower() == mac_hex.lower():
                        with winreg.OpenKey(devices_key, subkey_name) as dev_key:
                            raw, _ = winreg.QueryValueEx(dev_key, "Name")
                            if isinstance(raw, bytes):
                                return raw.rstrip(b"\x00").decode("utf-8", errors="ignore")
                            return str(raw)
                    i += 1
                except OSError:
                    break
    except OSError:
        pass
    return ""


def find_comport() -> str:
    """ペアリング済み 'M5-Claude-Notify' の COM ポートを自動検出"""
    sys.stderr.write("[client] Auto-detecting COM port for M5-Claude-Notify...\n")

    bt_ports = []
    for port_info in serial.tools.list_ports.comports():
        hwid = port_info.hwid or ""
        desc = port_info.description or ""
        sys.stderr.write(f"[client]   {port_info.device}: {desc!r} hwid={hwid}\n")

        if "BTHENUM" not in hwid:
            continue

        mac = ""
        m = re.search(r"BLUETOOTHDEVICE_([0-9A-Fa-f]{12})", hwid)
        if m:
            mac = m.group(1)
        else:
            m = re.search(r"&0&([0-9A-Fa-f]{12})[_&]", hwid)
            if m and m.group(1) != "000000000000":
                mac = m.group(1)

        sys.stderr.write(f"[client]     mac={mac or '(none)'}\n")
        bt_ports.append((port_info.device, mac))

    for device, mac in bt_ports:
        if not mac:
            continue
        name = get_bt_device_name(mac)
        if not (name and TARGET_NAME.lower() in name.lower()):
            continue
        sys.stderr.write(f"[client] Found (MAC): {device} ({name!r})\n")
        return device

    for port_info in serial.tools.list_ports.comports():
        if TARGET_NAME.lower() in (port_info.description or "").lower():
            sys.stderr.write(f"[client] Found (description): {port_info.device}\n")
            return port_info.device

    raise RuntimeError(
        f"'{TARGET_NAME}' の COM ポートが見つかりません。\n"
        "  → Windows の設定でペアリングされているか確認してください。\n"
        "  → または --com-port COMx で手動指定してください。"
    )


# ---------------------------------------------------------------------------
# Bluetooth 共通: 接続 + ハンドシェイク
# ---------------------------------------------------------------------------

def _open_serial(port_name: str) -> serial.Serial:
    """タイムアウト付きで Serial を開く"""
    result: list = [None, None]

    def do_open() -> None:
        try:
            result[0] = serial.Serial(port_name, BAUD_RATE, timeout=None)
        except Exception as e:
            result[1] = e

    t = threading.Thread(target=do_open, daemon=True)
    t.start()
    deadline = time.monotonic() + CONNECT_TIMEOUT
    while t.is_alive() and time.monotonic() < deadline:
        t.join(timeout=0.5)
    if t.is_alive():
        raise RuntimeError(f"Connection timeout ({CONNECT_TIMEOUT}s)")
    if result[1] is not None:
        raise result[1]
    return result[0]


def _handshake(ser: serial.Serial) -> None:
    """M5Stick からの 'hello' を待つ"""
    hello_result: list = [None, None]

    def do_hello() -> None:
        try:
            hello_result[0] = ser.readline()
        except Exception as e:
            hello_result[1] = e

    ht = threading.Thread(target=do_hello, daemon=True)
    ht.start()
    deadline = time.monotonic() + HANDSHAKE_TIMEOUT
    while ht.is_alive() and time.monotonic() < deadline:
        ht.join(timeout=0.5)
    if ht.is_alive():
        raise RuntimeError(f"Handshake timeout ({HANDSHAKE_TIMEOUT}s) - wrong port?")
    greeting = (hello_result[0] or b"").decode("utf-8", errors="ignore").strip().lower()
    if greeting != "hello":
        raise RuntimeError(f"Handshake failed: expected 'hello', got {greeting!r}")
    sys.stderr.write("[client] Handshake OK\n")
    ser.reset_input_buffer()


# ---------------------------------------------------------------------------
# PermissionRequest: コマンド送信 → ALLOW/DENY 待機
# ---------------------------------------------------------------------------

def communicate_permission(port_name: str, display: str) -> str:
    """許可リクエストを M5Stick に送信し、ボタン応答を待つ"""
    sys.stderr.write(f"[client] Connecting to {port_name} (permission)...\n")
    with _open_serial(port_name) as ser:
        _handshake(ser)

        ser.write((display + "\n").encode("utf-8"))
        ser.flush()
        sys.stderr.write("[client] Sent command, waiting for button...\n")

        read_result: list = [None, None]

        def do_read() -> None:
            try:
                read_result[0] = ser.readline()
            except Exception as e:
                read_result[1] = e

        rt = threading.Thread(target=do_read, daemon=True)
        rt.start()
        while rt.is_alive():
            rt.join(timeout=0.5)
        if read_result[1] is not None:
            raise read_result[1]
        line = read_result[0]
        if not line:
            raise RuntimeError("Button read failed (empty response)")

        msg = line.decode("utf-8", errors="ignore").strip().upper()
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

def communicate_notify(port_name: str, message: str) -> None:
    """通知を M5Stick に送信する（返答待ちなし）"""
    sys.stderr.write(f"[client] Connecting to {port_name} (notify)...\n")
    with _open_serial(port_name) as ser:
        _handshake(ser)

        payload = f"NOTIFY:{message}\n"
        ser.write(payload.encode("utf-8"))
        ser.flush()
        sys.stderr.write(f"[client] Sent notification: {message!r}\n")

        time.sleep(NOTIFY_SEND_WAIT)

    sys.stderr.write("[client] Done.\n")


# ---------------------------------------------------------------------------
# テスト
# ---------------------------------------------------------------------------

def run_tests(port_name: str, event: str) -> None:
    """指定イベントのテストを実行する（event='all' は全イベントを順番に実施）"""
    sys.stderr.write(f"[test] Using port: {port_name}\n")

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
            communicate_notify(port_name, message)
            sys.stderr.write(f"[test] '{name}' OK\n")
        except Exception as e:
            sys.stderr.write(f"[test] '{name}' FAILED: {e}\n")
            sys.exit(1)
        if event == "all" and name != list(TEST_EVENTS)[-1]:
            sys.stderr.write("[test] 次のイベントまで 3 秒待機...\n")
            time.sleep(3)

    # permission テスト
    if event in ("all", "permission"):
        if event == "all":
            sys.stderr.write("\n[test] --- permission ---\n")
        try:
            decision = communicate_permission(port_name, "TEST: Allow this test?")
            sys.stderr.write(f"[test] Result: {decision}\n")
            sys.stderr.write("[test] 'permission' OK\n")
        except Exception as e:
            sys.stderr.write(f"[test] 'permission' FAILED: {e}\n")
            sys.exit(1)


# ---------------------------------------------------------------------------
# エントリポイント
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # ---- テストモード ----
    if args.test is not None:
        try:
            port_name = args.com_port if args.com_port else find_comport()
        except Exception as e:
            sys.stderr.write(f"[test] {e}\n")
            sys.exit(1)
        run_tests(port_name, args.test)
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
            port_name = args.com_port if args.com_port else find_comport()
            decision  = communicate_permission(port_name, display)
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
            port_name = args.com_port if args.com_port else find_comport()
            communicate_notify(port_name, display)
        except Exception as e:
            sys.stderr.write(f"[client] {e} → M5Stick unavailable, skipping notification\n")


if __name__ == "__main__":
    main()
