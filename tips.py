import os
import logging
from typing import List, Dict

import openpyxl

logger = logging.getLogger(__name__)

TIPS_FILE = os.environ.get("TIPS_FILE", "tips.xlsx")


class TipsLoader:
    def __init__(self):
        self.data: Dict[int, List[Dict]] = {}  # day -> list of tips

    def load(self):
        """Load tips from Excel file."""
        if not os.path.exists(TIPS_FILE):
            logger.warning(f"Tips file not found: {TIPS_FILE}")
            return

        wb = openpyxl.load_workbook(TIPS_FILE)
        ws = wb.active

        self.data = {}
        skipped = 0

        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if not row or row[0] is None:
                continue

            try:
                day = int(row[0])
                title = str(row[1]).strip() if row[1] else ""
                text = str(row[2]).strip() if row[2] else ""
            except (ValueError, TypeError):
                logger.warning(f"Row {row_idx}: invalid data {row}, skipping")
                skipped += 1
                continue

            if not text:
                logger.warning(f"Row {row_idx}: empty text for day {day}, skipping")
                skipped += 1
                continue

            if day not in self.data:
                self.data[day] = []

            self.data[day].append({"title": title, "text": text})

        logger.info(
            f"Loaded {sum(len(v) for v in self.data.values())} tips "
            f"for {len(self.data)} days. Skipped: {skipped}"
        )

    def get_tips_for_day(self, day: int) -> List[Dict]:
        """Return list of tips for a given pregnancy day."""
        return self.data.get(day, [])

    def reload(self):
        """Reload tips from file (useful after updating Excel)."""
        self.data = {}
        self.load()
