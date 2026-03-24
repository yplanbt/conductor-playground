# Google Sheets Setup Guide

## Step 1: Create a Google Cloud Project
1. Go to https://console.cloud.google.com/
2. Click "Select a project" > "New Project"
3. Name it (e.g., "Tripoli") and click "Create"

## Step 2: Enable APIs
1. Go to "APIs & Services" > "Library"
2. Search and enable **Google Sheets API**
3. Search and enable **Google Drive API**

## Step 3: Create a Service Account
1. Go to "APIs & Services" > "Credentials"
2. Click "Create Credentials" > "Service Account"
3. Name it (e.g., "tripoli-sheets") and click "Create"
4. Skip the optional permissions steps, click "Done"

## Step 4: Download the Key
1. Click on the service account you just created
2. Go to "Keys" tab > "Add Key" > "Create New Key"
3. Choose **JSON** format and click "Create"
4. Save the downloaded file as `service_account.json` in the project root (same folder as `run.py`)

## Step 5: Configure Tripoli
Create a `.env` file in the project root:

```
GOOGLE_SHEETS_ENABLED=true
GOOGLE_SERVICE_ACCOUNT_FILE=service_account.json
GOOGLE_SHEETS_SHARE_EMAIL=your-email@gmail.com
GOOGLE_SHEETS_MAX_ARTICLES=50
```

Replace `your-email@gmail.com` with your actual Google account email. The spreadsheets will be automatically shared with this email so you can view them.

## Step 6: Install Dependencies
```bash
source venv/bin/activate
pip install gspread google-auth
```

## How It Works
- Each search pushes results to Google Sheets automatically
- A spreadsheet accumulates up to 50 articles across multiple searches
- Once a sheet has 50 articles, a new spreadsheet is created
- The sheet link appears in the UI after each search
