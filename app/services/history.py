import csv
from flask import current_app

def log_prompt_row(row):
    path = current_app.config["PROMPTS_CSV"]
    header = ["timestamp","app","task","prompt","manual_summary"]
    write_header = False
    try:
        with open(path, "r", newline="", encoding="utf-8") as f:
            pass
    except FileNotFoundError:
        write_header = True
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        if write_header:
            w.writeheader()
        w.writerow(row)
