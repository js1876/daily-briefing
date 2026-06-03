@echo off
cd /d C:\Users\dltmddbs\Documents\Codex\daily-briefing
set GIT=C:\Program Files\Git\cmd\git.exe
python scripts\generate_daily_briefing.py >> logs\daily_briefing_task.log 2>&1

"%GIT%" add index.html public archive README.md .gitignore scripts run_daily_briefing.bat test_discord_briefing_send.bat >> logs\daily_briefing_task.log 2>&1
"%GIT%" diff --cached --quiet
if errorlevel 1 (
  "%GIT%" commit -m "Update daily briefing" >> logs\daily_briefing_task.log 2>&1
  "%GIT%" push >> logs\daily_briefing_task.log 2>&1
)
