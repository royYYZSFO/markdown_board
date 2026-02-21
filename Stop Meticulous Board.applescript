-- Stop the Meticulous Board server
try
    do shell script "lsof -ti:7783 | xargs kill -9"
    display notification "Meticulous Board server stopped." with title "Meticulous Board"
on error
    display notification "Server was not running." with title "Meticulous Board"
end try
