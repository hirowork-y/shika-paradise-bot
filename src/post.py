"""
Googleスプレッドシートの「投稿する」行をXに投稿するスクリプト。
GitHub Actions の post.yml から毎日12時に実行される。
"""

import os
import json
import tweepy
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timezone, timedelta

# スプレッドシートのシート名
SHEET_NAME = "収集"

# カラム定義（スプレッドシートの列順と対応）
COL_DATE = 1      # 日付
COL_MEDIA = 2     # 媒体名
COL_TITLE = 3     # タイトル
COL_URL = 4       # URL
COL_TEXT = 5      # 投稿文
COL_STATUS = 6    # ステータス

# ステータスの定義
STATUS_TO_POST = "投稿する"
STATUS_POSTED = "投稿済み"

# 日本時間のタイムゾーン
JST = timezone(timedelta(hours=9))


def get_sheet() -> gspread.Worksheet:
    """Googleスプレッドシートの「収集」シートを取得する。"""
    credentials_json = os.environ["GOOGLE_CREDENTIALS_JSON"]
    credentials_dict = json.loads(credentials_json)

    scopes = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
    client = gspread.authorize(creds)

    spreadsheet_id = os.environ["SPREADSHEET_ID"]
    spreadsheet = client.open_by_key(spreadsheet_id)

    return spreadsheet.worksheet(SHEET_NAME)


def get_twitter_client() -> tweepy.Client:
    """Tweepy クライアントを初期化して返す（X API v2）。"""
    return tweepy.Client(
        consumer_key=os.environ["TWITTER_API_KEY"],
        consumer_secret=os.environ["TWITTER_API_SECRET"],
        access_token=os.environ["TWITTER_ACCESS_TOKEN"],
        access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
    )


def post_tweet(client: tweepy.Client, text: str) -> bool:
    """
    ツイートを投稿する。
    成功すれば True、失敗すれば False を返す。
    """
    try:
        client.create_tweet(text=text)
        return True
    except tweepy.TweepyException as e:
        print(f"投稿エラー: {e}")
        return False


def update_status(sheet: gspread.Worksheet, row_index: int, status: str):
    """指定行のステータスを更新する（1始まり、ヘッダー含む）。"""
    try:
        sheet.update_cell(row_index, COL_STATUS, status)
    except Exception as e:
        print(f"ステータス更新エラー [行{row_index}]: {e}")


def main():
    print(f"投稿処理を開始: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    sheet = get_sheet()
    twitter = get_twitter_client()

    # 全行を取得（ヘッダー行 + データ行）
    all_rows = sheet.get_all_values()
    if len(all_rows) <= 1:
        print("データがありません。処理を終了します。")
        return

    posted_count = 0
    # 2行目からデータ行（インデックスは1始まりなので row_index = i + 1 + 1 = i + 2）
    for i, row in enumerate(all_rows[1:], start=2):
        # 列数が不足している行はスキップ
        if len(row) < COL_STATUS:
            continue

        status = row[COL_STATUS - 1].strip()
        if status != STATUS_TO_POST:
            continue

        title = row[COL_TITLE - 1].strip()
        url = row[COL_URL - 1].strip()
        post_text = row[COL_TEXT - 1].strip()

        # 投稿文が空の場合はスキップ（人間が文章を用意するまで待つ）
        if not post_text:
            print(f"スキップ（投稿文なし）: {title}")
            continue

        print(f"投稿中: {title}")
        success = post_tweet(twitter, post_text)

        if success:
            update_status(sheet, i, STATUS_POSTED)
            posted_count += 1
            print(f"  投稿完了 → ステータスを「{STATUS_POSTED}」に更新しました。")
        else:
            print(f"  投稿失敗。ステータスはそのままです。")

    print(f"\n投稿処理完了: 合計 {posted_count} 件を投稿しました。")


if __name__ == "__main__":
    main()
