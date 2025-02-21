# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "click",
#     "openpyxl",
#     "requests",
#     "beautifulsoup4",
#     "rich",
#     "pandas",
# ]
# ///

import click
import pandas as pd
import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.progress import track
from dataclasses import dataclass, field
from typing import Optional, Dict
import re
from datetime import datetime
import os
import json
import hashlib
import urllib.parse

@dataclass
class ContractAmounts:
    action_obligation: Optional[float] = None
    base_and_exercised: Optional[float] = None
    base_and_all_options: Optional[float] = None

@dataclass
class ContractData:
    agency: str
    description: str
    saved_amount: float
    link: str
    current_amounts: ContractAmounts = field(default_factory=ContractAmounts)
    total_amounts: ContractAmounts = field(default_factory=ContractAmounts)
    status: str = "Not Verified"
    error: Optional[str] = None
    page_archive_id: Optional[str] = None
    accessed_date: Optional[str] = None

def extract_amounts_from_fpds(html_content: str) -> tuple[ContractAmounts, ContractAmounts]:
    """Extract all relevant amounts from FPDS HTML content."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        def parse_amount(element_id: str) -> Optional[float]:
            """Parse amount from FPDS HTML input field."""
            field = soup.find('input', {'id': element_id})
            if field and 'value' in field.attrs:
                amount_str = field['value']
                # Remove currency symbols, commas and convert to float
                cleaned_str = amount_str.replace('$', '').replace(',', '').strip()
                if cleaned_str:
                    return float(cleaned_str)
            return None

        # Current amounts
        current = ContractAmounts(
            action_obligation=parse_amount('obligatedAmount'),
            base_and_exercised=parse_amount('baseAndExercisedOptionsValue'),
            base_and_all_options=parse_amount('ultimateContractValue')
        )

        # Total amounts
        total = ContractAmounts(
            action_obligation=parse_amount('totalObligatedAmount'),
            base_and_exercised=parse_amount('totalBaseAndExercisedOptionsValue'),
            base_and_all_options=parse_amount('totalUltimateContractValue')
        )

        return current, total

    except Exception as e:
        print(f"Error parsing HTML: {e}")
        return ContractAmounts(), ContractAmounts()

def generate_archive_id(url: str, timestamp: str) -> str:
    """Generate a unique identifier for archived pages."""
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    
    components = [
        query.get('agencyID', [''])[0],
        query.get('PIID', [''])[0],
        query.get('modNumber', [''])[0],
        timestamp
    ]
    
    if not any(components):
        return hashlib.sha256(url.encode()).hexdigest()[:12]
    
    return '_'.join(filter(None, components))

def archive_webpage(html_content: str, archive_id: str, url: str, timestamp: str, archive_dir: str) -> dict:
    """Archive webpage content and metadata."""
    if not os.path.exists(archive_dir):
        os.makedirs(archive_dir)
    
    html_path = os.path.join(archive_dir, f"{archive_id}.html")
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    metadata = {
        'archive_id': archive_id,
        'original_url': url,
        'accessed_date': timestamp,
        'file_path': html_path
    }
    
    return metadata

def verify_contract(contract: ContractData, session: requests.Session, archive_dir: str) -> ContractData:
    """Verify a single contract by fetching and comparing FPDS data."""
    try:
        response = session.get(contract.link)
        response.raise_for_status()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        contract.accessed_date = timestamp
        
        archive_id = generate_archive_id(contract.link, timestamp)
        contract.page_archive_id = archive_id
        archive_webpage(response.text, archive_id, contract.link, timestamp, archive_dir)
        
        current_amounts, total_amounts = extract_amounts_from_fpds(response.text)
        contract.current_amounts = current_amounts
        contract.total_amounts = total_amounts

        # Compare saved amount with base_and_all_options (total contract value)
        if total_amounts.base_and_all_options is not None:
            if abs(total_amounts.base_and_all_options - contract.saved_amount) < 0.01:
                contract.status = "Verified"
            else:
                contract.status = "Mismatch"
        else:
            contract.status = "Error"
            contract.error = "Could not extract total contract value from FPDS"
            
    except requests.RequestException as e:
        contract.status = "Error"
        contract.error = f"Request failed: {str(e)}"
    
    return contract

def format_amount(amount: Optional[float]) -> str:
    """Format amount as currency string."""
    if amount is None:
        return "N/A"
    return f"${amount:,.2f}"

def save_results(verified_contracts, input_file, archive_dir):
    """Save verification results to Excel and CSV files."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_filename = f"fpds_verification_{timestamp}"
    
    results_df = pd.DataFrame([{
        'Agency': c.agency,
        'Description': c.description,
        'Saved Amount': c.saved_amount,
        'Current Action Obligation': c.current_amounts.action_obligation,
        'Current Base & Exercised': c.current_amounts.base_and_exercised,
        'Current Total Value': c.current_amounts.base_and_all_options,
        'Total Action Obligation': c.total_amounts.action_obligation,
        'Total Base & Exercised': c.total_amounts.base_and_exercised,
        'Total Contract Value': c.total_amounts.base_and_all_options,
        'Status': c.status,
        'Error': c.error if c.error else '',
        'Link': c.link,
        'Archive ID': c.page_archive_id,
        'Accessed Date': c.accessed_date,
        'Potential Savings': (
            c.total_amounts.base_and_all_options - c.total_amounts.base_and_exercised 
            if (c.total_amounts.base_and_all_options is not None and 
                c.total_amounts.base_and_exercised is not None)
            else None
        ),
        'Already Obligated': c.total_amounts.action_obligation
    } for c in verified_contracts])

    # Add summary statistics
    total_contracts = len(verified_contracts)
    verified_count = sum(1 for c in verified_contracts if c.status == "Verified")
    mismatch_count = sum(1 for c in verified_contracts if c.status == "Mismatch")
    error_count = sum(1 for c in verified_contracts if c.status == "Error")

    total_obligated = sum(
        c.total_amounts.action_obligation or 0 
        for c in verified_contracts 
        if c.total_amounts.action_obligation is not None
    )
    
    total_potential_savings = sum(
        (c.total_amounts.base_and_all_options or 0) - (c.total_amounts.base_and_exercised or 0)
        for c in verified_contracts 
        if (c.total_amounts.base_and_all_options is not None and 
            c.total_amounts.base_and_exercised is not None)
    )

    summary_df = pd.DataFrame([
        ['Total Contracts', total_contracts],
        ['Verified', verified_count],
        ['Mismatches', mismatch_count],
        ['Errors', error_count],
        ['Total Amount Obligated', format_amount(total_obligated)],
        ['Total Potential Savings', format_amount(total_potential_savings)]
    ], columns=['Metric', 'Value'])

    # Save to Excel with multiple sheets
    excel_path = os.path.join(archive_dir, f"{base_filename}.xlsx")
    with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
        results_df.to_excel(writer, sheet_name='Verification Results', index=False)
        summary_df.to_excel(writer, sheet_name='Summary', index=False)
        
        for sheet_name in writer.sheets:
            worksheet = writer.sheets[sheet_name]
            for column in worksheet.columns:
                max_length = 0
                column = list(column)
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = (max_length + 2)
                worksheet.column_dimensions[column[0].column_letter].width = min(adjusted_width, 50)

    # Save to CSV
    csv_path = os.path.join(archive_dir, f"{base_filename}.csv")
    results_df.to_csv(csv_path, index=False)

    return excel_path, csv_path

@click.command()
@click.argument('excel_file', type=click.Path(exists=True))
@click.option('--sheet', default='Contracts', help='Name of the sheet containing contract data')
def main(excel_file: str, sheet: str):
    """Verify contract amounts in FPDS against Excel spreadsheet data."""
    console = Console()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = f"verification_archive_{timestamp}"
    os.makedirs(archive_dir)
    
    try:
        df = pd.read_excel(excel_file, sheet_name=sheet)
        df = df[['AGENCY', 'DESCRIPTION', 'SAVED', 'LINK']].dropna()
    except Exception as e:
        console.print(f"[red]Error loading Excel file: {e}[/red]")
        return

    contracts = []
    for _, row in df.iterrows():
        contracts.append(ContractData(
            agency=row['AGENCY'],
            description=row['DESCRIPTION'],
            saved_amount=float(row['SAVED']),
            link=row['LINK']
        ))

    if not contracts:
        console.print("[red]No contract data found in the Excel file[/red]")
        return

    session = requests.Session()

    console.print("\n[bold]Verifying contracts...[/bold]")
    verified_contracts = []
    for contract in track(contracts, description="Verifying..."):
        verified_contracts.append(verify_contract(contract, session, archive_dir))

    table = Table(show_header=True, header_style="bold")
    table.add_column("Agency", width=30)
    table.add_column("Description", width=30)
    table.add_column("Saved Amount", justify="right")
    table.add_column("Total Contract Value", justify="right")
    table.add_column("Already Obligated", justify="right")
    table.add_column("Potential Savings", justify="right")
    table.add_column("Status")

    for contract in verified_contracts:
        saved_str = format_amount(contract.saved_amount)
        total_value = format_amount(contract.total_amounts.base_and_all_options)
        obligated = format_amount(contract.total_amounts.action_obligation)
        
        potential_savings = (
            contract.total_amounts.base_and_all_options - contract.total_amounts.base_and_exercised
            if (contract.total_amounts.base_and_all_options is not None and 
                contract.total_amounts.base_and_exercised is not None)
            else None
        )
        savings_str = format_amount(potential_savings)
        
        status_style = {
            "Verified": "green",
            "Mismatch": "yellow",
            "Error": "red"
        }.get(contract.status, "white")
        
        table.add_row(
            contract.agency[:30],
            contract.description[:30],
            saved_str,
            total_value,
            obligated,
            savings_str,
            f"[{status_style}]{contract.status}[/{status_style}]"
        )

    excel_path, csv_path = save_results(verified_contracts, excel_file, archive_dir)

    console.print("\n[bold]Verification Results:[/bold]")
    console.print(table)

    verified_count = sum(1 for c in verified_contracts if c.status == "Verified")
    mismatch_count = sum(1 for c in verified_contracts if c.status == "Mismatch")
    error_count = sum(1 for c in verified_contracts if c.status == "Error")
    
    total_obligated = sum(
        c.total_amounts.action_obligation or 0 
        for c in verified_contracts 
        if c.total_amounts.action_obligation is not None
    )
    
    total_potential_savings = sum(
        (c.total_amounts.base_and_all_options or 0) - (c.total_amounts.base_and_exercised or 0)
        for c in verified_contracts 
        if (c.total_amounts.base_and_all_options is not None and 
            c.total_amounts.base_and_exercised is not None)
    )
    
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"Total contracts: {len(verified_contracts)}")
    console.print(f"[green]Verified: {verified_count}[/green]")
    console.print(f"[yellow]Mismatches: {mismatch_count}[/yellow]")
    console.print(f"[red]Errors: {error_count}[/red]")
    console.print(f"\nTotal amount already obligated: {format_amount(total_obligated)}")
    console.print(f"Total potential savings: {format_amount(total_potential_savings)}")

    console.print("\n[bold]Results and archives saved to:[/bold]")
    console.print(f"Archive directory: {archive_dir}")
    console.print(f"Excel report: {excel_path}")
    console.print(f"CSV report: {csv_path}")

if __name__ == '__main__':
    main()