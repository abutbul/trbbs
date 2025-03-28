"""
Main entry point for the vehicle information system.
"""

import sys
from vehicle_info.resources.vehicle_resources import VEHICLE_RESOURCES
from vehicle_info.processors.data_processor import get_vehicle_info, format_vehicle_info

def main():
    """
    Main function to process command line arguments and display vehicle information.
    """
    # Get vehicle number from command line arguments or use default
    if len(sys.argv) > 1:
        vehicle_number = sys.argv[1]
    else:
        vehicle_number = "3519130"  # Default example
        print(f"No vehicle number provided, using default: {vehicle_number}")

    # Get vehicle information
    result = get_vehicle_info(vehicle_number, VEHICLE_RESOURCES)
    
    # Format and display the results
    formatted_output = format_vehicle_info(result, vehicle_number)
    print(formatted_output)

if __name__ == "__main__":
    main()