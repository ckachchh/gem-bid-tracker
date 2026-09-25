@echo off
REM ============================================================
REM  GeM bid tracker - daily update
REM  Scrapes from THIS machine (Indian IP), then pushes the
REM  rebuilt dashboard to GitHub Pages.
REM  GitHub's own runners cannot reach GeM - connection refused.
REM ============================================================
setlocal
cd /d "%~dp0"

echo [%date% %time%] starting >> update.log

python gem_bids_scraper.py "laptop" "notebook"      >> update.log 2>&1
python gem_bids_scraper.py "desktop computer"       >> update.log 2>&1
python gem_bids_scraper.py "server" "all in one pc" >> update.log 2>&1
python gem_bids_scraper.py "workstation"            >> update.log 2>&1

python build_dashboard.py >> update.log 2>&1
if errorlevel 1 (
  echo [%date% %time%] BUILD FAILED - not pushing >> update.log
  exit /b 1
)

if not exist docs mkdir docs
copy /y dashboard.html docs\index.html >nul
copy /y bids.csv       docs\bids.csv   >nul

git add bids.csv bids.json docs
git diff --staged --quiet
if errorlevel 1 (
  git commit -m "data: %date%" >> update.log 2>&1
  git push                     >> update.log 2>&1
  echo [%date% %time%] pushed >> update.log
) else (
  echo [%date% %time%] no changes >> update.log
)
endlocal
