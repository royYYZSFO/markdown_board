#!/bin/bash
# Stops the Meticulous Board server
echo "Stopping Meticulous Board server..."
lsof -ti :7842 | xargs kill -9 2>/dev/null && echo "Done." || echo "Server was not running."
