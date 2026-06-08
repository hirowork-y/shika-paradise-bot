# 鹿パラダイス ニュース収集・投稿ボット

SNSメディア「鹿パラダイス」（X: @shika_paradise）向けの自動ニュース収集・投稿支援システム。

## 機能

- **毎朝8時**: NHK・北海道新聞のRSSフィードから鹿・ジビエ関連ニュースを自動収集し、Googleスプレッドシートに記録
- **毎日12時**: スプレッドシートで「投稿する」に設定した記事をXに自動投稿

## 人間の作業フロー

1. 朝8時以降にスプレッドシートを開く
2. 収集された記事を確認し、ステータスを変更する
   - 不要な記事 → `スキップ`
   - 投稿したい記事 → Claude.aiで投稿文を生成し「投稿文」列に貼り付け → `投稿する`
3. 12時に自動投稿される

## スプレッドシートの列構成

| 列 | 内容 |
|---|---|
| A | 日付 |
| B | 媒体名 |
| C | タイトル |
| D | URL |
| E | 投稿文 |
| F | ステータス（未確認 / スキップ / 投稿する / 投稿済み） |

## 必要なGitHub Secrets

| Secret名 | 内容 |
|---|---|
| `TWITTER_API_KEY` | X Developer Portal のAPIキー |
| `TWITTER_API_SECRET` | X Developer Portal のAPIシークレット |
| `TWITTER_ACCESS_TOKEN` | アクセストークン |
| `TWITTER_ACCESS_TOKEN_SECRET` | アクセストークンシークレット |
| `GOOGLE_CREDENTIALS_JSON` | GCPサービスアカウントのJSONキー（全文） |
| `SPREADSHEET_ID` | GoogleスプレッドシートのID |
