import logging

from yt_song_to_instrumental.config import LabelConfig

logger = logging.getLogger(__name__)


def sync_channel_metadata(service, label_config: LabelConfig) -> None:
    response = service.channels().list(part="snippet,brandingSettings", mine=True).execute()

    if not response.get("items"):
        logger.error("No channel found for authenticated user")
        return

    channel = response["items"][0]
    channel_id = channel["id"]
    current_description = channel.get("brandingSettings", {}).get("channel", {}).get("description", "")

    desired_description = label_config.channel_description.strip()

    if current_description.strip() == desired_description:
        logger.info("Channel description already up to date")
        return

    body = {
        "id": channel_id,
        "brandingSettings": {
            "channel": {
                "description": desired_description,
            }
        },
    }

    service.channels().update(part="brandingSettings", body=body).execute()
    logger.info("Updated channel description")
