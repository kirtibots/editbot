# Heroku One-Click Deploy

This ZIP is Heroku-ready.

## One-click button
After uploading these files to your GitHub repository, use this button in your
repository README (replace `YOUR_GITHUB_USER/YOUR_REPO`):

```md
[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/YOUR_GITHUB_USER/YOUR_REPO)
```

## Required config vars
- `API_ID`
- `API_HASH`
- `BOT_TOKEN`
- `OWNER_ID`

`START_IMAGE` is optional. If it is empty, the bundled `start.jpg` is used.

## Important
Give the bot **Delete Messages** permission in the Telegram group.
