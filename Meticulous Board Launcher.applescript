set boardFolder to "/Users/royraanani/Library/CloudStorage/OneDrive-Personal/02 - Professional/05 - Meticulous Home/000-ai_ops/meticulous-board/"
set startScript to boardFolder & "start.command"
set serverPort to "7842"
set boardURL to "http://localhost:" & serverPort

-- Check if already running
try
    do shell script "lsof -ti :" & serverPort
    open location boardURL
    return
end try

-- Launch Terminal with the start script
tell application "Terminal"
    activate
    do script quoted form of startScript
end tell

delay 2

open location boardURL

display notification "Syncing to your Obsidian vault" with title "Meticulous Board" subtitle "Running at localhost:7842"