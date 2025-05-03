#!/bin/bash
# Simple script to view the last 50 lines of jarvis.log

echo "Displaying last 50 lines of jarvis.log..."
tail -n 50 jarvis.log | cat
echo "Done." 
