"""
RSSフィードからニュース記事を収集し、Googleスプレッドシートに追記するスクリプト。
GitHub Actions の collect.yml から毎朝8時に実行される。
"""

import os
import json
import feedparser
from datetime import datetime, timezone, timedelta
import gspread
from google.oauth2.service_account import Credentials

# 収集対象のRSSフィード（媒体名: URL）
RSS_FEEDS = {
    "NHK社会": "https://www3.nhk.or.jp/rss/news/cat6.xml",
    "北海道新聞": "https://www.hokkaido-np.co.jp/rss/index.rss",
}

# フィルタリングキーワード（いずれか1つでも含まれれば対象）
KEYWORDS = ["エゾシカ", "鹿", "ジビエ", "狩猟", "害獣", "駆除", "北海道"]

# 除外キーワード（いずれか1つでも含まれれば除外）
EXCLUDE_KEYWORDS = ["鹿児島", "鹿屋", "鹿沼", "鹿嶋", "鹿島"]

# スプレッドシートのシート名
SHEET_NAME = "収集"

# カラム定義（スプレッドシートの列順と対応）
COL_DATE = 1      # 日付
COL_MEDIA = 2     # 媒体名
COL_TITLE = 3     # タイトル
COL_URL = 4       # URL
COL_TEXT = 5      # 投稿文
COL_STATUS = 6    # ステータス

# 初期ステータス
STATUS_UNCONFIRMED = "未確認"

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))


def get_sheet() -> gspread.Worksheet:
    """Googleスプレッドシートの「収集」シートを取得する。"""
    # 環境変数からサービスアカウントの認証情報を読み込む
    credentials_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    credentials_dict = json.loads(credentials_json)

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    client = gspread.authorize(creds)

    # スプレッドシートIDは環境変数から取得
    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    spreadsheet = client.open_by_key(spreadsheet_id)

    return spreadsheet.worksheet(SHEET_NAME)


def get_existing_urls(sheet: gspread.Worksheet) -> set:
    """スプレッドシートに登録済みのURLの集合を返す（重複チェック用）。"""
    try:
        urls = sheet.col_values(COL_URL)
        # ヘッダー行を除外
        return set(urls[1:]) if len(urls) > 1 else set()
    except Exception as e:
        print(f"既存URL取得エラー: {e}")
        return set()


def matches_keywords(text: str) -> bool:
    """キーワードを含み、除外キーワードを含まない場合に True を返す。"""
    if not any(keyword in text for keyword in KEYWORDS):
        return False
    if any(keyword in text for keyword in EXCLUDE_KEYWORDS):
        return False
    return True


def parse_feed(media_name: str, url: str) -> list[dict]:
    """
    RSSフィードを取得・解析し、記事情報のリストを返す。
    エラーが発生しても空リストを返してクラッシュを防ぐ。
    """
    articles = []
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            link = entry.get("link", "")

            # タイトルまたは要約にキーワードが含まれるか確認
            if not matches_keywords(title + summary):
                continue

            # 公開日時を取得（なければ現在時刻を使用）
            published = entry.get("published_parsed")
            if published:
                dt = datetime(*published[:6], tzinfo=timezone.utc).astimezone(JST)
                date_str = dt.strftime("%Y-%m-%d")
            else:
                date_str = datetime.now(JST).strftime("%Y-%m-%d")

            articles.append({
                "date": date_str,
                "media": media_name,
                "title": title,
                "url": link,
            })
    except Exception as e:
        print(f"フィード取得エラー [{media_name}]: {e}")

    return articles


def append_articles(sheet: gspread.Worksheet, articles: list[dict], existing_urls: set) -> int:
    """
    新着記事をスプレッドシートに追記する。
    既に登録済みのURLはスキップする。
    追記した件数を返す。
    """
    added_count = 0
    for article in articles:
        if article["url"] in existing_urls:
            print(f"スキップ（重複）: {article['title']}")
            continue
        try:
            row = [
                article["date"],
                article["media"],
                article["title"],
                article["url"],
                "",               # 投稿文（空欄）
                STATUS_UNCONFIRMED,  # ステータス
            ]
            sheet.append_row(row, value_input_option="USER_ENTERED")
            existing_urls.add(article["url"])
            added_count += 1
            print(f"追加: {article['title']}")
        except Exception as e:
            print(f"追記エラー [{article['title']}]: {e}")

    return added_count


def main():
    print(f"収集処理を開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    sheet = get_sheet()
    existing_urls = get_existing_urls(sheet)
    print(f"登録済みURL数: {len(existing_urls)}")

    total_added = 0
    for media_name, feed_url in RSS_FEEDS.items():
        print(f"\n[{media_name}] フィード取得中...")
        articles = parse_feed(media_name, feed_url)
        print(f"  キーワードマッチ: {len(articles)}件")
        added = append_articles(sheet, articles, existing_urls)
        total_added += added
        print(f"  新規追加: {added}件")

    print(f"\n収集処理完了: 合計 {total_added} 件を追加しました。")


if __name__ == "__main__":
    main()
