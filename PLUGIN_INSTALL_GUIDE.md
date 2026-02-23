# Claude プラグイン インストールガイド

このドキュメントでは、M5StickC Claude Notification プラグインを Claude Code に登録する方法を説明します。

## プラグイン概要

| 項目 | 値 |
|---|---|
| プラグイン名 | `m5-claude-notify` |
| 対応フック | PermissionRequest, Start, Stop, AskUserQuestion, ExitPlanMode |
| 通信方式 | Bluetooth Classic SPP |
| 実装言語 | Python 3.8+ |

## インストール手順

### ステップ 1: リポジトリをクローン

```bash
git clone https://github.com/sakamoto66/m5-claude-code-notification.git
cd m5-claude-code-notification
```

### ステップ 2: M5StickC にファームウェアを書き込む

```bash
cd m5stick
pip install platformio
pio run --target upload
```

### ステップ 3: M5StickC を Windows にペアリング

1. M5StickC の电源をオン（USB 接続または電池）
2. Windows 設定 → **Bluetooth とその他のデバイス** → **Bluetooth デバイスを追加**
3. `M5-Claude-Notify` を検索して選択
4. ペアリング完了後、**デバイス マネージャー** で COM ポート番号を確認

### ステップ 4: Python 依存パッケージをインストール

```bash
pip install -r hook/requirements.txt
```

### ステップ 5: Claude にプラグインを登録

#### 方法 A: プラグイン設定ファイルで登録（推奨・自動化）

`~/.claude/settings.json` または `~/.claude/settings.local.json` に以下を追加：

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

Claude が起動時に `plugin.json` を自動読み込みし、すべてのフックを登録します。

#### 方法 B: 手動で Hook を登録（カスタマイズ時）

`~/.claude/settings.json` に以下を追加（各フックを個別に設定）：

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

### ステップ 6: 動作確認

テストを実行して、すべてのフックが正常に動作するか確認：

```bash
# 全フック対応イベントをテスト
python hook/client.py --test all

# 個別フック（PermissionRequest）のテスト
python hook/client.py --test permission

# COM ポートを手動指定してテスト
python hook/client.py --com-port COM5 --test all
```

## 設定ファイルの場所

| OS | 場所 |
|---|---|
| **Windows** | `%APPDATA%\.claude\settings.json` または `%LOCALAPPDATA%\.claude\settings.json` |
| **macOS** | `~/.claude/settings.json` |
| **Linux** | `~/.claude/settings.json` |

## プロジェクトローカルな設定

`.claude/settings.json` をプロジェクトルートに配置すると、そのプロジェクトでのみプラグインが有効になります：

```
m5stick-claude-code-notification/
├── .claude/
│   └── settings.json       ← プロジェクトローカル設定
├── plugin.json
├── hook/
└── m5stick/
```

## アップグレード

新しいバージョンにアップグレードする場合：

```bash
cd m5stick-claude-code-notification
git pull origin main
pip install -r hook/requirements.txt --upgrade
```

Claude は自動的に `plugin.json` から最新の設定を読み込みます。

## アンインストール

Claude からプラグインを削除する場合：

1. `~/.claude/settings.json` から `plugins` エントリを削除
2. または `hooks` セクションから該当するエントリを削除
3. Claude Code を再起動

## トラブルシューティング

### プラグインが認識されない

```bash
# JSON syntax を確認
python -m json.tool ~/.claude/settings.json

# パスが正しいか確認
ls c:\projects\m5stick-claude-code-notification\plugin.json
```

### COM ポート自動検出に失敗

```bash
# COM ポート一覧を表示
python -m serial.tools.list_ports

# 手動指定してテスト
python hook/client.py --com-port COM5 --test permission
```

### 権限エラーが出る

```
Permission denied: COM5
```

→ COM ポートを別のアプリケーション（ターミナルアプリなど）で使用していないか確認してください。

## サポート

問題が発生した場合は、以下をご確認ください：

1. [README.md](README.md) の「トラブルシューティング」セクション
2. [plan.md](plan.md) の技術仕様
3. GitHub Issues で報告

---

**楽しい Claude + M5StickC ライフを！** 🎉
