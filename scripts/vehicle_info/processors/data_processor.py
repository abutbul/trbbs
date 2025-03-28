"""
Functions for processing and formatting vehicle data.
"""

import re
from vehicle_info.resources.vehicle_resources import PROPERTY_MAPPING
from vehicle_info.api.data_gov import get_vehicle_resource

def get_vehicle_info(mispar_rechev, resources):
    """
    Get all available vehicle information by querying all vehicle resources.
    
    Args:
        mispar_rechev: The vehicle number to search for
        resources: List of resource definitions
    
    Returns:
        Combined vehicle records or error message
    """
    all_results = {}
    errors = []
    
    # Query each resource
    for resource in resources:
        result = get_vehicle_resource(
            mispar_rechev, 
            resource['id'], 
            resource['csv'],
            resource['encoding']
        )
        
        if isinstance(result, list):
            all_results[resource['name']] = result
        else:
            errors.append(f"{resource['name']}: {result}")
    
    # Check if we got any data
    if not all_results:
        return f"No data found for vehicle number {mispar_rechev}. Errors: {', '.join(errors)}"
    
    # Return the combined results
    return {
        'results': all_results,
        'errors': errors
    }

def format_vehicle_info(result, vehicle_number):
    """
    Format vehicle information for display.
    
    Args:
        result: The result from get_vehicle_info
        vehicle_number: The vehicle number that was searched
        
    Returns:
        Formatted output string
    """
    output = []
    
    if isinstance(result, dict) and 'results' in result:
        
        # Track if we found any records
        found_records = False

        # Merge all records into a single consolidated view
        merged_data = {}

        # Process each resource's results
        for resource_name, records in result['results'].items():
            if records and len(records) > 0:
                found_records = True
                # Process all records, not just the first one
                for record in records:
                    # Add all fields from this record to the merged data
                    for key, value in record.items():
                        # If key already exists in merged_data, create a numbered version
                        if key in merged_data:
                            # Check if the value is the same
                            if merged_data[key] != value:
                                # Find the next available number for this key
                                counter = 1
                                while f"{key}-{counter}" in merged_data:
                                    counter += 1
                                # Add the field with a numbered suffix
                                merged_data[f"{key}-{counter}"] = value
                        else:
                            merged_data[key] = value

        # Display the consolidated information
        if merged_data:
            output.append("פרטים על הרכב")
            for key, value in sorted(merged_data.items()):
                # Skip any keys that are "_id" (case insensitive)
                if key.lower() == '_id':
                    continue

                # Check if this is a numbered field (e.g., "field-1")
                match = re.search(r'^(.+?)-(\d+)$', key)
                
                if match:
                    # This is a numbered field
                    base_key = match.group(1).lower()
                    number = match.group(2)
                    
                    # Skip any base keys that are "_id" (case insensitive)
                    if base_key == '_id':
                        continue
                        
                    if base_key in PROPERTY_MAPPING:
                        label = PROPERTY_MAPPING[base_key]
                    else:
                        # If no mapping found, use the original key
                        label = base_key
                        
                    # Print with number suffix
                    output.append(f"{label} ({number})\t{value}")
                else:
                    # Regular field (not numbered)
                    key_lower = key.lower()
                    if key_lower in PROPERTY_MAPPING:
                        output.append(f"{PROPERTY_MAPPING[key_lower]}\t{value}")
                    else:
                        # No mapping found, use the original key
                        output.append(f"{key}\t{value}")
                        
        # Display any errors
        # if result['errors']:
        #     output.append("\n--- Errors ---")
        #     for error in result['errors']:
        #         output.append(f"  {error}")

        if not found_records:
            output.append(f"No records found for vehicle number {vehicle_number}.")
    else:
        output.append(str(result))  # Print error message
        
    return "\n".join(output)