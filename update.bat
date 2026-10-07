@echo off
REM ============================================================
REM  GeM bid tracker - daily update
REM  Scrapes from THIS machine (Indian IP), then pushes to
REM  GitHub Pages. GitHub's runners cannot reach GeM.
REM ============================================================
setlocal
cd /d "%~dp0"

echo. >> update.log
echo ======== [%date% %time%] start ======== >> update.log

python gem_bids_scraper.py "laptop" "notebook"      >> update.log 2>&1
python gem_bids_scraper.py "desktop computer"       >> update.log 2>&1
python gem_bids_scraper.py "server" "all in one pc" >> update.log 2>&1
python gem_bids_scraper.py "workstation"            >> update.log 2>&1

python build_dashboard.py >> update.log 2>&1
if errorlevel 1 (
  echo [%date% %time%] BUILD FAILED - nothing pushed >> update.log
  exit /b 1
)

if not exist docs mkdir docs
copy /y dashboard.html docs\index.html >nul
copy /y bids.csv       docs\bids.csv   >nul

git add bids.csv bids.json docs >> update.log 2>&1
git diff --staged --quiet
if not errorlevel 1 (
  echo [%date% %time%] no changes to push >> update.log
  goto :done
)

git commit -m "data: %date%" >> update.log 2>&1

REM Remote may have moved (e.g. edits made on github.com). Rebase onto it
REM first; generated files always resolve in favour of our fresh copy.
git fetch origin >> update.log 2>&1
git rebase origin/main >> update.log 2>&1
if errorlevel 1 (
  echo [%date% %time%] rebase conflict - taking local generated files >> update.log
  git checkout --ours bids.csv bids.json docs/index.html docs/bids.csv >> update.log 2>&1
  git add bids.csv bids.json docs >> update.log 2>&1
  git -c core.editor=true rebase --continue >> update.log 2>&1
  if errorlevel 1 (
    git rebase --abort >> update.log 2>&1
    echo [%date% %time%] PUSH FAILED - rebase unrecoverable, fix by hand >> update.log
    exit /b 1
  )
)

git push >> update.log 2>&1
if errorlevel 1 (
  echo [%date% %time%] PUSH FAILED - dashboard is STALE on GitHub >> update.log
  echo    common cause: git credentials not cached for this account >> update.log
  exit /b 1
)
echo [%date% %time%] pushed OK >> update.log

:done
endlocal
