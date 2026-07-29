from api import DAMXClient

if __name__ == "__main__":
    # Option 1: Using Context Manager (Auto connects & disconnects)
    with DAMXClient() as client:
        if client.is_connected:
            # Get current settings
            settings = client.get_all_settings()
            print("Daemon Settings:", settings)

            # Change Fan Speed
            # if client.set_fan_speed(cpu=80, gpu=80):
            #     print("Fan speed updated successfully.")

            # Set thermal profile
            # client.set_thermal_profile("performance")

    # Option 2: Manual lifecycle management
    # client = DAMXClient()
    # client.connect()
    # ... actions ...
    # client.disconnect()
