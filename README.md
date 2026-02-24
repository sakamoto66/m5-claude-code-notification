# M5StickC Claude Code Notification

Claude Code のフックシステムと M5StickC を Bluetooth SPP で連携させるプラグインです。
以下のすべてのイベントに対応しています：

- **PermissionRequest** — ツール実行許可を M5StickC のボタンで承認/拒否
- **Start** — Claude 実行開始を M5StickC に通知
- **Stop** — Claude 実行停止を M5StickC に通知
- **AskUserQuestion** — ユーザー質問を M5StickC に表示
- **ExitPlanMode** — 計画モード終了の承認を M5StickC に表示

```
Claude Code フックイベント発火
        ↓
client.py（Python フッククライアント）
        ↓ Bluetooth SPP
M5StickC の画面にメッセージ表示
        ↓
[PermissionRequest] [A] ボタン → ALLOW  /  [B] ボタン → DENY
[Notify系] → 3秒間表示後に前の画面に戻る
        ↓
Claude Code に結果を返す
```

## ディレクトリ構成

```
claude-plugins/
├── plugin.json              # Claude プラグイン設定（新規）
├── README.md
├── plan.md
├── hook/                    # Claude Code フッククライアント (Python)
│   ├── client.py            # フックエントリポイント
│   ├── requirements.txt      # Python 依存パッケージ（新規）
│   ├── package.json         # Node.js 版（レガシー）
│   ├── tsconfig.json
│   └── src/
│       └── hook-client.ts   # Node.js 版（レガシー）
└── m5stick/                 # M5StickC ファームウェア (Arduino / PlatformIO)
    ├── src/
    │   └── main.cpp         # Bluetooth SPP サーバー + ボタン処理
    └── platformio.ini
```

## 必要なもの

- **M5StickC** (ESP32 ベース、ペアリング済み)
- **Windows PC** (Bluetooth Classic 対応、Python 3.8+)
- [PlatformIO](https://platformio.org/) (M5StickC ファームウェア書き込み用)
- Claude Code

## クイックスタート

詳細は [PLUGIN_INSTALL_GUIDE.md](PLUGIN_INSTALL_GUIDE.md) を参照してください。

```bash
# 1. リポジトリをクローン
git clone https://github.com/yourusername/m5stick-claude-code-notification.git
cd m5stick-claude-code-notification

# 2. M5StickC にファームウェアを書き込む
cd m5stick
pio run --target upload
cd ..

# 3. M5StickC を Windows にペアリング（手動: 設定アプリ）

# 4. Python 依存パッケージをインストール
pip install -r hook/requirements.txt

# 5. Claude にプラグインを登録
# ~/.claude/settings.json を編集:
# {
#   "plugins": [
#     {
#       "name": "m5-claude-notify",
#       "path": "C:\\projects\\m5stick-claude-code-notification"
#     }
#   ]
# }

# 6. テスト
python hook/client.py --test all
```

## セットアップ（詳細版）

### 1. M5StickC にファームウェアを書き込む

```bash
cd m5stick
pip install platformio
pio run --target upload
```

書き込み後、M5StickC の画面に **"Waiting..."** と表示されれば起動成功です。

### 2. M5StickC を Windows にペアリング

1. Windows 設定 → **Bluetooth とその他のデバイス**
2. **Bluetooth デバイスを追加** → **M5-Claude-Notify** を検索・選択
3. ペアリング完了後、ポート情報を確認
   ```
   デバイス マネージャー → ポート (COM と LPT) → M5-Claude-Notify のシリアルポート（例: COM5）
   ```

### 3. Python 依存パッケージをインストール

```bash
pip install -r hook/requirements.txt
```

### 4. Claude プラグインとして登録

Claude Code 設定ファイル（`~/.claude/settings.json` またはプロジェクト `.claude/settings.json`）に以下を追加：

#### 方法 A: プラグイン名で登録（推奨）

```json
{
  "plugins": [
    {
      "name": "m5-claude-notify",
      "path": "C:\\projects\\m5stick-claude-code-notification"
    }
  ]
}
```

Claude が `plugin.json` を自動的に読み込みます。

#### 方法 B: 手動で Hook を登録

```json
{
  "hooks": {
    "PermissionRequest": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": [
              "C:\\projects\\m5stick-claude-code-notification\\hook\\client.py",
              "--hook-type",
              "permission"
            ],
            "timeout": 90
          }
        ]
      }
    ],
    "Start": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": [
              "C:\\projects\\m5stick-claude-code-notification\\hook\\client.py",
              "--hook-type",
              "notify"
            ],
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": [
              "C:\\projects\\m5stick-claude-code-notification\\hook\\client.py",
              "--hook-type",
              "notify"
            ],
            "timeout": 10
          }
        ]
      }
    ],
    "AskUserQuestion": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": [
              "C:\\projects\\m5stick-claude-code-notification\\hook\\client.py",
              "--hook-type",
              "notify"
            ],
            "timeout": 10
          }
        ]
      }
    ],
    "ExitPlanMode": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": [
              "C:\\projects\\m5stick-claude-code-notification\\hook\\client.py",
              "--hook-type",
              "notify"
            ],
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

### 5. テスト実行

フックが正常に動作するか確認：

```bash
# すべてのイベントをテスト
python hook/client.py --test all

# 特定イベントのみテスト
python hook/client.py --test permission
python hook/client.py --test start
python hook/client.py --test stop
python hook/client.py --test question
python hook/client.py --test plan

# COM ポートを手動指定
python hook/client.py --com-port COM5 --test permission
```

## 動作説明

### PermissionRequest フック（許可リクエスト）

| フェーズ | 動作 |
|---|---|
| Claude がツール実行を要求 | フックが起動し、COM ポート自動検出 |
| M5StickC 発見（5 秒以内） | コマンド内容を Bluetooth SPP で送信、M5StickC の画面に表示 |
| M5StickC 未発見（5 秒タイムアウト） | 自動的に **allow** でフォールバック（ツール実行許可） |
| ボタン A（側面ボタン）を押す | **ALLOW** — ツール実行を許可 |
| ボタン B（天面ボタン）を押す | **DENY** — ツール実行を拒否 |
| 60 秒間ボタン未操作 | 自動的に **allow** でフォールバック |

### Notify フック（通知系）

Start、Stop、AskUserQuestion、ExitPlanMode イベントは以下のように動作します：

| イベント | 表示内容 | 動作 |
|---|---|---|
| **Start** | `Start` | Claude 実行開始を通知（3 秒表示） |
| **Stop** | `Done` | Claude 実行停止を通知（3 秒表示） |
| **AskUserQuestion** | `Q:質問内容` | ユーザー質問を表示（3 秒表示） |
| **ExitPlanMode** | `Q:Plan ready - approval needed` | 計画モード終了の承認リクエスト（3 秒表示） |

M5StickC が見つからない場合は、エラーをログ出力して処理を続行します。

## Bluetooth スペック

### デバイス情報

| 項目 | 値 |
|---|---|
| デバイス名 | `M5-Claude-Notify` |
| 通信方式 | Bluetooth Classic SPP (Serial Port Profile) |
| ボーレート | 9600 bps |
| データフォーマット | UTF-8 テキスト（改行区切り） |

### コマンドプロトコル

**PC → M5StickC:**
- 通常: `コマンド\n` （例: `Allow this test?\n`）
- 通知: `NOTIFY:メッセージ\n` （例: `NOTIFY:Start\n`）

**M5StickC → PC:**
- ボタン A: `ALLOW\n`
- ボタン B: `DENY\n`
- ハンドシェイク: `hello\n` （接続時、ターミナルモードの判定用）

## トラブルシューティング

### COM ポートが見つからない

```
'M5-Claude-Notify' の COM ポートが見つかりません。
  → Windows の設定でペアリングされているか確認してください。
  → または --com-port COMx で手動指定してください。
```

**対策:**
1. M5StickC が "Waiting..." を表示しているか確認
2. Windows デバイス マネージャーで **ポート (COM と LPT)** を確認
3. `python hook/client.py --com-port COM5 --test permission` で手動指定

### ペアリングが解除される

Bluetooth が頻繁に切断される場合：
1. M5StickC を USB 電源に接続して安定供給
2. Windows の電源設定で**Bluetooth ラジオをオフにする**を無効化
3. M5StickC の側面ボタンで電源を再起動

### テストが突然失敗する

```
Button read failed (empty response)
```

**対策:**
- M5StickC の画面にボタンガイド（**[A] ALLOW / [B] DENY**）が表示されているか確認
- ボタン A/B のいずれかを押して応答
- 60 秒以内に操作してください

### Python スクリプトが実行されない

Claude の hook 実行時に `python: command not found` などエラーが出る場合：

```bash
# Python のフルパスで指定
where python
# → C:\Program Files\Python311\python.exe

# settings.json で絶対パス指定
"command": "C:\\Program Files\\Python311\\python.exe",
"args": ["C:\\projects\\m5stick-claude-code-notification\\hook\\client.py", ...]
```

### プラグインが認識されない

Claude Code がプラグインを読み込まない場合：

```bash
# settings.json の構文を検証
python -m json.tool ~/.claude/settings.json

# プラグイン登録を手動確認
cat ~/.claude/settings.json | grep m5-claude-notify
```
