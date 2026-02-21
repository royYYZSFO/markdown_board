-- Meticulous Board Launcher
-- Double-click to start the board server and open it in your browser.

set boardFolder to (path to home folder as text) & "Documents:Meticulous Board:"
set serverScript to boardFolder & "server.py"
set serverScriptPosix to POSIX path of serverScript

-- Check if server is already running
try
    do shell script "curl -s http://localhost:7783/ping"
    -- Already running Ñ just open browser
    open location "http://localhost:7783"
    return
end try

-- Start the server in the background
do shell script "cd " & quoted form of POSIX path of boardFolder & " && /usr/bin/python3 " & quoted form of serverScriptPosix & " > /tmp/meticulous-board.log 2>&1 &"

-- Wait for it to be ready (up to 5 seconds)
set attempts to 0
repeat
    delay 0.5
    set attempts to attempts + 1
    try
        do shell script "curl -s http://localhost:7783/ping"
        exit repeat
    end try
    if attempts > 10 then
        display alert "Meticulous Board" message "Server failed to start. Check /tmp/meticulous-board.log for details." as warning
        return
    end if
end repeat

-- Open the board in the default browser
open location "http://localhost:7783"
