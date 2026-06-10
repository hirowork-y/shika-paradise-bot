"""
Googleスプレッドシートの「投稿する」行をXに投稿するスクリプト。
GitHub Actions の post.yml から毎日12時に実行される。
"""

import os
import json
import tweepy
import gspread
import anthropic
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

SYSTEM_PROMPT = """あなたはSNSメディア「鹿パラダイス」（X: @shika_paradise）の投稿担当です。
道東の鹿・狩猟・ジビエに関するニュースを受け取り、X（旧Twitter）への投稿文を生成してください。

## メディアのミッション
道東の現場にいる人間の言葉と、鹿という存在のリアルを伝える。
観光メディアでも環境保護メディアでもなく、「現場を記録するルポメディア」として発信する。

## トーン
- 現場に敬意を持つルポライターの視点
- 短文を重ねる。一文が長くなりすぎない
- 主語を省く。余白を作る
- 数字・固有名詞・現場の言葉を使う（「鹿」「道東」「血抜き」「忍び猟」など）
- 感嘆符・絵文字は使わない
- 「美しい」「感動した」などの主観的形容は使わない。事実が感情を連れてくる
- 主張を前に出しすぎない。事実を積み重ねて、読む人に委ねる

## 禁止ワード
素敵／癒し／感動／絶景／必見／感謝／エモい

## 投稿ルール
- 140字前後（厳守）
- URLは含めない
- 冒頭1〜2行で引きを作る（問い・意外な事実・現場の言葉）
- 改行を効果的に使い、視覚的な余白を作る
- 記事を要約するのではなく、道東・鹿・狩猟の現場視点を加える
- 末尾に「#エゾシカ #道東 #ジビエ」を付ける

## 投稿例

### 例1
今年度、北海道で駆除されたエゾシカは約8万頭。

食肉として流通したのは2割以下だという。
撃った後の処理が、追いつかない。

#エゾシカ #道東 #ジビエ

### 例2
道内のジビエ処理施設が昨年比1.3倍になった。

現場の人間に聞くと、施設より先に壁がある、と言う。
腹を撃たず、血を抜き、冷やして運べるハンターが足りない。

#エゾシカ #道東 #ジビエ

### 例3
十勝で今年、鹿による農業被害が相次いだ。

駆除数は増えている。被害額も増えている。
現場では、柵を張ることと撃つことを同時にやっている。

#エゾシカ #道東 #ジビエ

## 入力フォーマット
媒体名：〇〇
配信日：〇〇
タイトル：〇〇

## 出力フォーマット
投稿文のみを出力する。説明・前置き・かぎかっこは不要。"""


def generate_tweet(media: str, date: str, title: str) -> str:
    """Anthropic APIを使って投稿文を生成する。失敗時は空文字を返す。"""
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"媒体名：{media}\n配信日：{date}\nタイトル：{title}",
                }
            ],
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"投稿文生成エラー [{title}]: {e}")
        return ""


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

        date = row[COL_DATE - 1].strip()
        media = row[COL_MEDIA - 1].strip()
        title = row[COL_TITLE - 1].strip()
        post_text = row[COL_TEXT - 1].strip()

        if not post_text:
            print(f"投稿文を生成中: {title}")
            post_text = generate_tweet(media, date, title)
            if not post_text:
                print(f"スキップ（投稿文生成失敗）: {title}")
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
