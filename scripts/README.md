```markdown
# FPDS Contract Verifier

This tool verifies federal contract amounts between an Excel spreadsheet and FPDS (Federal Procurement Data System) web pages.

## Requirements

- Python 3.12 or later
- uv (Python package manager)

## Setup

1. Install uv:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

2. Save the script as `fpds-verifier.py`

3. Run with uv:
```bash
uv run fpds-verifier.py your_spreadsheet.xlsx
```

## Input Format

Your Excel spreadsheet needs these columns:
- AGENCY
- DESCRIPTION  
- SAVED (dollar amount)
- LINK (URL to FPDS page)

## What it Does

1. Reads your spreadsheet
2. For each contract:
   - Opens the FPDS webpage
   - Gets three key amounts:
     - Action Obligation (money already spent)
     - Base and Exercised Options (current contract value)
     - Base and All Options (maximum possible value)
   - Saves a copy of the webpage
   - Compares the amounts

## Output

Creates a folder named `verification_archive_[timestamp]` containing:
- Excel file with verification results
- CSV file with same data
- Saved copies of all FPDS pages

The results show:
- Which contracts match
- Money already spent
- Potential savings
- Any errors found

## Basic Usage

```bash
uv run fpds-verifier.py DOGEReceipts.xlsx
```

## Common Issues

If you see `No contract data found`:
- Check your column names match exactly
- Make sure there's data in all required columns
- Verify your spreadsheet name is correct

Need help? Open an issue on GitHub with:
- Your spreadsheet format
- The exact error message
- What you expected to happen
```