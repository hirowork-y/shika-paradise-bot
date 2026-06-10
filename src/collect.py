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
import anthropic

# 収集対象のRSSフィード（媒体名: URL）
RSS_FEEDS = {
    "NHK社会": "https://www3.nhk.or.jp/rss/news/cat6.xml",
    "北海道新聞": "https://www.hokkaido-np.co.jp/output/7/free/index.ad.xml",
    "農林水産省": "https://www.maff.go.jp/j/press/rss.xml",
    "日本農業新聞": "https://www.agrinews.co.jp/feed",
    "朝日新聞": "https://www.asahi.com/rss/asahi/newsheadlines.rdf",
    "毎日新聞": "https://mainichi.jp/rss/etc/mainichi-flash.rss",
}

# フィルタリングキーワード（いずれか1つでも含まれれば対象）
KEYWORDS = ["エゾシカ", "鹿", "ジビエ", "狩猟", "害獣", "駆除", "北海道"]

# 除外キーワード（いずれか1つでも含まれれば除外）
EXCLUDE_KEYWORDS = ["鹿児島", "鹿屋", "鹿沼", "鹿嶋", "鹿島"]

# 「北海道」キーワードを除外する媒体（北海道新聞は全記事が北海道のため）
EXCLUDE_BROAD_KEYWORD_SOURCES = {"北海道新聞"}
BROAD_KEYWORD = "北海道"

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


def matches_keywords(text: str, media_name: str = "") -> bool:
    """キーワードを含み、除外キーワードを含まない場合に True を返す。"""
    effective_keywords = [
        kw for kw in KEYWORDS
        if not (kw == BROAD_KEYWORD and media_name in EXCLUDE_BROAD_KEYWORD_SOURCES)
    ]
    if not any(keyword in text for keyword in effective_keywords):
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
            if not matches_keywords(title + summary, media_name):
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
            post_text = generate_tweet(article["media"], article["date"], article["title"])
            row = [
                article["date"],
                article["media"],
                article["title"],
                article["url"],
                post_text,
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
