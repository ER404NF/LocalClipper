"""Step hints the crew follows inside the account tabs and on the phone. They are guidance, not rigid
scripts: the agent reads the real page each step and adapts when a site moves its buttons."""

ALLOWED_DOMAINS = {
    "tiktok": ["tiktok.com"],
    "instagram": ["instagram.com", "facebook.com"],
    "youtube": ["youtube.com", "google.com", "accounts.google.com"],
}

TAB = {
    ("tiktok", "post"): """Open https://www.tiktok.com/tiktokstudio/upload .
Upload the video file (use the file input / the drop area). Wait until it finishes uploading.
Replace the description text with the caption. Leave other settings as they are.
If a time is given: turn on scheduling, set the date and time, then press Schedule. Otherwise press Post.
Done when TikTok shows the post was scheduled/posted (or it appears in the posts list).""",
    ("youtube", "post"): """Open https://studio.youtube.com and use Create -> Upload videos (or https://www.youtube.com/upload).
Upload the video file. Title = the title given (max 100 characters). Description = the caption.
Choose 'No, it's not made for kids'. Press Next until the Visibility step.
If a time is given: choose Schedule and set the date and time. Otherwise choose Public. Then Save / Publish.
Done when YouTube confirms it's scheduled or published.""",
    ("instagram", "post"): """Open https://www.instagram.com/ . Click Create (+), then Post/Reel.
Upload the video file. If asked about cropping, pick the original or 9:16 ratio. Click Next until the caption step.
Paste the caption. Click Share. Done when Instagram says the reel was shared.""",
    ("youtube", "stats"): """Open https://studio.youtube.com . Read: subscribers, views in the last 28 days, and on the Earn page
the Partner Program progress (subscribers and Shorts views in 90 days) if shown. Report the numbers exactly as shown.""",
    ("tiktok", "stats"): """Open https://www.tiktok.com/tiktokstudio . Read: followers, video views and likes for the last 7/28 days,
and anything shown about Creator Rewards eligibility. Report the numbers exactly as shown.""",
    ("instagram", "stats"): """Open https://www.instagram.com/accounts/insights/ (or the professional dashboard). Read followers,
accounts reached and plays for the last 30 days. Report the numbers exactly as shown.""",
}

PHONE = {
    "edits_post": """The video is already in the phone's gallery (newest item).
Open the Edits app. Start a new project and pick the newest video.
If a sound is requested, use Audio -> search the sound -> add it under the clip, lower its volume so the clip's audio stays clear.
Export / Next, then Share to Instagram as a Reel. Make sure the right Instagram account is selected.
Paste the caption, then Share. Done when Instagram shows the reel was shared.""",
}


def tab_hint(platform: str, action: str) -> str:
    return TAB.get((platform, action), "")
