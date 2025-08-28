import os
import datetime
import logging
import requests
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from openai import OpenAI

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("toucan-batch-analysis")

load_dotenv()

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
PRODUCTBOARD_API_TOKEN = os.environ["PRODUCTBOARD_API_TOKEN"]
PRODUCTBOARD_API_NOTES_URL = "https://api.productboard.com/notes"
PRODUCTBOARD_API_VERSION = "1"
PRODUCT_TEAM_CHANNEL = os.environ.get("PRODUCT_TEAM_CHANNEL")  # Slack channel ID

slack_client = WebClient(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def fetch_feedback_notes(days=14):
    headers = {
        "Authorization": f"Bearer {PRODUCTBOARD_API_TOKEN}",
        "Content-Type": "application/json",
        "X-Version": PRODUCTBOARD_API_VERSION,
    }

    notes = []
    page_limit = 100
    page_offset = 0
    last_param = f"{days}d"

    while True:
        params = {
            "pageLimit": page_limit,
            "pageOffset": page_offset,
            "last": last_param,  # Filter for only notes created in last 'days' days
        }
        response = requests.get(PRODUCTBOARD_API_NOTES_URL, headers=headers, params=params)
        response.raise_for_status()
        batch = response.json().get("data", [])
        notes.extend(batch)
        logger.info(f"Fetched {len(batch)} notes (offset={page_offset})")
        if len(batch) < page_limit:
            break
        page_offset += page_limit

    logger.info(f"Total notes fetched for last {days} days: {len(notes)}")
    return notes

def prepare_analysis_prompt(notes):
    prompt_intro = (
        f"You are a product manager assistant analyzing {len(notes)} pieces of product feedback from the last two weeks. "
        "Identify key themes, recurring problems, user emotions, and prioritized recommendations for product improvements.\n\n"
        "Feedback summary list:\n"
    )
    # Extract summaries or titles from notes, fallback to title if summary unavailable
    summaries = []
    for note in notes:
        content = note.get("content") or note.get("title") or ""
        summaries.append(f"- {content.strip()}")
    return prompt_intro + "\n".join(summaries)

def analyze_trends_with_gpt(notes):
    prompt = prepare_analysis_prompt(notes)
    logger.info("Sending batch analysis prompt to GPT...")
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
    )
    analysis = response.choices[0].message.content
    logger.info("Received trend analysis from GPT.")
    return analysis

def split_text_for_blocks(text, max_len=2900):
    """Helper to split message into multiple Slack blocks to avoid length limits."""
    blocks = []
    while text:
        chunk = text[:max_len]
        last_newline = chunk.rfind('\n')
        if last_newline > 0:
            chunk = chunk[:last_newline]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": chunk
            }
        })
        text = text[len(chunk):].lstrip('\n')
    return blocks

def post_analysis_to_slack(client, channel_id, analysis_text):
    blocks = split_text_for_blocks(analysis_text)

    try:
        client.chat_postMessage(
            channel=channel_id,
            blocks=blocks
        )
        logger.info(f"Posted formatted trend analysis to Slack channel {channel_id}")
    except SlackApiError as e:
        logger.error(f"Failed to post to Slack: {e.response['error']}")

def main():
    notes = fetch_feedback_notes(days=14)
    if not notes:
        logger.warning("No feedback notes found for analysis. Exiting.")
        return
    analysis = analyze_trends_with_gpt(notes)
    post_analysis_to_slack(slack_client, PRODUCT_TEAM_CHANNEL, analysis)

if __name__ == "__main__":
    main()
