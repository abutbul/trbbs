"""
Utility functions for CSV file handling.
"""

import csv
import os
from vehicle_info.utils.vehicle_utils import normalize_vehicle_number

def search_vehicle_in_csv(mispar_rechev, csv_path, encoding):
    """
    Search for a vehicle number in a local CSV file using a specific encoding.
    
    Args:
        mispar_rechev: The vehicle number to search for
        csv_path: Path to the CSV file
        encoding: The specific encoding to use for the CSV file
        
    Returns:
        List of records if found, None otherwise
    """
    if not os.path.exists(csv_path):
        # print(f"Warning: CSV file not found at {csv_path}")
        return None
    
    # Get both the original and padded vehicle number for comparison
    mispar_rechev_str = str(mispar_rechev)
    mispar_rechev_padded = normalize_vehicle_number(mispar_rechev)
    
    try:
        records = []
        with open(csv_path, 'r', encoding=encoding, errors='replace', newline='') as csvfile:
            # Use pipe as the delimiter based on provided CSV format
            reader = csv.DictReader(csvfile, delimiter='|')
            
            for row in reader:
                csv_vehicle_num = row.get('mispar_rechev', '')
                # Check against both padded and unpadded versions
                if (csv_vehicle_num == mispar_rechev_str or 
                    csv_vehicle_num == mispar_rechev_padded):
                    records.append(row)
        
        print(f"Successfully read CSV with encoding: {encoding}")
        return records if records else None
        
    except Exception as e:
        print(f"Error reading CSV with encoding {encoding}: {e}")
        
        # Fallback to binary mode if the specified encoding fails
        print("Trying binary mode with manual parsing...")
        try:
            with open(csv_path, 'rb') as csvfile:
                lines = csvfile.readlines()
                header = lines[0].decode('utf-8', errors='replace').strip().split('|')
                
                records = []
                for line in lines[1:]:
                    try:
                        # Try to decode each line with a safe fallback
                        decoded_line = line.decode(encoding, errors='replace').strip()
                        values = decoded_line.split('|')
                        
                        if len(values) >= len(header):
                            row = dict(zip(header, values))
                            csv_vehicle_num = row.get('mispar_rechev', '')
                            # Check against both padded and unpadded versions here too
                            if (csv_vehicle_num == mispar_rechev_str or 
                                csv_vehicle_num == mispar_rechev_padded):
                                records.append(row)
                    except:
                        continue
                
                return records if records else None
        except Exception as e:
            print(f"Binary mode reading also failed: {e}")
            return None