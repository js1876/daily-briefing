@echo off
cd /d C:\Users\dltmddbs\Documents\Codex\daily-briefing
set GIT=C:\Program Files\Git\cmd\git.exe
python scripts\generate_daily_briefing.py >> logs\daily_briefing_discord_test.log 2>&1
"%GIT%" status --short >> logs\daily_briefing_discord_test.log 2>&1
python scripts\send_discord_notification.py >> logs\daily_briefing_discord_test.log 2>&1
echo Test send finished. Check logs\daily_briefing_discord_test.log
