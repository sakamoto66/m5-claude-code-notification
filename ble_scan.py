"""
BLEデバイススキャナー（キャッシュなし）
M5StickC が見つかるか確認するための診断ツール

使い方:
    pip install bleak
    python ble_scan.py
"""

import asyncio
from bleak import BleakScanner

TARGET_NAME = "M5-Claude-Notify"
SCAN_DURATION = 10  # 秒


async def main():
    print(f"BLEスキャン開始（{SCAN_DURATION}秒）...")
    print("-" * 60)

    found = {}

    def callback(device, advertisement_data):
        addr = device.address
        if addr not in found:
            found[addr] = device
            name = device.name or advertisement_data.local_name or "(名前なし)"
            rssi = advertisement_data.rssi
            marker = " ★ TARGET" if name == TARGET_NAME else ""
            print(f"[{addr}] {name:30s} RSSI={rssi:4d} dBm{marker}")
            if advertisement_data.service_uuids:
                for uuid in advertisement_data.service_uuids:
                    print(f"         UUID: {uuid}")

    # use_bdaddr=False でキャッシュを使わず毎回新規スキャン
    async with BleakScanner(detection_callback=callback) as scanner:
        await asyncio.sleep(SCAN_DURATION)

    print("-" * 60)
    print(f"スキャン完了: {len(found)} デバイス発見")

    if any(d.name == TARGET_NAME for d in found.values()):
        print(f"✓ {TARGET_NAME} が見つかりました")
    else:
        print(f"✗ {TARGET_NAME} は見つかりませんでした")


if __name__ == "__main__":
    asyncio.run(main())
