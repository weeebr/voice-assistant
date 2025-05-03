#!/usr/bin/env python3
import datetime
import os

LOG_FILE_PATH = "transcriptions.log"
WORDS_PER_PAGE = 500

def analyze_log():
    """Reads the log file, calculates stats, and prints them."""
    if not os.path.exists(LOG_FILE_PATH):
        print(f"Error: Log file not found at '{LOG_FILE_PATH}'")
        return

    now = datetime.datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    periods = {
        "Today": today_start,
        "Yesterday": today_start - datetime.timedelta(days=1),
        "Last 7 Days": today_start - datetime.timedelta(days=7),
        "Last 30 Days": today_start - datetime.timedelta(days=30),
        "Last 6 Months": today_start - datetime.timedelta(days=180) 
    }
    
    # Initialize word counts
    stats = {period_name: 0 for period_name in periods}

    try:
        with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                parts = line.split('\t', 1)
                if len(parts) != 2:
                    # print(f"Warning: Skipping malformed line: {line}")
                    continue

                timestamp_str, text = parts
                
                try:
                    # Parse timestamp (adjust format if logger format differs)
                    entry_dt = datetime.datetime.fromisoformat(timestamp_str)
                except ValueError:
                    # print(f"Warning: Skipping line with invalid timestamp format: {timestamp_str}")
                    continue

                word_count = len(text.split())

                # --- Corrected Period Checking --- 
                # Check specific days first
                if entry_dt >= periods["Today"]:
                    stats["Today"] += word_count
                # Use elif to ensure yesterday doesn't include today
                elif entry_dt >= periods["Yesterday"]:
                     stats["Yesterday"] += word_count
                
                # Check cumulative periods independently
                # An entry from today or yesterday should also count towards these longer periods.
                if entry_dt >= periods["Last 7 Days"]:
                    stats["Last 7 Days"] += word_count
                if entry_dt >= periods["Last 30 Days"]:
                    stats["Last 30 Days"] += word_count
                if entry_dt >= periods["Last 6 Months"]:
                    stats["Last 6 Months"] += word_count
                # --- End Corrected Checking --- 

    except FileNotFoundError:
        print(f"Error: Log file disappeared during read: '{LOG_FILE_PATH}'")
        return
    except Exception as e:
        print(f"An error occurred during analysis: {e}")
        return

    # Print results
    print("--- Transcription Stats ---")
    print(f"(Assuming {WORDS_PER_PAGE} words ≈ 1 A4 page)")
    
    # Print in a specific order
    for period_name in ["Today", "Yesterday", "Last 7 Days", "Last 30 Days", "Last 6 Months"]:
         word_count = stats[period_name]
         # Always calculate pages, even if word_count is 0
         pages = round(word_count / WORDS_PER_PAGE, 1) 
         print(f"- {period_name:>13}: {word_count:>6} words ({pages:.1f} pages)")

    print("-------------------------")


if __name__ == "__main__":
    analyze_log() 
