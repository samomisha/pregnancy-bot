import os
import logging
import json
from typing import List, Dict

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "1tLbRUYxRpvlUnHAA3F6R8eRezaatznONkDY8YhYczxg")


class TipsLoader:
    def __init__(self):
        self.data: Dict[int, List[Dict]] = {}  # day -> list of tips

    def load(self):
        """Load tips from Google Sheets."""
        try:
            # Define the scope for Google Sheets API
            scopes = [
                'https://www.googleapis.com/auth/spreadsheets.readonly'
            ]
            
            # Authenticate using service account credentials from environment variable
            credentials_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
            if not credentials_json:
                logger.warning("GOOGLE_CREDENTIALS_JSON environment variable not set")
                return
            
            try:
                credentials_info = json.loads(credentials_json)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse GOOGLE_CREDENTIALS_JSON: {e}")
                return
            
            creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
            client = gspread.authorize(creds)
            
            # Open the spreadsheet by ID
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            worksheet = spreadsheet.sheet1  # Get the first sheet
            
            # Get all values from the sheet
            rows = worksheet.get_all_values()
            
            self.data = {}
            skipped = 0
            
            # Skip header row (index 0), start from row 1
            for row_idx, row in enumerate(rows[1:], start=2):
                if not row or not row[0]:
                    continue
                
                try:
                    day = int(row[0])
                    title = str(row[1]).strip() if len(row) > 1 and row[1] else ""
                    text = str(row[2]).strip() if len(row) > 2 and row[2] else ""
                except (ValueError, TypeError, IndexError):
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
        except Exception as e:
            logger.error(f"Error loading tips from Google Sheets: {e}")

    def get_tips_for_day(self, day: int) -> List[Dict]:
        """Return list of tips for a given pregnancy day."""
        return self.data.get(day, [])

    def reload(self):
        """Reload tips from Google Sheets (useful after updating the spreadsheet)."""
        self.data = {}
        self.load()
