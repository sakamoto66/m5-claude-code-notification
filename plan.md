# Claude Code CLI × M5StickC Permission System
**〜 BLE UART と PermissionRequest Hook で許可ダイアログをリモート承認する仕組み 〜**

このプロジェクトは、**Claude Code CLI の PermissionRequest Hook を捕捉し、M5StickC に BLE で通知し、ボタンで承認/拒否できるようにするシステム**です。

常駐プロセス不要。M5StickC が近くにあればリモート承認、なければ自動的に allow でフォールバック。

---

## 機能概要

- Claude Code CLI の **PermissionRequest Hook** を利用
- 許可が必要な操作が発生すると Hook クライアントが起動される
- **M5StickC が見つかれば** BLE UART でコマンドを送信し、ボタン応答を待つ
- **M5StickC が見つからなければ**（5 秒タイムアウト）`allow` で自動フォールバック
- ボタン A (側面) → ALLOW（緑表示）、ボタン B (天面) → DENY（赤表示）

---

## アーキテクチャ

```
Claude Code CLI
   ↓ PermissionRequest Hook（stdin に JSON）
hook/dist/hook-client.js（BLE 直接制御・使い捨てプロセス）
   ↓ BLE UART（Nordic UART Service）※ 5秒以内に接続できなければ allow
M5StickC（m5stick/src/main.cpp）
   ↓ ボタン A → "ALLOW" / ボタン B → "DENY"
hook クライアント
   ↓ stdout: {"hookSpecificOutput": {"permissionDecision": "allow"}}
Claude Code CLI（許可 or 拒否）
```

常駐プロセス（デーモン）は不要。Hook クライアントが直接 BLE をスキャン・接続・通信・切断する。

---

## フォルダ構成

```
claude-plugins/
├── plan.md
├── m5stick/                    ← PlatformIO プロジェクト（M5StickC ファームウェア）
│   ├── platformio.ini
│   └── src/
│       └── main.cpp
└── hook/                       ← Claude Code Hook クライアント（Node.js + TypeScript）
    ├── package.json
    ├── tsconfig.json
    └── src/
        ├── hook-client.ts
        └── noble.d.ts          ← @abandonware/noble 型宣言
```

---

## Component 1: M5StickC ファームウェア

### platformio.ini

```ini
[env:m5stick-c]
platform = espressif32
board = m5stick-c
framework = arduino
lib_deps =
    m5stack/M5StickC@^0.2.8
monitor_speed = 115200
upload_speed = 1500000
```

### src/main.cpp の実装概要

- **画面:** ST7735S 80×160px、横向き（Rotation 3）
- **BLE ペリフェラル:** デバイス名 `M5-Claude-Notify`
- **Nordic UART Service (NUS):**
  - RX Characteristic `6E400002` → PC からのコマンド受信（Write）
  - TX Characteristic `6E400003` → ボタン応答を PC に送信（Notify）
- **コマンド表示:** 1 行 26 文字で折り返し、画面下部にボタンガイド表示
- **ボタン A (M5.BtnA / 側面):** `ALLOW` 送信 + 緑画面表示
- **ボタン B (M5.BtnB / 天面):** `DENY` 送信 + 赤画面表示
- **切断時:** 自動的に再アドバタイズ開始

---

## Component 2: Hook クライアント

### hook/package.json

```json
{
  "name": "m5-hook-client",
  "type": "commonjs",
  "scripts": {
    "build": "tsc",
    "start": "node dist/hook-client.js"
  },
  "dependencies": {
    "@abandonware/noble": "1.9.2-26"
  },
  "devDependencies": {
    "@types/node": "^20.0.0",
    "typescript": "^5.3.0"
  }
}
```

### hook/src/hook-client.ts の実装概要

1. stdin から Claude Code の Hook JSON を読み込む
2. BLE スキャン開始（最大 5 秒）
3. **M5Stick が見つからない場合:** `allow` でフォールバック（Claude Code は通常動作）
4. **M5Stick が見つかった場合:** 接続 → NUS コマンド送信 → ボタン待機（最大 60 秒）
5. `ALLOW` / `DENY` 受信後に切断
6. 結果を stdout に JSON 出力して終了

```
{"hookSpecificOutput": {"permissionDecision": "allow"}}
```

---

## BLE UUIDs（Nordic UART Service）

| 用途 | UUID |
|------|------|
| NUS Service | `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` |
| RX (PC → M5Stick, Write) | `6E400002-B5A3-F393-E0A9-E50E24DCCA9E` |
| TX (M5Stick → PC, Notify) | `6E400003-B5A3-F393-E0A9-E50E24DCCA9E` |

---

## Claude Code Hook 設定

`~/.claude/settings.json` に以下を追加:

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node C:/projects/m5stick-claude-code-notification/hook/dist/hook-client.js",
            "timeout": 90
          }
        ]
      }
    ]
  }
}
```

---

## セットアップ手順

### 1. Windows BLE ドライバ設定

**方法 A: @abandonware/noble（デフォルト）**

1. [Zadig](https://zadig.akeo.ie/) をダウンロード
2. Options → List all Devices で Bluetooth アダプタを選択
3. WinUSB ドライバを適用
   > ⚠️ 適用後は Windows Bluetooth 設定からアダプタが使用不可になる
4. 管理者 PowerShell で `npm install -g windows-build-tools`

**方法 B: noble-uwp（ドライバ変更不要）**

`hook/package.json` の `@abandonware/noble` を `noble-uwp` に変更し、
`hook/src/hook-client.ts` の import も `noble-uwp` に変更する。

### 2. M5StickC ファームウェア書き込み

```bash
cd m5stick
pio run --target upload
```

書き込み完了後、M5StickC の画面に **"Waiting..."** が表示される。

### 3. Hook クライアントのビルド

```bash
cd hook
npm install
npm run build
```

### 4. Claude Code Hook 設定

上記の JSON を `~/.claude/settings.json` に追加する。

---

## 動作確認

1. M5StickC に電源を入れる → 画面に **"Waiting..."**（黄）表示
2. Claude Code で権限が必要な操作を実行（例: Bash コマンド）
3. Hook クライアントが BLE スキャン開始（最大 5 秒）
4. M5StickC が見つかれば接続し、画面にコマンド内容と `[A]ALLOW / [B]DENY` ガイドが表示される
5. **ボタン A** → 緑画面 **ALLOW** → Claude Code が操作を続行
6. **ボタン B** → 赤画面 **DENY** → Claude Code が操作を拒否
7. **M5StickC が見つからない場合** → 5 秒後に自動 allow（Claude Code は通常動作）

---

## 今後の拡張案

- BLE MTU ネゴシエーションで 20 バイト制限を緩和（最大 512 バイト）
- M5StickC Plus / Plus2 対応（画面 135×240px で表示量を増加）
- 許可内容に応じた自動承認ルール
- Wi-Fi（WebSocket）版（BLE 不要、常駐プロセスは必要）

---

## v1.0.0 �X�V: Claude �v���O�C�����Ή�

**������:** 2026-02-23

### �������e

1. **���� Hook �^�C�v�ւ̑Ή�** 
   - PermissionRequest�i�����N�G�X�g�j
   - Start�i���s�J�n�ʒm�j
   - Stop�i���s��~�ʒm�j
   - AskUserQuestion�i���[�U�[����\���j
   - ExitPlanMode�i�v�惂�[�h�I�����F�j

2. **Python �Łiclient.py�j�̊��S�Ή�**
   - Node.js �Łihook-client.ts�j�ł� BLE �݂̂��������APython �łł� Bluetooth Classic SPP �ɑΉ�
   - Windows �l�C�e�B�u�Ή��F���W�X�g������ Bluetooth �f�o�C�X�����������o
   - COM �|�[�g�������o���蓮�w��I�v�V����

3. **Claude �v���O�C���V�X�e���Ή�**
   - plugin.json ��ǉ��F�v���O�C�����^�f�[�^�� Hook ��`
   - ~/.claude/settings.json �œ���I�ɓo�^�\
   - ���� Hook �� 1 �� Python �v���Z�X�Ō����I�ɏ���

4. **�ݒ�t�@�C���̒ǉ�**
   - requirements.txt�FPython �ˑ��p�b�P�[�W
   - pyproject.toml�FPython �p�b�P�[�W�d�l
   - PLUGIN_INSTALL_GUIDE.md�F�ڍ׃C���X�g�[���菇

### �e�X�g���@

�S�C�x���g�̃e�X�g:
python hook/client.py --test all

�ʃC�x���g:
python hook/client.py --test permission
python hook/client.py --test start
python hook/client.py --test stop
python hook/client.py --test question

COM �|�[�g�蓮�w��:
python hook/client.py --com-port COM5 --test permission
