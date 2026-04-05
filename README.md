# Steam Release Calendar

Generate an `.ics` calendar file with upcoming release dates from a public Steam wishlist.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- A public Steam wishlist
- Your numeric Steam profile ID in `STEAM_USER_ID`

## Setup

1. Copy `.env.example` to `.env`
2. Fill in `STEAM_USER_ID`
3. Run the generator:

```bash
uv run steamreleasecalendar
```

The calendar file is written to `dist/steam-upcoming-releases.ics` by default.

## Configuration

- `STEAM_USER_ID`: numeric Steam profile ID used in `/profiles/<id>/`
- `STEAM_COUNTRY_CODE`: optional Steam storefront country code such as `de` or `us`
- `OUTPUT_DIR`: target directory for the generated calendar, defaults to `dist`
- `OUTPUT_FILENAME`: generated file name, defaults to `steam-upcoming-releases.ics`

## Finding Your Steam User ID

Use the numeric Steam profile ID, not your custom vanity name.

The most reliable way is to use [steamid.io](https://steamid.io/):

1. Open your Steam profile page.
2. Copy your profile URL.
3. Paste it into `https://steamid.io/lookup`.
4. Copy the `steamID64` value.

If your profile URL already looks like `https://steamcommunity.com/profiles/7656119...`, you can also copy the long number after `/profiles/` directly.

The value should look like `76561198000000000` and goes into `STEAM_USER_ID`.

## Notes

- The wishlist must be public so Steam can return the data.
- Only titles with a concrete release date on or after today are included.
- The generator prefers Steam's explicit release-date update text when the app metadata date is stale.
- The generated file uses all-day events for the release date.

## GitHub Actions

The repo includes a workflow at `.github/workflows/generate-calendar.yml` that runs daily and can also be triggered manually from the Actions tab.

Before it can run, add a repository secret named `STEAM_USER_ID` with your numeric Steam profile ID in GitHub under `Settings > Secrets and variables > Actions`.

The workflow also publishes the generated `dist/` directory to GitHub Pages. After enabling GitHub Pages for the repository, the hosted site will contain:

- `index.html` with a link to the calendar file
- `steam-upcoming-releases.ics` for direct calendar downloads

If the secret is missing, the workflow fails with instructions and a link to `https://steamid.io/lookup`.
