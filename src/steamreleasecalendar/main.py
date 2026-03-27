from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from json import JSONDecodeError
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


STEAM_WISHLIST_API_URL = "https://api.steampowered.com/IWishlistService/GetWishlist/v1/"
STEAM_APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"
APP_DETAILS_WORKERS = 8


class SteamReleaseCalendarError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    steam_user_id: str
    output_dir: Path
    output_filename: str


@dataclass(frozen=True)
class Release:
    app_id: int
    name: str
    release_date: date
    steam_url: str


def request_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "steamreleasecalendar/0.1",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config() -> Config:
    load_dotenv(Path(".env"))

    steam_user_id = os.getenv("STEAM_USER_ID", "").strip()
    if not steam_user_id:
        raise SteamReleaseCalendarError(
            "Missing STEAM_USER_ID. Set it in your environment or .env file."
        )

    output_dir = Path(os.getenv("OUTPUT_DIR", "dist")).expanduser()
    output_filename = os.getenv(
        "OUTPUT_FILENAME", "steam-upcoming-releases.ics"
    ).strip()
    if not output_filename:
        raise SteamReleaseCalendarError("OUTPUT_FILENAME cannot be empty.")

    return Config(
        steam_user_id=steam_user_id,
        output_dir=output_dir,
        output_filename=output_filename,
    )


def parse_release_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None

    for fmt in ("%b %d, %Y", "%d %b, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue

    return None


def fetch_wishlist_app_ids(steam_user_id: str) -> list[int]:
    query = urlencode({"steamid": steam_user_id})
    url = f"{STEAM_WISHLIST_API_URL}?{query}"

    try:
        payload = request_json(url)
    except HTTPError as exc:
        if exc.code == 403:
            raise SteamReleaseCalendarError(
                "Steam wishlist is not accessible. Make sure the wishlist is public."
            ) from exc
        raise SteamReleaseCalendarError(
            f"Steam wishlist request failed with HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        raise SteamReleaseCalendarError(f"Steam request failed: {exc.reason}") from exc
    except JSONDecodeError as exc:
        raise SteamReleaseCalendarError(
            "Steam returned an unexpected wishlist response. Check that the profile ID is correct and the wishlist is public."
        ) from exc

    items = payload.get("response", {}).get("items", [])
    if not isinstance(items, list):
        raise SteamReleaseCalendarError(
            "Steam wishlist response did not contain items."
        )

    return [int(item["appid"]) for item in items if "appid" in item]


def fetch_app_details(app_id: int) -> dict[str, Any]:
    query = urlencode(
        {
            "appids": str(app_id),
            "filters": "basic,release_date",
            "cc": "us",
            "l": "english",
        }
    )
    url = f"{STEAM_APP_DETAILS_URL}?{query}"
    return request_json(url)


def fetch_all_upcoming_releases(steam_user_id: str) -> list[Release]:
    releases: list[Release] = []
    today = datetime.now(UTC).date()

    app_ids = fetch_wishlist_app_ids(steam_user_id)

    try:
        with ThreadPoolExecutor(max_workers=APP_DETAILS_WORKERS) as executor:
            futures = {
                executor.submit(fetch_app_details, app_id): app_id for app_id in app_ids
            }

            for future in as_completed(futures):
                payload = future.result()

                for raw_app_id, item in payload.items():
                    if not item.get("success"):
                        continue

                    data = item.get("data", {})
                    release_info = data.get("release_date", {})
                    release_day = parse_release_date(str(release_info.get("date", "")))
                    if release_day is None or release_day < today:
                        continue

                    app_id = int(raw_app_id)
                    name = str(data.get("name") or f"Steam App {app_id}")
                    releases.append(
                        Release(
                            app_id=app_id,
                            name=name,
                            release_date=release_day,
                            steam_url=f"https://store.steampowered.com/app/{app_id}/",
                        )
                    )
    except HTTPError as exc:
        raise SteamReleaseCalendarError(
            f"Steam app details request failed with HTTP {exc.code}."
        ) from exc
    except URLError as exc:
        raise SteamReleaseCalendarError(f"Steam request failed: {exc.reason}") from exc
    except JSONDecodeError as exc:
        raise SteamReleaseCalendarError(
            "Steam returned an unexpected app details response."
        ) from exc

    releases.sort(
        key=lambda release: (release.release_date, release.name.lower(), release.app_id)
    )
    return releases


def escape_ical_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold_ical_line(line: str) -> str:
    encoded = line.encode("utf-8")
    chunks: list[bytes] = []

    while len(encoded) > 75:
        split_at = 75
        while split_at > 0 and (encoded[split_at] & 0xC0) == 0x80:
            split_at -= 1
        chunks.append(encoded[:split_at])
        encoded = encoded[split_at:]

    chunks.append(encoded)
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def build_icalendar(releases: list[Release], steam_user_id: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//steamreleasecalendar//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{escape_ical_text(f'Steam Upcoming Releases ({steam_user_id})')}",
        "X-WR-TIMEZONE:UTC",
    ]

    for release in releases:
        uid_hash = sha256(
            f"{steam_user_id}:{release.app_id}:{release.release_date.isoformat()}".encode(
                "utf-8"
            )
        ).hexdigest()[:16]
        summary = escape_ical_text(f"{release.name} release")
        description = escape_ical_text(
            f"{release.name} is scheduled to release on Steam.\\n{release.steam_url}"
        )
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:{uid_hash}@steamreleasecalendar",
                f"DTSTAMP:{timestamp}",
                f"DTSTART;VALUE=DATE:{release.release_date.strftime('%Y%m%d')}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                f"URL:{release.steam_url}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ical_line(line) for line in lines) + "\r\n"


def write_calendar(config: Config, calendar_text: str) -> Path:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    output_path = config.output_dir / config.output_filename
    output_path.write_text(calendar_text, encoding="utf-8", newline="")
    return output_path


def main() -> int:
    try:
        config = load_config()
        releases = fetch_all_upcoming_releases(config.steam_user_id)
        calendar_text = build_icalendar(releases, config.steam_user_id)
        output_path = write_calendar(config, calendar_text)
    except SteamReleaseCalendarError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(releases)} upcoming releases to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
