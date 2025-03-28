"""
Functions for interacting with the data.gov.il API.
"""

import requests
import os
from vehicle_info.utils.csv_utils import search_vehicle_in_csv

def get_vehicle_resource(mispar_rechev, resource_id, csv_filename, encoding):
    """
    Get vehicle information from a specific resource, first checking a local CSV file,
    then querying the data.gov.il API if not found locally.
    
    Args:
        mispar_rechev: The vehicle number to search for
        resource_id: The resource ID to query in the API
        csv_filename: The CSV filename to check locally
        encoding: The encoding to use for reading the CSV file
        
    Returns:
        The vehicle records or error message
    """
    # First, try to find the vehicle in the local CSV file
    csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                           "csv", csv_filename)
    
    local_records = search_vehicle_in_csv(mispar_rechev, csv_path, encoding)
    
    if local_records:
        print(f"Vehicle found in local CSV file for resource {resource_id}!")
        return local_records
    
    # print(f"Vehicle not found in local CSV for resource {resource_id}, querying API...")
    
    # If not found locally, query the API
    base_url = "https://data.gov.il/api/3/action/datastore_search"
    params = {
        'resource_id': resource_id,
        'limit': 5,
        'q': mispar_rechev
    }
    
    response = requests.get(base_url, params=params)
    
    if response.status_code == 200:
        data = response.json()
        # Check if the response contains records
        if data.get('success') and 'result' in data:
            records = data['result'].get('records', [])
            if records:
                return records
            else:
                return f"No records found for this vehicle number in resource {resource_id}"
        else:
            return f"API response format error or no data available for resource {resource_id}"
    else:
        return f"Error {response.status_code} querying resource {resource_id}"