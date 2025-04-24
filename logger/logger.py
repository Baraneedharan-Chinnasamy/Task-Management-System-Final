import logging
import os
from datetime import datetime, timedelta

LOG_FOLDER = 'logger'
os.makedirs(LOG_FOLDER, exist_ok=True)

def trim_old_log_lines(file_path, days_to_keep=5):
    print(f"🧼 Cleaning {file_path}...")  # DEBUG — you'll see this in terminal
    if not os.path.exists(file_path):
        return

    cutoff = datetime.now() - timedelta(days=days_to_keep)
    new_lines = []
    deleted_count = 0

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                timestamp_str = line.split(" - ")[0].strip()
                log_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S,%f")
                if log_time >= cutoff:
                    new_lines.append(line)
                else:
                    deleted_count += 1
            except Exception:
                # If line can't be parsed, keep it to avoid accidental deletion
                new_lines.append(line)

    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

    print(f"[LOG CLEAN] {file_path}: Deleted {deleted_count} old lines.")

def get_logger(name, filename):
    log_path = os.path.join(LOG_FOLDER, filename)

    # ✅ Always run cleanup every time get_logger is called
    trim_old_log_lines(log_path, days_to_keep=5)

    logger = logging.getLogger(name)

    # Only attach handlers if not already attached
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)

        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(stream_handler)

    return logger
