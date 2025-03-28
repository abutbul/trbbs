"""
Utility functions for vehicle number handling.
"""

def normalize_vehicle_number(mispar_rechev):
    """
    Normalize vehicle number by ensuring it's a string and adding leading zeros if needed.
    
    Args:
        mispar_rechev: The vehicle number to normalize
        
    Returns:
        String representation of vehicle number, padded with leading zeros if needed
    """
    # Convert to string first
    mispar_str = str(mispar_rechev).strip()
    
    # If the number is less than 8 digits, pad with leading zeros
    if len(mispar_str) < 8:
        mispar_str = mispar_str.zfill(8)
        
    return mispar_str