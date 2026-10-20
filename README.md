# Router Syslog Monitor

Buffalo ルーター（AirStation等）から syslog を受信し、リアルタイムでモニタリングする監視画面です。  
受信したログは SQLite に永続保存され、後から日付・キーワードで検索できます。

![monitor](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi) ![python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python) ![sqlite](https://img.shields.io/badge/SQLite-built--in-003B57?logo=sqlite)

## 機能

| 機能 | 説明 |
|------|------|
| **リアルタイム受信** | UDP syslog (port 514) をリアルタイム表示 |
| **受信ステータス** | 緑/黄/グレーのインジケーターと最終受信時刻・受信レート |
| **ライブフィルター** | Severity・送信元IP・正規表現キーワードで絞り込み |
| **SQLite 永続保存** | 受信ログを自動保存、サーバー再起動後も参照可能 |
| **履歴検索** | 日付カレンダー・キーワード・Severity で過去ログを検索 |
| **CSV エクスポート** | ライブ・履歴どちらもCSVで保存可能 |

## 必要環境

- Python 3.9+
- macOS（Linux でも動作可）

```bash
pip3 install fastapi uvicorn
```

## 起動方法

ルーターはポート 514 (UDP) に syslog を送信します。514 番ポートのバインドには root 権限が必要です。

```bash
sudo python3 server.py
```

ブラウザで開く：

```
http://localhost:8080
```

> **root なしで起動する場合**  
> ポート 5140 で起動します。ルーター側の syslog 送信先ポートを 5140 に変更するか、以下でポート転送してください。
>
> ```bash
> echo "rdr pass on en0 proto udp from any to any port 514 -> 127.0.0.1 port 5140" | sudo pfctl -ef -
> ```

## ルーター設定（Buffalo AirStation の場合）

1. ルーター管理画面 → **管理設定 → ログ情報転送 (syslog)**
2. 「ログ情報転送機能」を **使用する** にチェック
3. **syslogサーバー** に Mac の IP アドレスを入力（例: `192.168.50.11`）
4. 「設定」ボタンで保存

## ファイル構成

```
syslog-dashboard/
├── server.py          # syslog UDP受信 + FastAPI Web サーバー
├── templates/
│   └── index.html     # 監視画面 UI（vanilla JS + SSE）
├── start.sh           # 起動スクリプト
├── setup-port-forward.sh  # pfctl ポート転送設定
├── syslog.db          # 受信ログ DB（自動生成・git管理外）
└── .gitignore
```

## 監視画面画面

### ライブタブ
- 受信したログをリアルタイムストリーミング表示
- Severity（emerg / alert / crit / err / warning / notice / info / debug）でサイドバーフィルター
- 送信元 IP・種別（WIRELESS / DHCP 等）でワンクリック絞り込み

### 履歴タブ
- ログが存在する日付をカレンダーストリップで一覧表示
- 日付範囲・キーワード・Severity を指定して検索
- 最大 5,000 件表示、CSV ダウンロード対応
