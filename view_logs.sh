#!/bin/bash
# Simple script to view the last 50 lines of last_run.log

echo "Displaying last 50 lines of last_run.log..."
tail -n 50 last_run.log | cat
echo "Done." 
